"""
baostock 行情，类 BaostockDataGateway。

对外
    start                按 period 分组起 daemon 线程轮询
    stop                 停线程并 logout
    get_kline_warm_up    数据预热：拉取最近 N 根 K 线
    get_today_ohlc       当日开高低（日线）
    get_depths           合成盘口（价由最新 close 铺档）

私有
    _start_poll          某 period 分组的主循环
    _fetch_data          拉指定天数内的 K 线
"""
import math
import random
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional

import baostock as bs  # type: ignore

from quant.data.baostock_fetcher import BaostockDataFetcher
from ...enums import GatewayMode, Period
from .base import DataGateway
from ...core.models import TickerData


class BaostockDataGateway(DataGateway):
    """轮询 baostock 最新 K 线；无真实 tick / Level2。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(mode=GatewayMode.POLL, **kwargs)

        # 行情拉取器
        self.data_fetcher: BaostockDataFetcher = BaostockDataFetcher(bs)
        self.data_fetcher.bs.login()

    def stop(self) -> None:
        """停止所有轮询线程并 logout。"""
        super().stop()
        if self.data_fetcher.bs is not None:
            self.data_fetcher.bs.logout()
            self.data_fetcher.bs = None

    def get_kline_warm_up(self, ticker: str, period: Period, size: int) -> List[TickerData]:
        """拉取最近 size 根 K 线作为数据预热，按 period 动态估算所需天数。"""
        days_needed = self._days_for_period(period, size)
        datas = self._fetch_data(ticker, period, days_needed)
        return datas[-size:] if datas else []

    def get_today_ohlc(self, ticker: str) -> Optional[Dict[str, float]]:
        """从最近日线取开、高、低；缺数据返回 None。"""
        try:
            data = self._fetch_data(ticker, Period.DAY_1, 7)
            if not data:
                return None
            row = data[-1]
            return {"open": row.open, "high": row.high, "low": row.low}
        except Exception as e:
            self.logger.exception(f"获取 {ticker} 当日 OHLC 失败: {e}")
            return None

    def get_depths(self, ticker: str, levels: int = 5) -> Dict[str, List[Dict[str, float]]]:
        """
        合成盘口（非真实 L2）：价由最新 5m close 按相对价差铺档；
        各档量在 [~5%·volume, volume] 内独立随机。
        """
        levels = max(1, min(int(levels), 10))
        try:
            data = self._fetch_data(ticker, Period.MINUTE_5, 7)
            if not data:
                return {"bids": [], "asks": []}
            row = data[-1]
            last_f = row.price
            if last_f <= 0:
                return {"bids": [], "asks": []}
            base = row.volume if row.volume and row.volume > 0 else 1000
        except Exception as e:
            self.logger.exception(f"get_depths {ticker}: {e}")
            return {"bids": [], "asks": []}

        lo = max(1, base // 20)
        hi = max(lo, base)
        step = max(last_f * 1e-4, 0.01)
        bids: List[Dict[str, float]] = []
        asks: List[Dict[str, float]] = []
        for i in range(levels):
            lv = float(i + 1)
            bids.append({"level": lv, "price": round(last_f - lv * step, 6), "volume": float(random.randint(lo, hi))})
            asks.append({"level": lv, "price": round(last_f + lv * step, 6), "volume": float(random.randint(lo, hi))})
        return {"bids": bids, "asks": asks}

    def start_poll(self, period: Period, tickers: List[str]) -> None:
        """回放昨天到现在的历史 K 线，模拟 QMT poll 模式逐根推送。"""
        replay_data: Dict[str, Deque[TickerData]] = {}
        for ticker in tickers:
            # 拉取最近 2 天数据作为回放序列；数据量不足时 bars 为空 deque，后续跳过
            data = self._fetch_data(ticker, period, 2)
            replay_data[ticker] = deque(data or [])
            self.logger.info(f"[baostock回放] {ticker} 预取 {len(replay_data[ticker])} 根 {period.code} K线")

        while self._running:
            for ticker in tickers:
                callback, _ = self._ticker_callbacks.get(ticker, (None, None))
                if not callback:
                    continue
                data = replay_data[ticker]
                if not data:
                    continue
                try:
                    callback(data.popleft())
                except Exception as e:
                    self.logger.exception(f"回放 {ticker} 数据出错: {str(e)}")
            # 按 period 节奏 sleep，模拟新 bar 产生的时间间隔
            time.sleep(period.fetch_seconds)

    def _fetch_data(self, ticker: str, period: Period, days: int) -> List[TickerData]:
        """用已登录会话拉近 days 日 K 线。"""
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return self.data_fetcher.fetch_data(ticker, period, start, end)

    @staticmethod
    def _days_for_period(period: Period, bars: int) -> int:
        """估算拉取 bars 根 K 线所需的日历天数。"""
        if period.days_per_bar > 0:
            return math.ceil(bars * period.days_per_bar) * 2
        trading_seconds_per_day = 4 * 3600
        return math.ceil(bars * period.fetch_seconds / trading_seconds_per_day * (7 / 5)) * 2
