"""
全局共享数据模型。TickerData 和 SignalData 被 data/、live/、strategy/、adapters/ 各层共同使用，
放在 core/ 层避免循环导入。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..enums import Signal


@dataclass
class SignalData:
    timestamp: datetime
    signal: Signal
    # 本次信号建议的买卖股数上限（买卖双侧），None 表示不限
    quantity: Optional[int] = None


@dataclass
class TickerData:
    ticker: str
    timestamp: datetime
    # 最新价（实时场景为 tick 价，K 线场景为 close 价）
    price: float
    # K 线 OHLCV；纯 tick 场景 open/high/low 为 None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None
    # 买一/卖一；网关有 L2 时填入
    bid: Optional[float] = None
    ask: Optional[float] = None
