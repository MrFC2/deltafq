"""
订单管理器。
"""

import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime
from ..enums import OrderType, OrderStatus, Signal
from ..core.base import BaseComponent


class OrderManager(BaseComponent):
    """订单管理器。"""

    def __init__(self, **kwargs):
        """初始化订单管理器。"""
        super().__init__(**kwargs)
        self.orders = {}

    def create_order(self,
                     ticker: str,
                     signal: Signal,
                     quantity: int,
                     order_type: OrderType = None,
                     price: Optional[float] = None,
                     stop_price: Optional[float] = None) -> Dict[str, Any]:
        """创建新订单，返回订单字典。quantity 为正整数，方向由 signal 决定。"""
        order_id = f"ORD_{len(self.orders) + 1:06d}"

        order = {
            'id': order_id,
            'ticker': ticker,
            'signal': signal,
            'quantity': quantity,
            'order_type': order_type,
            'price': price,
            'stop_price': stop_price,
            'status': OrderStatus.PENDING,
            'created_at': datetime.now(),
        }

        self.orders[order_id] = order
        return order

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 查询订单。"""
        return self.orders.get(order_id)

    def update_order_status(self, order_id: str, status: OrderStatus) -> bool:
        """更新订单状态。"""
        if order_id in self.orders:
            self.orders[order_id]['status'] = status
            return True
        return False

    def mark_executed(self, order_id: str, execution_price: Optional[float] = None) -> bool:
        """标记订单为已成交。"""
        if order_id in self.orders:
            self.orders[order_id]['status'] = OrderStatus.EXECUTED
            self.orders[order_id]['execution_price'] = execution_price
            self.orders[order_id]['executed_at'] = datetime.now()
            return True
        return False

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单。"""
        if order_id in self.orders and self.orders[order_id]['status'] == OrderStatus.PENDING:
            self.orders[order_id]['status'] = OrderStatus.CANCELLED
            return True
        return False

    def get_orders_by_status(self, status: OrderStatus) -> List[Dict[str, Any]]:
        """查询指定状态的所有订单。"""
        return [order for order in self.orders.values() if order['status'] == status]

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """查询所有挂单。"""
        return self.get_orders_by_status(OrderStatus.PENDING)

    def get_executed_orders(self) -> List[Dict[str, Any]]:
        """查询所有已成交订单。"""
        return self.get_orders_by_status(OrderStatus.EXECUTED)

    def get_order_history(self) -> List[Dict[str, Any]]:
        """获取完整订单历史。"""
        return list(self.orders.values())

    def cleanup_old_orders(self, days: int = 30) -> int:
        """清理旧订单。"""
        cutoff_date = datetime.now() - pd.Timedelta(days=days)
        old_orders = [
            order_id for order_id, order in self.orders.items()
            if order['created_at'] < cutoff_date and order['status'] in {OrderStatus.EXECUTED, OrderStatus.CANCELLED}
        ]

        for order_id in old_orders:
            del self.orders[order_id]

        return len(old_orders)
