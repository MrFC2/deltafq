"""
交易执行引擎。
"""

from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime
from ..core.base import BaseComponent
from .order_manager import OrderManager
from .position_manager import PositionManager

from ..enums import OrderType, Signal

if TYPE_CHECKING:
    from ..core.models import TickerData


class TraderEngine(BaseComponent):
    """模拟交易执行引擎，内部管理资金、持仓、订单。"""

    def __init__(self,
                 cash: Optional[float] = None,
                 commission: Optional[float] = None,
                 match_on_tick: bool = False,
                 **kwargs):
        """初始化执行引擎。"""
        super().__init__(**kwargs)
        # 是否在 tick 到达时撮合挂单（True=模拟撮合，False=立即成交）
        self.match_on_tick = match_on_tick
        # 当前可用资金
        self.cash = cash
        # 手续费率
        self.commission = commission
        # 成交记录列表
        self.trades = []
        # 订单管理器
        self.order_manager = OrderManager()
        # 持仓管理器
        self.position_manager = PositionManager()

    def execute_order(self,
                      ticker: str,
                      signal: Signal,
                      quantity: int,
                      order_type: OrderType,
                      price: Optional[float] = None,
                      timestamp: Optional[datetime] = None) -> str:
        """执行订单。signal 决定买卖方向，quantity 为正整数。"""
        try:
            # 限价单校验价格
            if order_type == OrderType.LIMIT and price is None:
                raise ValueError("限价单必须提供价格")

            # 创建订单
            order = self.order_manager.create_order(ticker, signal, quantity, order_type, price)
            order_id = order['id']

            # 模拟：立即成交或挂单等待撮合
            if not self.match_on_tick:
                self._on_trade(order_id, price, timestamp)
            return order_id

        except Exception as e:
            raise RuntimeError(f"订单执行失败: {str(e)}") from e

    def on_tick(self, ticker_data: TickerData) -> None:
        """对挂单进行 tick 撮合。"""
        for order in self.order_manager.get_pending_orders():
            if order["ticker"] != ticker_data.ticker:
                continue
            sig, ot, p = order["signal"], order["order_type"], order["price"]
            match = ot == OrderType.MARKET or (sig == Signal.BUY and ticker_data.price <= p) or (sig == Signal.SELL and ticker_data.price >= p)
            if match:
                self._on_trade(order["id"], ticker_data.price, ticker_data.timestamp)
                break  # 每个 tick 每标的只撮合一笔

    def _on_trade(self,
                  order_id: str,
                  execution_price: float,
                  timestamp: Optional[datetime] = None):
        """成交后统一结算：更新资金、持仓、订单状态和成交记录。"""
        order = self.order_manager.get_order(order_id)
        if not order:
            return

        ticker = order['ticker']
        signal = order['signal']
        quantity = order['quantity']
        timestamp = timestamp or datetime.now()

        if signal == Signal.BUY:  # 买入
            gross_cost = quantity * execution_price
            commission_amount = gross_cost * self.commission
            total_cost = gross_cost + commission_amount

            if total_cost <= self.cash:
                self.cash -= total_cost
                self.position_manager.add_position(ticker, quantity, execution_price)
                self.order_manager.mark_executed(order_id, execution_price)

                # 记录成交
                self.trades.append({
                    'order_id': order_id,
                    'ticker': ticker,
                    'quantity': quantity,
                    'price': execution_price,
                    'type': 'buy',
                    'timestamp': timestamp,
                    'commission': commission_amount,
                    'cost': total_cost
                })
            else:
                self.logger.warning(f"买入资金不足: 需要 {total_cost:.2f}，当前 {self.cash:.2f}")
                self.order_manager.cancel_order(order_id)
        else:  # 卖出（signal == Signal.SELL）
            if self.position_manager.can_sell(ticker, quantity):
                gross_revenue = quantity * execution_price
                commission_amount = gross_revenue * self.commission
                net_revenue = gross_revenue - commission_amount

                # 计算盈亏
                buy_cost = self._get_latest_buy_cost(ticker)
                profit_loss = net_revenue - buy_cost if buy_cost else net_revenue

                self.position_manager.reduce_position(ticker, quantity)
                self.cash += net_revenue
                self.order_manager.mark_executed(order_id, execution_price)

                # 记录成交
                self.trades.append({
                    'order_id': order_id,
                    'ticker': ticker,
                    'quantity': quantity,
                    'price': execution_price,
                    'type': 'sell',
                    'timestamp': timestamp,
                    'commission': commission_amount,
                    'gross_revenue': gross_revenue,
                    'net_revenue': net_revenue,
                    'buy_cost': buy_cost,
                    'profit_loss': profit_loss
                })
            else:
                self.logger.warning(f"卖出持仓不足: {ticker}，需要 {quantity}")
                self.order_manager.cancel_order(order_id)

    def _get_latest_buy_cost(self, ticker: str) -> float:
        """获取最近一笔买入成本，用于计算盈亏。"""
        for trade in reversed(self.trades):
            if trade.get('ticker') == ticker and trade.get('type') == 'buy':
                return float(trade.get('cost', 0.0))
        return 0.0
