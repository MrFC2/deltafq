"""
Trade execution engine for DeltaFQ.
"""

from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime
from ..core.base import BaseComponent
from .order_manager import OrderManager
from .position_manager import PositionManager

if TYPE_CHECKING:
    from ..live.models import TickData


class ExecutionEngine(BaseComponent):
    """
    Trade execution engine for real-time trading.
    Supports paper trading (broker=None) and live trading (broker=adapter).
    Paper trading manages cash internally. Live trading uses broker for account info.
    """
    
    def __init__(self, broker=None, initial_capital: Optional[float] = None,
                 commission: float = 0.001, match_on_tick: bool = False, **kwargs):
        """
        Initialize execution engine.
        Args:
            broker: Broker adapter for live trading. None for paper trading.
            initial_capital: Initial capital for paper trading. Defaults to 1000000.
            commission: Commission rate for paper trading. Defaults to 0.001.
            match_on_tick: If True, paper limit orders stay pending until on_tick matches (simulation).
                If False (default), paper orders fill at once (backtest).
        """
        super().__init__(**kwargs)
        self.broker = broker
        self.match_on_tick = match_on_tick
        self.order_manager = OrderManager()
        self.position_manager = PositionManager()
        
        # Paper trading mode: manage cash internally
        if broker is None:
            self.initial_capital = initial_capital if initial_capital is not None else 1000000
            self.cash = self.initial_capital
            self.commission = commission
            self.trades: List[Dict[str, Any]] = []
            self.is_paper_trading = True
        else:
            # Live trading mode: get account info from broker
            self.cash = None
            self.commission = None
            self.trades = []
            self.is_paper_trading = False
    
    def initialize(self) -> bool:
        """Initialize execution engine."""
        if self.is_paper_trading:
            self.logger.info(f"初始化模拟交易执行引擎，初始资金: {self.initial_capital}")
        else:
            self.logger.info("初始化实盘交易执行引擎")
        
        if self.broker:
            return self.broker.initialize()
        
        return True
    
    def execute_order(self, ticker: str, quantity: int, order_type: str = "limit", 
                     price: Optional[float] = None, timestamp: Optional[datetime] = None) -> str:
        """Execute an order. Default is limit order (price required)."""
        try:
            # Validate price for limit orders
            if order_type == "limit" and price is None:
                raise ValueError("限价单必须提供价格")
            
            # Create order
            order_id = self.order_manager.create_order(
                ticker=ticker,
                quantity=quantity,
                order_type=order_type,
                price=price
            )
            
            # Execute through broker
            if self.broker:
                broker_order_id = self.broker.place_order(
                    ticker=ticker,
                    quantity=quantity,
                    order_type=order_type,
                    price=price
                )
                
                # Update order with broker ID
                order = self.order_manager.get_order(order_id)
                if order:
                    order['broker_order_id'] = broker_order_id
                
                self.logger.info(f"订单已执行（券商）: {order_id} -> {broker_order_id}，日期: {timestamp.date()}，价格: {price}，数量: {quantity}")
            else:
                if not self.match_on_tick:
                    self._on_trade(order_id, price, timestamp)
                    self.logger.info(f"订单已执行（模拟）: {order_id}，日期: {timestamp.date()}，价格: {price}，数量: {quantity}")
                else:
                    side = "[SELL]" if quantity < 0 else "[BUY]"
                    self.logger.info(f"○ Order pending: {order_id} {side} {ticker} qty={abs(quantity)} @ {price:.2f}")
            
            return order_id
            
        except Exception as e:
            raise RuntimeError(f"订单执行失败: {str(e)}") from e

    def on_tick(self, tick: "TickData") -> None:
        """Match pending orders against tick (for EventEngine-driven simulation)."""
        if not self.is_paper_trading:
            return
        for order in self.order_manager.get_pending_orders():
            if order["ticker"] != tick.ticker:
                continue
            q, ot, p = order["quantity"], order["order_type"], order["price"]
            match = ot == "market" or (q > 0 and tick.price <= p) or (q < 0 and tick.price >= p)
            if match:
                self._on_trade(order["id"], tick.price, tick.timestamp)
                break  # one fill per tick per ticker, keep it simple

    def _on_trade(self, order_id: str, execution_price: float, timestamp: Optional[datetime] = None):
        """Unified settlement entry after a trade. Updates cash, position, order status and trade record."""
        order = self.order_manager.get_order(order_id)
        if not order:
            return
        
        ticker = order['ticker']
        quantity = order['quantity']
        timestamp = timestamp or datetime.now()
        
        if quantity > 0:  # Buy
            gross_cost = quantity * execution_price
            commission_amount = gross_cost * self.commission
            total_cost = gross_cost + commission_amount
            
            if total_cost <= self.cash:
                self.cash -= total_cost
                self.position_manager.add_position(ticker, quantity, execution_price)
                self.order_manager.mark_executed(order_id, execution_price)
                
                # Record trade (unified record with full details)
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
                self.logger.info(f"✓ Order filled: {order_id} [BUY] {ticker} qty={quantity} @ {execution_price:.2f}")
            else:
                self.logger.warning(f"买入资金不足: 需要 {total_cost:.2f}，当前 {self.cash:.2f}")
                self.order_manager.cancel_order(order_id)
        else:  # Sell
            quantity = abs(quantity)
            if self.position_manager.can_sell(ticker, quantity):
                gross_revenue = quantity * execution_price
                commission_amount = gross_revenue * self.commission
                net_revenue = gross_revenue - commission_amount
                
                # Calculate profit/loss
                buy_cost = self._get_latest_buy_cost(ticker)
                profit_loss = net_revenue - buy_cost if buy_cost else net_revenue
                
                self.position_manager.reduce_position(ticker, quantity)
                self.cash += net_revenue
                self.order_manager.mark_executed(order_id, execution_price)
                
                # Record trade (unified record with full details)
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
                self.logger.info(f"✓ Order filled: {order_id} [SELL] {ticker} qty={quantity} @ {execution_price:.2f}")
            else:
                self.logger.warning(f"卖出持仓不足: {ticker}，需要 {quantity}")
                self.order_manager.cancel_order(order_id)
    
    def _get_latest_buy_cost(self, ticker: str) -> float:
        """Get the latest buy cost for a ticker (for PnL calculation)."""
        for trade in reversed(self.trades):
            if trade.get('ticker') == ticker and trade.get('type') == 'buy':
                return float(trade.get('cost', 0.0))
        return 0.0

