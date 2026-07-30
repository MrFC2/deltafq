from abc import ABC, abstractmethod

from ...core.models import OrderRequest


class TradeGateway(ABC):
    """实盘交易网关抽象：连接、下单、撤单、关闭、账户查询。"""

    @abstractmethod
    def connect(self) -> bool:
        """建立交易连接。"""
        raise NotImplementedError

    @abstractmethod
    def send_order(self, req: OrderRequest) -> str:
        """发送委托，返回委托号。"""
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤销指定委托。"""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """停止交易网关并释放资源。"""
        raise NotImplementedError

    @abstractmethod
    def get_cash(self) -> float:
        """返回当前可用资金。"""
        raise NotImplementedError

    @abstractmethod
    def get_position(self, ticker: str) -> int:
        """返回指定标的可用持仓股数。"""
        raise NotImplementedError

    @abstractmethod
    def get_commission(self) -> float:
        """返回佣金率。"""
        raise NotImplementedError

    @abstractmethod
    def is_order_terminal(self, order_id: str) -> bool:
        """委托是否已终结（成交或撤单），终结则无需再操作。"""
        raise NotImplementedError
