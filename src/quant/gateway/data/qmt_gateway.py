"""
miniQMT 行情（xtdata），类 QmtDataGateway。

对外
    start                开 daemon：poll 轮询或 push 订分笔
    stop                 停线程，push 会退订
    get_kline_warm_up    数据预热：拉取最近 N 根 K 线
    get_today_ohlc       当日开高低（从快照解析）
    get_depths           买卖盘口（从快照解析）

私有
    _unsubscribe_push    push 停时退订
    _start_poll          按间隔拉全快照轮询
    _start_push          订分笔并阻塞 run
    _on_push_datas       分笔回调里组 TickerData
    _poll_tick           拉实时快照
    _poll_kline          拉最新一根 K 线
    _get_full_tick       封装 get_full_tick
    _bid_ask_from_dict   快照 dict 取买一卖一
    _ts_from_millis_or_now  行情时间转 datetime
"""
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from xtquant import xtdata  # type: ignore

from quant.data.qmt_fetcher import fetch_data
from .base import DataGateway
from ...core.models import TickerData
from ...enums import GatewayMode, Period


class QmtDataGateway(DataGateway):
    """poll 定时拉全快照，push 订分笔推送；xt 标的代码，Tick 含最新价及可选买卖盘。"""

    def __init__(self,
                 dividend_type: str = "none",
                 mode: GatewayMode = GatewayMode.POLL,
                 **kwargs: Any) -> None:
        """K 线除权类型、模式 poll 或 push。"""
        super().__init__(**kwargs)

        # --- 配置参数 ---
        # K 线除权类型（none / 前复权等）
        self.dividend_type = dividend_type
        # 行情模式：poll 定时拉全快照，push 订分笔
        self.mode: GatewayMode = mode

        # --- 运行时状态 ---
        # 轮询/推送线程运行标志
        self._running = False
        # 后台 daemon 线程列表（每个 period 分组对应一个线程）
        self._threads: List[threading.Thread] = []
        # push 模式下各标的订阅序号，退订时使用
        self._ticker_sub_seqs: List[int] = []
        # K 线模式下各标的上次推送的 K 线时间戳，用于去重
        self._last_kline_ts: Dict[str, Optional[datetime]] = {}

    def start(self) -> None:
        """起后台线程：poll 轮询快照，push 订分笔并跑 xtdata.run。"""
        if self._running:
            return
        self._running = True

        if self.mode == GatewayMode.PUSH:
            # PUSH：xtdata.run() 是全局事件循环只能调一次，所有 ticker 在同一个线程里订阅
            t = threading.Thread(target=self._start_push, daemon=True)
            self._threads.append(t)
            t.start()
            return

        # POLL：按 period 分组，每组起一个 daemon 线程
        period_tickers: Dict[Period, List[str]] = defaultdict(list)
        for ticker, (_, period) in self._ticker_callbacks.items():
            period_tickers[period].append(ticker)
        for period, tickers in period_tickers.items():
            t = threading.Thread(target=self._start_poll, args=(period, tickers), daemon=True)
            self._threads.append(t)
            t.start()

    def stop(self) -> None:
        """停线程；push 会退订并调 stop（若有）；join 等线程结束。"""
        self._running = False
        if self.mode == GatewayMode.PUSH:
            self._unsubscribe_push()
        for t in self._threads:
            t.join(timeout=5.0)
        self._threads.clear()

    def get_today_ohlc(self, ticker: str) -> Optional[Dict[str, float]]:
        """从快照取当日开、高、低三个 float；缺或错返回 None。"""
        tick = self._get_full_tick(ticker)
        if not tick:
            self.logger.error(f"get_today_ohlc: {ticker} 无快照")
            return None
        try:
            o = tick.get("open")
            h = tick.get("high") or tick.get("highPrice")
            l_ = tick.get("low") or tick.get("lowPrice")
            if o is None or h is None or l_ is None:
                return None
            return {"open": float(o), "high": float(h), "low": float(l_)}
        except Exception as e:
            self.logger.exception(f"get_today_ohlc 解析错误: {e}")
            return None

    def get_depths(self, ticker: str, levels: int = 5) -> Dict[str, List[Dict[str, float]]]:
        """返回买卖盘口深度（价格+委托量）。"""
        tick = self._get_full_tick(ticker)
        if not tick:
            return {"bids": [], "asks": []}
        lv = max(1, min(int(levels), 10))
        bids: List[Dict[str, float]] = []
        asks: List[Dict[str, float]] = []

        for i in range(1, lv + 1):
            bp = self._level_value(tick, "bid", "price", i)
            bv = self._level_value(tick, "bid", "volume", i)
            ap = self._level_value(tick, "ask", "price", i)
            av = self._level_value(tick, "ask", "volume", i)
            if bp is not None:
                bids.append({"level": float(i), "price": bp, "volume": float(bv or 0.0)})
            if ap is not None:
                asks.append({"level": float(i), "price": ap, "volume": float(av or 0.0)})
        return {"bids": bids, "asks": asks}

    def get_kline_warm_up(self, ticker: str, period: Period, size: int) -> List[TickerData]:
        """拉取最近 size 根 K 线作为数据预热。"""
        datas = fetch_data(ticker, None, None, period=period, dividend_type=self.dividend_type, count=size)
        return datas or []

    # ---------- 私有 ----------

    def _unsubscribe_push(self) -> None:
        """push 停时逐个退订 quote，再调 xtdata.stop（有则调）。"""
        if not self._ticker_sub_seqs:
            return
        try:
            for seq in self._ticker_sub_seqs:
                try:
                    xtdata.unsubscribe_quote(seq)
                except Exception as e:
                    self.logger.exception(f"unsubscribe_quote {seq} 失败: {e}")
            self._ticker_sub_seqs.clear()
            stop_fn = getattr(xtdata, "stop", None)
            if callable(stop_fn):
                stop_fn()
        except Exception as e:
            self.logger.exception(f"push 清理失败: {e}")

    def _start_poll(self, period: Period, tickers: List[str]) -> None:
        """按 period 轮询行情，TICK 模式拉实时快照，K 线模式等到新 K 线才推送。"""
        while self._running:
            for ticker in tickers:
                callback, _ = self._ticker_callbacks.get(ticker, (None, None))
                if period == Period.TICK:
                    # 拉取实时信息
                    ticker_data = self._poll_tick(ticker)
                else:
                    # K 线模式：拿到新数据才推送，旧数据等下一轮
                    ticker_data = self._poll_kline(ticker, period)

                if ticker_data and callback:
                    callback(ticker_data)

            # 加多3秒，给第三方缓冲时间统计数据
            time.sleep(period.fetch_seconds + 3)

    def _poll_tick(self, ticker: str) -> Optional[TickerData]:
        """拉实时快照，返回 TickerData；失败返回 None。"""
        tick = self._get_full_tick(ticker)
        self.logger.info(f"_poll_tick data: {tick}")
        if not tick:
            return None
        price = tick.get("lastPrice") or tick.get("last") or tick.get("price")
        if price is None:
            return None
        ts = self._ts_from_millis_or_now(tick.get("time"))
        bid, ask = self._bid_ask_from_dict(tick)
        vol = tick.get("volume") or tick.get("lastVolume") or 0
        return TickerData(ticker=ticker, timestamp=ts, price=float(price), volume=int(vol), bid=bid, ask=ask)

    def _poll_kline(self, ticker: str, period: Period) -> Optional[TickerData]:
        """拉最新一根 K 线，是新数据才返回，旧数据返回 None 由外层下一轮重试。"""
        datas = fetch_data(ticker, None, None, period=period, dividend_type=self.dividend_type, count=1)
        if not datas:
            return None
        data = datas[-1]
        last_ts = self._last_kline_ts.get(ticker)
        if last_ts is not None and data.timestamp <= last_ts:
            # 还是旧数据，返回 None，外层下一轮再试
            return None
        # 是新 K 线，记录时间戳并返回
        self._last_kline_ts[ticker] = data.timestamp
        return data

    def _start_push(self) -> None:
        """逐只 subscribe_quote（每只用注册时的 period），最后阻塞 xtdata.run。
        start() 的 PUSH 路径只建一个线程调此方法，保证 xtdata.run() 全局只调一次。
        """
        # 防御性检查：线程启动时已被 stop
        if not self._running:
            return

        # 逐个标的订阅分笔行情，各自使用注册时传入的 period
        for ticker, (_, period) in self._ticker_callbacks.items():
            seq = xtdata.subscribe_quote(ticker, period=period.code, start_time="", end_time="", count=0,
                                         callback=self._push_callback)
            if seq < 0:
                self.logger.error(f"subscribe_quote 失败 {ticker}: {seq}")
                continue
            self._ticker_sub_seqs.append(seq)

        # 无成功订阅则退出
        if not self._ticker_sub_seqs:
            return

        # 阻塞运行 xtdata 事件循环，直到 stop() 调用 unsubscribe
        try:
            xtdata.run()
        except Exception as e:
            if self._running:
                self.logger.error(f"xtdata.run 异常: {e}")

    def _push_callback(self, data: dict) -> None:
        """分笔推送回调：行转 TickerData 再交 tick 回调"""
        self.logger.info(f"_on_push_datas data: {data}")
        if not self._running:
            return
        # datas 结构：{标的代码: [分笔行, ...]}
        for code, rows in (data or {}).items():
            for row in rows or []:
                # 跳过格式异常的推送数据
                if not isinstance(row, dict):
                    continue
                # 兼容多种字段名
                price = row.get("lastPrice") or row.get("last_price") or row.get("price")
                if price is None:
                    continue
                vol = row.get("volume") or row.get("lastVolume") or 0
                ts = self._ts_from_millis_or_now(row.get("time"))
                bid, ask = self._bid_ask_from_dict(row)
                ticker_data = TickerData(ticker=code, price=float(price), timestamp=ts, volume=int(vol),
                                         bid=bid, ask=ask)
                entry = self._ticker_callbacks.get(code)
                if entry:
                    callback, _ = entry
                    callback(ticker_data)

    def _get_full_tick(self, ticker: str) -> Optional[Dict[str, Any]]:
        """调 get_full_tick；成功返回快照，失败返回 None。"""
        data = xtdata.get_full_tick([ticker])
        if not data or ticker not in data:
            return None
        return data[ticker]

    @staticmethod
    def _bid_ask_from_dict(d: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """从行情 dict 取买一卖一；若买价大于卖价则对调一次。"""

        def _to_f(v: Any) -> Optional[float]:
            if v is None:
                return None
            if isinstance(v, (list, tuple)) and len(v) > 0:
                v = v[0]
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        bid = d.get("bid1") or d.get("bidPrice") or d.get("bid") or d.get("bidPx")
        ask = d.get("ask1") or d.get("askPrice") or d.get("ask") or d.get("askPx")
        b, a = _to_f(bid), _to_f(ask)
        if b is not None and a is not None and b > a:
            return a, b
        return b, a

    @classmethod
    def _level_value(cls, d: Dict[str, Any], side: str, kind: str, idx: int) -> Optional[float]:
        """取指定档位字段，兼容数组字段和逐档字段。"""
        if side == "bid":
            arr_keys = ["bidPrice", "bid", "bidPx"] if kind == "price" else ["bidVol", "bidVolume", "bidQty"]
            scalar_keys = (
                [f"bid{idx}", f"bidPrice{idx}", f"bidPx{idx}"]
                if kind == "price"
                else [f"bidVol{idx}", f"bidVolume{idx}", f"bidQty{idx}"]
            )
        else:
            arr_keys = ["askPrice", "ask", "askPx"] if kind == "price" else ["askVol", "askVolume", "askQty"]
            scalar_keys = (
                [f"ask{idx}", f"askPrice{idx}", f"askPx{idx}"]
                if kind == "price"
                else [f"askVol{idx}", f"askVolume{idx}", f"askQty{idx}"]
            )

        for key in arr_keys:
            arr = d.get(key)
            if isinstance(arr, (list, tuple)) and len(arr) >= idx:
                return cls._to_float(arr[idx - 1])
        for key in scalar_keys:
            if key in d:
                return cls._to_float(d.get(key))
        return None

    @staticmethod
    def _to_float(v: Any) -> Optional[float]:
        """将任意值转为 float，失败返回 None。"""
        if v is None:
            return None
        if isinstance(v, (list, tuple)) and len(v) > 0:
            v = v[0]
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _ts_from_millis_or_now(raw: Any) -> datetime:
        """时间戳毫秒太长则按毫秒除；坏了或没有就用本机当前时间。"""
        if raw is None:
            return datetime.now().replace(tzinfo=None)
        try:
            n = int(raw)
            if n > 10 ** 12:
                n = n // 1000
            return datetime.fromtimestamp(n)
        except (TypeError, ValueError, OSError):
            return datetime.now().replace(tzinfo=None)
