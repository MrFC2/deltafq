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
    YAHOO = "yahoo"
    BAOSTOCK = "baostock"
    MINIQMT = "miniqmt"


class EventType(Enum):
    """事件总线事件类型。"""
    TICK = "tick"
    ORDER = "order"
    TRADE = "trade"
    ACCOUNT = "account"
    POSITION = "position"


class Interval(Enum):
    """K 线周期。"""
    REALTIME = "realtime"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    DAY_1 = "1d"
    WEEK_1 = "1wk"
    MONTH_1 = "1mo"
