"""
miniQMT 交易网关，类 MiniQmtTradeGateway。

对外
    __init__      注入连接参数、策略名、委托备注、手数
    client        暴露底层 MiniQmtXtTraderClient，便于查询柜台数据
    connect       连接 miniQMT 交易端
    stop          断开连接并清理
    send_order    接收统一 OrderRequest，转柜台限价单并返回字符串委托号
    cancel_order  按委托号撤单，失败时按合同号兜底再撤
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import TradeGateway
from ...enums import OrderType
from .miniqmt_client import MiniQmtXtTraderClient

logger = logging.getLogger(__name__)

# miniQMT order_status 终态：已成交、已撤单、部分撤单、废单等（见 documents/MiniQmtTrade.md）
_MINIQMT_ORDER_STATUS_TERMINAL = frozenset({53, 54, 56, 57})


class MiniQmtTradeGateway(TradeGateway):
    """连接 miniQMT 并适配 LiveEngine 的下单撤单接口。"""

    def __init__(
            self,
            userdata_mini_path: Optional[str] = None,
            account_id: Optional[str] = None,
            session_id: Optional[int] = None,
            strategy_name: str = "deltafq",
            order_remark: str = "",
            lot_size: int = 100,
    ) -> None:
        """初始化柜台参数；lot_size 用于数量对齐，默认按 A 股 100 股一手。"""
        self._strategy_name = strategy_name
        self._order_remark = order_remark
        self._lot_size = max(1, int(lot_size))
        self._client = MiniQmtXtTraderClient(userdata_mini_path, account_id, session_id)

    @property
    def client(self) -> MiniQmtXtTraderClient:
        """底层交易客户端；可直接查资金、持仓、委托、成交。"""
        return self._client

    def connect(self) -> bool:
        """连接交易端并订阅资金账号。"""
        return self._client.connect()

    def stop(self) -> None:
        """断开交易端连接。"""
        self._client.disconnect()

    def send_order(self,
                   ticker: str,
                   quantity: int,
                   price: float,
                   order_type: OrderType = OrderType.LIMIT) -> str:
        """仅支持限价单；数量按 lot_size 向下对齐；返回字符串委托号。"""
        if order_type != OrderType.LIMIT:
            raise ValueError("MiniQmtTradeGateway 当前仅支持限价单")
        qty = int(quantity)
        if qty == 0:
            raise ValueError("数量不能为零")
        abs_vol = abs(qty)
        if abs_vol % self._lot_size != 0:
            aligned = (abs_vol // self._lot_size) * self._lot_size
            if aligned <= 0:
                raise ValueError(f"数量 {qty} 小于最小手数（{self._lot_size}）")
            logger.warning("adjusting quantity %s -> %s (lot_size=%s)", abs_vol, aligned, self._lot_size)
            abs_vol = aligned
        is_buy = qty > 0
        oid = self._client.order_stock_limit(ticker, abs_vol, float(price), is_buy, strategy_name=self._strategy_name, order_remark=self._order_remark)
        if oid is None or int(oid) <= 0:
            raise RuntimeError(f"下单失败: oid={oid!r}")
        return str(int(oid))

    def get_cash(self) -> float:
        if not self._client.is_connected():
            return 0.0
        try:
            asset = self._client.query_stock_asset()
            return float(getattr(asset, "cash", 0.0) or 0.0) if asset is not None else 0.0
        except Exception as e:
            logger.warning("query_stock_asset 失败: %s", e)
            return 0.0

    def get_position(self, ticker: str) -> int:
        if not self._client.is_connected():
            return 0
        try:
            for p in self._client.query_stock_positions() or []:
                if (getattr(p, "stock_code", "") or "") == ticker:
                    return int(getattr(p, "can_use_volume", None) or getattr(p, "volume", 0) or 0)
        except Exception as e:
            logger.warning("query_stock_positions 失败: %s", e)
        return 0

    def get_commission(self) -> float:
        return 0.001

    def is_order_terminal(self, order_id: str) -> bool:
        if not self._client.is_connected():
            return False
        try:
            target = int(str(order_id).strip())
        except ValueError:
            return True
        try:
            for row in self._client.query_stock_orders(cancelable_only=False) or []:
                brid = getattr(row, "order_id", None)
                if brid is None:
                    continue
                try:
                    matched = int(brid) == target
                except (TypeError, ValueError):
                    matched = str(brid).strip() == str(order_id).strip()
                if matched:
                    st = int(getattr(row, "order_status", -1))
                    return st in _MINIQMT_ORDER_STATUS_TERMINAL
            return True
        except Exception as e:
            logger.warning("查询挂单 %s 失败: %s", order_id, e)
            return False

    def cancel_order(self, order_id: str) -> bool:
        """先按委托号撤；失败则在可撤委托里查合同号并兜底撤单。"""
        try:
            oid = int(str(order_id).strip())
        except ValueError:
            return False
        if oid <= 0:
            return False
        try:
            rc = self._client.cancel_order_stock(oid)
        except Exception as e:
            logger.warning("cancel_order_stock %s: %s", oid, e)
            rc = -1
        if rc == 0:
            return True
        # 兜底：可撤委托里按 order_id 找合同号
        try:
            for o in self._client.query_stock_orders(cancelable_only=True):
                brid = getattr(o, "order_id", None)
                if brid is None:
                    continue
                try:
                    if int(brid) != oid:
                        continue
                except (TypeError, ValueError):
                    if str(brid).strip() != str(oid):
                        continue
                code = getattr(o, "stock_code", "") or ""
                sysid = getattr(o, "order_sysid", None)
                if code and sysid:
                    rc2 = self._client.cancel_order_stock_sysid(code, str(sysid))
                    return rc2 == 0
        except Exception as e:
            logger.warning("cancel fallback query: %s", e)
        return False
