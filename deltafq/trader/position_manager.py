"""
Position management for DeltaFQ.
"""

from typing import Dict, Optional
from datetime import datetime
from ..core.base import BaseComponent


class PositionManager(BaseComponent):
    """持仓管理器。"""
    
    def __init__(self, **kwargs):
        """初始化持仓管理器。"""
        super().__init__(**kwargs)
        self.positions = {}
        self.logger.info("初始化持仓管理器")
    
    def add_position(self, ticker: str, quantity: int, price: Optional[float] = None) -> bool:
        """增加或新建持仓。"""
        if ticker in self.positions:
            # 更新已有持仓
            current_quantity = self.positions[ticker]['quantity']
            current_avg_price = self.positions[ticker]['avg_price']
            
            new_quantity = current_quantity + quantity
            if price:
                new_avg_price = ((current_quantity * current_avg_price) + (quantity * price)) / new_quantity
            else:
                new_avg_price = current_avg_price
            
            self.positions[ticker]['quantity'] = new_quantity
            self.positions[ticker]['avg_price'] = new_avg_price
            self.positions[ticker]['updated_at'] = datetime.now()
        else:
            # 新建持仓
            self.positions[ticker] = {
                'ticker': ticker,
                'quantity': quantity,
                'avg_price': price or 0.0,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
        
        self.logger.info(f"↑ 持仓已更新: {ticker} -> {self.positions[ticker]['quantity']}")
        return True
    
    def reduce_position(self, ticker: str, quantity: int) -> bool:
        """减少持仓。"""
        if ticker not in self.positions:
            self.logger.warning(f"未找到标的持仓: {ticker}")
            return False
        
        current_quantity = self.positions[ticker]['quantity']
        if current_quantity < quantity:
            self.logger.warning(f"持仓数量不足: {ticker}")
            return False
        
        new_quantity = current_quantity - quantity
        
        if new_quantity == 0:
            del self.positions[ticker]
        else:
            self.positions[ticker]['quantity'] = new_quantity
            self.positions[ticker]['updated_at'] = datetime.now()
        
        self.logger.info(f"↓ 持仓已减少: {ticker} -> {new_quantity}")
        return True
    
    def get_position(self, ticker: str) -> int:
        """查询标的当前持仓数量。"""
        return self.positions.get(ticker, {}).get('quantity', 0)
    
    def get_all_positions(self) -> Dict[str, int]:
        """查询所有持仓。"""
        return {ticker: pos['quantity'] for ticker, pos in self.positions.items()}
    
    def can_sell(self, ticker: str, quantity: int) -> bool:
        """检查是否可以卖出指定数量。"""
        return self.get_position(ticker) >= quantity
    
    def close_position(self, ticker: str) -> bool:
        """清空指定标的持仓。"""
        if ticker not in self.positions:
            return False

        quantity = self.positions[ticker]['quantity']
        return self.reduce_position(ticker, quantity)
