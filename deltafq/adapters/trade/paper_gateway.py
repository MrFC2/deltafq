from .base import TradeGateway
from ...core.models import OrderRequest
from ...trader.engine import TraderEngine


class PaperTradeGateway(TradeGateway):
    def __init__(self, initial_capital: float = 1_000_000.0, commission: float = 0.001) -> None:
        self._engine = TraderEngine(
            cash=initial_capital,
            commission=commission,
            match_on_tick=True,
        )

    def connect(self) -> bool:
        return True

    def send_order(self, req: OrderRequest) -> str:
        return self._engine.execute_order(
            ticker=req.ticker,
            quantity=req.quantity,
            order_type=req.order_type,
            price=req.price,
            timestamp=req.timestamp,
        )

    def cancel_order(self, order_id: str) -> bool:
        return self._engine.order_manager.cancel_order(order_id)

    def stop(self) -> None:
        pass
