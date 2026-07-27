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
    YAHOO = "yahoo"  # yfinance
    BAOSTOCK = "baostock"  # baostock（A 股历史 K 线）
    MINIQMT = "miniqmt"  # xtquant（需本机运行 miniQMT 终端）


class EventType(Enum):
    """事件总线事件类型。"""
    TICK = "tick"
    ORDER = "order"
    TRADE = "trade"
    ACCOUNT = "account"
    POSITION = "position"
