from abc import ABC, abstractmethod

from ...core.models import OrderRequest


class TradeGateway(ABC):
    """实盘交易网关抽象：连接、下单、撤单、关闭。"""

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
