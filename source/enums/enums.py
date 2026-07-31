"""
订单相关枚举。
"""

from enum import Enum


class OrderType(Enum):
    """订单类型。"""
    LIMIT = "limit"  # 限价单
    MARKET = "market"  # 市价单


class OrderStatus(Enum):
    """订单状态。"""
    PENDING = "pending"  # 待成交
    EXECUTED = "executed"  # 已成交
    CANCELLED = "cancelled"  # 已撤销


class CombineMethod(Enum):
    """多信号合并方式。"""
    VOTE = "vote"  # 多数投票
    WEIGHTED = "weighted"  # 加权求和


class DataSource(Enum):
    """行情数据源。"""
    BAOSTOCK = "baostock"
    MINIQMT = "miniqmt"


class EventType(Enum):
    """事件总线事件类型。"""
    TICK = "tick"
    ORDER = "order"
    TRADE = "trade"
    ACCOUNT = "account"
    POSITION = "position"


class Signal(int, Enum):
    """策略信号方向。"""
    BUY = 1  # 买入
    HOLD = 0  # 持仓不动
    SELL = -1  # 卖出


class Interval(Enum):
    """K 线周期。refetch_seconds: 实盘重拉间隔；days_per_bar: 估算日历天数用于拉足 lookback。"""

    def __init__(self, _: str, refetch_seconds: int = 0, days_per_bar: float = 0.0):
        self.refetch_seconds = refetch_seconds
        self.days_per_bar = days_per_bar

    REALTIME = ("realtime", 0, 0.0)
    MINUTE_1 = ("1m", 60, 0.0)
    MINUTE_5 = ("5m", 300, 0.0)
    MINUTE_15 = ("15m", 900, 0.0)
    MINUTE_30 = ("30m", 1800, 0.0)
    HOUR_1 = ("1h", 3600, 0.0)
    DAY_1 = ("1d", 86400, 365 / 252)
    WEEK_1 = ("1wk", 60, 365 / 52)
    MONTH_1 = ("1mo", 60, 365 / 12)
