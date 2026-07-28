from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..enums import OrderType


@dataclass
class TickData:
    ticker: str
    timestamp: datetime
    # 最新价（close）
    price: float
    # K 线 OHLCV；纯 tick 场景 open/high/low 为 None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None
    # 暖机标志；warmup tick 不触发策略
    is_warm_up: bool = False
    # 买一/卖一；网关有 L2 时填入
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class OrderRequest:
    ticker: str
    quantity: int
    price: float
    order_type: OrderType = OrderType.LIMIT
    timestamp: Optional[datetime] = None
