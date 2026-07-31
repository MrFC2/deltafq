"""
baostock 行情，类 BaostockDataGateway。

对外
    connect              bs.login
    subscribe            追加订阅标的
    start                开 daemon 线程轮询最新 5m
    stop                 停线程并 logout
    get_today_ohlc       当日开高低（日线）
    get_depths           合成盘口（价由最新 close 铺档）

私有
    _run                 主循环：bar 时间戳变化才推送
    _fetch_recent_7_day_data  已登录会话拉近 7 日 K 线
"""
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from source.data.baostock_fetcher import BaostockDataFetcher
from ...enums import Interval
from .base import DataGateway
from ...core.models import TickerData


class BaostockDataGateway(DataGateway):
    """轮询 baostock 5m 最新价；无真实 tick / Level2。"""

    def __init__(self, interval: float = 60.0, **kwargs: Any) -> None:
        """
        初始化 BaostockDataGateway。

        Args:
            interval: 轮询间隔（秒），默认 60s。
        """
        super().__init__(**kwargs)

        # --- 配置参数 ---
        # 轮询间隔（秒）
        self.interval: float = interval

        # --- 订阅状态 ---
        # 已订阅标的列表
        self._tickers: List[str] = []
        # 各标的最后一根 K 线时间戳，用于去重推送
        self._last_data_timestamp: Dict[str, Any] = {}

        # --- 运行时状态 ---
        # 轮询线程运行标志
        self._running: bool = False
        # 轮询 daemon 线程
        self._thread: Optional[threading.Thread] = None

        # 行情拉取器
        import baostock as bs
        self.data_fetcher: BaostockDataFetcher = BaostockDataFetcher(bs)

    def connect(self) -> bool:
        """登录 baostock，将 session 注入 fetcher。"""
        try:
            self.data_fetcher.bs.login()
            return True
        except Exception as e:
            self.logger.error(f"连接失败: {e}")
            return False

    def subscribe(self, tickers: List[str]) -> bool:
        """追加订阅标的。"""
        new_ticker = [s for s in tickers if s not in self._tickers]
        for ticker in new_ticker:
            self._tickers.append(ticker)
        return True

    def start(self) -> None:
        """启动轮询线程。"""
        if self._running:
            return
        self.logger.info("启动 baostock 轮询")
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止轮询线程并 logout。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self.data_fetcher.bs is not None:
            self.data_fetcher.bs.logout()
            self.data_fetcher.bs = None
        self.logger.info("已停止 baostock 轮询")

    def get_today_ohlc(self, ticker: str) -> Optional[Dict[str, float]]:
        """从最近日线取开、高、低；缺数据返回 None。"""
        try:
            data = self._fetch_recent_7_day_data(ticker, Interval.DAY_1)
            if not data:
                return None
            row = data[-1]
            return {"open": row.open, "high": row.high, "low": row.low}
        except Exception as e:
            self.logger.error(f"获取 {ticker} 当日 OHLC 失败: {e}")
            return None

    def get_depths(self, ticker: str, levels: int = 5) -> Dict[str, List[Dict[str, float]]]:
        """
        合成盘口（非真实 L2）：价由最新 5m close 按相对价差铺档；
        各档量在 [~5%·volume, volume] 内独立随机。
        """
        levels = max(1, min(int(levels), 10))
        try:
            data = self._fetch_recent_7_day_data(ticker, Interval.MINUTE_5)
            if not data:
                return {"bids": [], "asks": []}
            row = data[-1]
            last_f = row.price
            if last_f <= 0:
                return {"bids": [], "asks": []}
            base = row.volume if row.volume and row.volume > 0 else 1000
        except Exception as e:
            self.logger.debug(f"get_depths {ticker}: {e}")
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

    # ---------- 私有 ----------

    def _run(self) -> None:
        """轮询各标的最新 5m；仅 bar 时间变化时组 TickerData 回调。"""
        while self._running:
            for ticker in self._tickers:
                try:
                    data = self._fetch_recent_7_day_data(ticker, Interval.MINUTE_5)
                    if not data:
                        continue
                    # 取最新数据进行推送
                    latest_data = data[-1]
                    data_timestamp = latest_data.timestamp
                    # 同一根 K 线不重复推送
                    if self._last_data_timestamp.get(ticker) == data_timestamp:
                        continue
                    self._last_data_timestamp[ticker] = data_timestamp
                    if self._push:
                        self._push(latest_data)
                except Exception as e:
                    self.logger.error(f"拉取 {ticker} 数据出错: {str(e)}")
                    continue
            time.sleep(self.interval)

    def _fetch_recent_7_day_data(self, ticker: str, interval: Interval) -> List[TickerData]:
        """用已登录会话拉近 7 日 K 线。"""
        start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return self.data_fetcher.fetch_data(ticker, start, end, interval=interval)
