"""
订单相关枚举。
"""

from enum import Enum


class OrderType(Enum):
    """订单类型。"""
    LIMIT = "limit"    # 限价单
    MARKET = "market"  # 市价单


class OrderStatus(Enum):
    """订单状态。"""
    PENDING = "pending"       # 待成交
    EXECUTED = "executed"     # 已成交
    CANCELLED = "cancelled"   # 已撤销
