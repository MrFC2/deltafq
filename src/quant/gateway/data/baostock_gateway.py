"""
baostock 行情，类 BaostockDataGateway。

对外
    start                开 daemon 线程轮询最新 5m
    stop                 停线程并 logout
    get_kline_warm_up    数据预热：拉取最近 N 根 K 线
    get_today_ohlc       当日开高低（日线）
    get_depths           合成盘口（价由最新 close 铺档）

私有
    _run                 主循环：bar 时间戳变化才推送
    _fetch_data          拉指定天数内的 K 线
"""
import math
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from quant.data.baostock_fetcher import BaostockDataFetcher
from ...enums import Period
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


        # --- 運行時状態 ---
        # 轮询线程运行标志
        self._running: bool = False
        # 轮询 daemon 线程
        self._thread: Optional[threading.Thread] = None

        # 行情拉取器
        import baostock as bs
        self.data_fetcher: BaostockDataFetcher = BaostockDataFetcher(bs)
        self.data_fetcher.bs.login()

    def start(self) -> None:
        """启动轮询线程。"""
        if self._running:
            return
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

    def get_kline_warm_up(self, ticker: str, period: Period, size: int) -> List[TickerData]:
        """拉取最近 size 根 K 线作为数据预热，按 period 动态估算所需天数。"""
        if period.days_per_bar > 0:
            # 日/周/月线：直接按每根 bar 对应日历天数估算，加 2 倍缓冲
            days_needed = math.ceil(size * period.days_per_bar) * 2
        else:
            # 分钟/小时线：按 fetch_seconds 换算，交易日约 4 小时，再乘 7/5 换算日历天
            trading_seconds_per_day = 4 * 3600
            days_needed = math.ceil(size * period.fetch_seconds / trading_seconds_per_day * (7 / 5)) * 2
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

    # ---------- 私有 ----------

    def _run(self) -> None:
        """轮询各标的最新 5m，推送最新一根 K 线，幂等校验由上层 engine 负责。"""
        while self._running:
            for ticker, (callback, _) in list(self._ticker_callbacks.items()):
                try:
                    data = self._fetch_data(ticker, Period.MINUTE_5, 7)
                    if not data:
                        continue
                    if callback:
                        callback(data[-1])
                except Exception as e:
                    self.logger.exception(f"拉取 {ticker} 数据出错: {str(e)}")
                    continue
            time.sleep(self.interval)

    def _fetch_data(self, ticker: str, period: Period, days: int) -> List[TickerData]:
        """用已登录会话拉近 days 日 K 线。"""
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return self.data_fetcher.fetch_data(ticker, period, start, end)
