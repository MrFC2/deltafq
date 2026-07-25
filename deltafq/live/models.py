from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TickData:
    ticker: str
    price: float
    timestamp: datetime
    volume: Optional[int] = None
    source: Optional[str] = None
    # 行情侧若有买一/卖一（如 xtdata get_full_tick），由网关填入；无则默认 None
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class OrderRequest:
    ticker: str
    quantity: int
    price: float
    order_type: str = "limit"
    timestamp: Optional[datetime] = None
