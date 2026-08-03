from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Tuple

from ...core.models import TickerData
from ...core.base import BaseComponent
from ...enums import Period


class DataGateway(BaseComponent, ABC):
    """实盘行情网关抽象：连接、订阅、推送与日内行情查询。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # ticker → (callback, period) 映射，网关通过 keys() 知道订阅了哪些标的
        self._ticker_callbacks: Dict[str, Tuple[Callable[[TickerData], None], Period]] = {}
        # 行情循环运行标志
        self._running: bool = False

    def register_ticker_callback(self,
                                 ticker: str,
                                 callback: Callable[[TickerData], None],
                                 period: Period) -> None:
        """注册某个标的的 Tick 推送回调，注册时携带 period，供 gateway 内部分组建线程。"""
        self._ticker_callbacks[ticker] = (callback, period)

    @abstractmethod
    def start(self) -> None:
        """启动行情循环（轮询或推送）。"""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """停止网关并释放资源。"""
        raise NotImplementedError

    @abstractmethod
    def get_kline_warm_up(self, ticker: str, period: Period, size: int) -> List[TickerData]:
        """拉取最近 size 根 K 线作为数据预热，供 engine 填充历史窗口。"""
        raise NotImplementedError

    @abstractmethod
    def get_today_ohlc(self, ticker: str) -> Optional[Dict[str, float]]:
        """返回当日开高低；不可用时返回 None。"""
        raise NotImplementedError

    @abstractmethod
    def get_depths(self, ticker: str, levels: int = 5) -> Dict[str, List[Dict[str, float]]]:
        """返回盘口深度：bids/asks 各档价格与委托量。"""
        raise NotImplementedError
