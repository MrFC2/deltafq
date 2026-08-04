from .base import TradeGateway
from ...core.models import SignalData, TickerData
from ...enums import OrderType
from ...trader.engine import TraderEngine


class PaperTradeGateway(TradeGateway):
    def __init__(self,
                 initial_capital: float = 1_000_000.0,
                 commission: float = 0.001) -> None:
        self._engine = TraderEngine(cash=initial_capital, commission=commission, enable_tick_match=True)

    def send_order(self,
                   ticker: str,
                   signal_data: SignalData,
                   price: float,
                   order_type: OrderType = OrderType.LIMIT) -> str:
        return self._engine.execute_order(ticker, signal_data.signal, signal_data.quantity, order_type, price)

    def cancel_order(self, order_id: str) -> bool:
        return self._engine.order_manager.cancel_order(order_id)

    def stop(self) -> None:
        pass

    def get_cash(self) -> float:
        return float(self._engine.cash or 0.0)

    def get_position(self, ticker: str) -> int:
        return int(self._engine.position_manager.get_position(ticker))

    def get_commission(self) -> float:
        return float(self._engine.commission or 0.0)

    def is_order_terminal(self, order_id: str) -> bool:
        o = self._engine.order_manager.get_order(order_id)
        if o is None:
            return True
        return (o.get("status") or "").lower() in ("executed", "cancelled")

    def match_pending_orders(self, ticker_data: TickerData) -> None:
        self._engine.match_pending_orders(ticker_data)

    def get_trades(self) -> list:
        return list(self._engine.trade_records)
