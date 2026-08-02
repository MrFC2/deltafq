from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

from ...core.models import TickerData
from ...core.base import BaseComponent
from ...enums import Period


class DataGateway(BaseComponent, ABC):
    """实盘行情网关抽象：连接、订阅、推送与日内行情查询。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # ticker → 回调映射，网关通过 _callback.keys() 知道订阅了哪些标的
        self._callback: Dict[str, Callable[[TickerData], None]] = {}
        self._period: Period = Period.MINUTE_5

    def register_callback(self, ticker: str, callback: Callable[[TickerData], None]) -> None:
        """注册某个标的的 Tick 推送回调，同时完成订阅。"""
        self._callback[ticker] = callback

    def connect(self) -> bool:
        """建立网关连接；子类在 __init__ 完成连接时可不覆写。"""
        return True

    @abstractmethod
    def start(self, period: Period) -> None:
        """启动行情循环（轮询或推送）。"""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """停止网关并释放资源。"""
        raise NotImplementedError

    @abstractmethod
    def get_today_ohlc(self, ticker: str) -> Optional[Dict[str, float]]:
        """返回当日开高低；不可用时返回 None。"""
        raise NotImplementedError

    @abstractmethod
    def get_depths(self, ticker: str, levels: int = 5) -> Dict[str, List[Dict[str, float]]]:
        """返回盘口深度：bids/asks 各档价格与委托量。"""
        raise NotImplementedError
