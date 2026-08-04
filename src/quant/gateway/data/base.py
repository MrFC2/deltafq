import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from ...core.models import TickerData
from ...core.base import BaseComponent
from ...enums import GatewayMode, Period


class DataGateway(BaseComponent, ABC):
    """实盘行情网关抽象：连接、订阅、推送与日内行情查询。"""

    def __init__(self, mode: GatewayMode = GatewayMode.POLL, **kwargs) -> None:
        super().__init__(**kwargs)
        self.mode: GatewayMode = mode
        self._ticker_callbacks: Dict[str, Tuple[Callable[[TickerData], None], Period]] = {}
        self._running: bool = False
        self._threads: List[threading.Thread] = []

    def register_ticker_callback(self,
                                 ticker: str,
                                 callback: Callable[[TickerData], None],
                                 period: Period) -> None:
        """注册某个标的的 Tick 推送回调，注册时携带 period，供 gateway 内部分组建线程。"""
        self._ticker_callbacks[ticker] = (callback, period)

    def start(self) -> None:
        """启动行情：push 模式单线程跑 _start_push，poll 模式按 period 分组跑 _start_poll。"""
        if self._running:
            return
        self._running = True

        if self.mode == GatewayMode.PUSH:
            # PUSH：xtdata.run() 是全局事件循环只能调一次，所有 ticker 在同一个线程里订阅
            t = threading.Thread(target=self.start_push, daemon=True)
            self._threads.append(t)
            t.start()
            return

        # POLL：按 period 分组，每组起一个 daemon 线程
        period_tickers: Dict[Period, List[str]] = defaultdict(list)
        for ticker, (_, period) in self._ticker_callbacks.items():
            period_tickers[period].append(ticker)
        for period, tickers in period_tickers.items():
            t = threading.Thread(target=self.start_poll, args=(period, tickers), daemon=True)
            self._threads.append(t)
        # 开始运行
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        """停止行情，join 所有线程。子类可 override 追加清理逻辑后调 super().stop()。"""
        self._running = False
        for t in self._threads:
            t.join(timeout=5.0)
        self._threads.clear()

    def start_poll(self, period: Period, tickers: List[str]) -> None:
        """poll 模式实现，子类按需 override。"""
        raise NotImplementedError

    def start_push(self) -> None:
        """push 模式实现，子类按需 override。"""
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
