"""
miniQMT 行情（xtdata），类 MiniQmtDataGateway。

对外
    connect              加载 xtdata，需 miniQMT 已开
    subscribe            追加标的并 1m 暖机回放
    start                开 daemon：poll 轮询或 push 订分笔
    stop                 停线程，push 会退订
    get_today_ohlc       当日开高低（从快照解析）
    get_depths           买卖盘口（从快照解析）

私有
    _warm_up             近一日 1m 合成暖机 tick
    _unsubscribe_push    push 停时退订
    _run_poll            按间隔拉全快照轮询
    _run_push            订分笔并阻塞 run
    _on_push_tick        分笔回调里组 TickerData
    _get_full_tick       封装 get_full_tick
    _bid_ask_from_dict   快照 dict 取买一卖一
    _ts_from_millis_or_now  行情时间转 datetime
"""
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from xtquant import xtdata  # type: ignore

from source.data.qmt_fetcher import fetch_data
from .base import DataGateway
from ...core.models import TickerData
from ...enums import GatewayMode, Interval


class QmtDataGateway(DataGateway):
    """poll 定时拉全快照，push 订分笔推送；xt 标的代码，Tick 含最新价及可选买卖盘。"""

    def __init__(self,
                 interval: float = 3.0,
                 dividend_type: str = "none",
                 mode: GatewayMode = GatewayMode.POLL,
                 **kwargs: Any) -> None:
        """轮询间隔秒、K 线除权类型、模式 poll 或 push。"""
        super().__init__(**kwargs)

        # --- 配置参数 ---
        # 轮询间隔（秒），仅 poll 模式使用
        self.interval = interval
        # K 线除权类型（none / 前复权等）
        self.dividend_type = dividend_type
        # 行情模式：poll 定时拉全快照，push 订分笔
        self.mode: GatewayMode = mode

        # --- 订阅状态 ---
        # 已订阅标的列表
        self._tickers: List[str] = []

        # --- 运行时状态 ---
        # 轮询/推送线程运行标志
        self._running = False
        # 后台 daemon 线程
        self._thread: Optional[threading.Thread] = None
        # push 模式下各标的订阅序号，退订时使用
        self._ticker_sub_seqs: List[int] = []

    def connect(self) -> bool:
        """加载 xtdata，本机需已启动 miniQMT。"""
        try:
            # xtdata 已在顶层导入，此处仅保留 try-catch 用于统一错误处理
            return True
        except Exception as e:
            self.logger.error(f"miniQMT 连接失败: {e}")
            return False

    def subscribe(self, tickers: List[str]) -> bool:
        """追加订阅；新标的用近一日 1m K 线逐根暖机回调。"""
        new_tickers = [s for s in tickers if s not in self._tickers]
        for ticker in new_tickers:
            self._tickers.append(ticker)
            self._warm_up(ticker)
        return True

    def start(self) -> None:
        """起后台线程：poll 轮询快照，push 订分笔并跑 xtdata.run。"""
        if self._running:
            return
        if self.mode == GatewayMode.POLL:
            self._thread = threading.Thread(target=self._run_poll, daemon=True)
        else:
            self._thread = threading.Thread(target=self._run_push, daemon=True)
        self._thread.start()
        self._running = True

    def stop(self) -> None:
        """停线程；push 会退订并调 stop（若有）；join 等线程结束。"""
        self._running = False
        if self.mode == GatewayMode.PUSH:
            self._unsubscribe_push()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._thread = None

    def get_today_ohlc(self, ticker: str) -> Optional[Dict[str, float]]:
        """从快照取当日开、高、低三个 float；缺或错返回 None。"""
        tick, err = self._get_full_tick(ticker)
        if err or not tick:
            self.logger.warning(f"get_today_ohlc: {err}")
            return None
        try:
            o = tick.get("open")
            h = tick.get("high") or tick.get("highPrice")
            l_ = tick.get("low") or tick.get("lowPrice")
            if o is None or h is None or l_ is None:
                return None
            return {"open": float(o), "high": float(h), "low": float(l_)}
        except Exception as e:
            self.logger.error(f"get_today_ohlc 解析错误: {e}")
            return None

    def get_depths(self, ticker: str, levels: int = 5) -> Dict[str, List[Dict[str, float]]]:
        """返回买卖盘口深度（价格+委托量）。"""
        tick, err = self._get_full_tick(ticker)
        if err or not tick:
            self.logger.debug(f"get_depths {ticker}: {err}")
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

    # ---------- 私有 ----------

    def _warm_up(self, ticker: str) -> None:
        """近一日 1m 收盘合成暖机 tick。 TODO 这个warmup现在没意义，看下后面怎么改"""
        try:
            end = datetime.now()
            start = end - timedelta(days=1)
            datas = fetch_data(ticker, start.strftime("%Y-%m-%d"), None, interval=Interval.MINUTE_1,
                               dividend_type=self.dividend_type)
            if datas.empty:
                self.logger.warning(f"{ticker} 暖机数据为空")
                return
            for timestamp, data in datas.iterrows():
                ts = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp
                if getattr(ts, "tzinfo", None) is not None:
                    ts = ts.replace(tzinfo=None)
                price = float(data["Close"])
                volume = int(data["Volume"])
                ticker_data = TickerData(ticker=ticker, timestamp=ts, price=price, open=float(data["Open"]),
                                         high=float(data["High"]), low=float(data["Low"]), volume=volume,
                                         is_warm_up=True)
                if self._push:
                    self._push(ticker_data)
        except Exception as e:
            self.logger.warning(f"{ticker} 暖机失败: {e}")

    def _unsubscribe_push(self) -> None:
        """push 停时逐个退订 quote，再调 xtdata.stop（有则调）。"""
        if not self._ticker_sub_seqs:
            return
        try:
            for seq in self._ticker_sub_seqs:
                try:
                    xtdata.unsubscribe_quote(seq)
                except Exception as e:
                    self.logger.warning(f"unsubscribe_quote {seq} 失败: {e}")
            self._ticker_sub_seqs.clear()
            stop_fn = getattr(xtdata, "stop", None)
            if callable(stop_fn):
                stop_fn()
        except Exception as e:
            self.logger.warning(f"push 清理失败: {e}")

    def _run_poll(self) -> None:
        """对每个标的拉全快照，组 TickerData，调 tick 回调。"""
        while self._running:
            for ticker in self._tickers:
                tick, err = self._get_full_tick(ticker)
                if err or not tick:
                    self.logger.debug(f"跳过 tick {ticker}: {err}")
                    continue
                try:
                    last = tick.get("lastPrice") or tick.get("last") or tick.get("price")
                    vol = tick.get("volume") or tick.get("lastVolume") or 0
                    if last is None:
                        continue
                    ts = self._ts_from_millis_or_now(tick.get("time"))
                    bid, ask = self._bid_ask_from_dict(tick)
                    ticker_data = TickerData(ticker=ticker, timestamp=ts, price=float(last),
                                             open=float(tick["open"]) if tick.get("open") is not None else None,
                                             high=float(tick.get("high") or tick.get("highPrice") or 0) or None,
                                             low=float(tick.get("low") or tick.get("lowPrice") or 0) or None,
                                             volume=int(vol) if vol is not None else None, bid=bid, ask=ask)
                    if self._push:
                        self._push(ticker_data)
                except Exception as e:
                    self.logger.error(f"轮询 {ticker} 出错: {e}")
            time.sleep(self.interval)

    def _run_push(self) -> None:
        """逐只 subscribe_quote，最后阻塞 xd.run。"""
        # 防御性检查：线程启动时已被 stop
        if not self._running:
            return

        # 逐个标的订阅分笔行情
        self._ticker_sub_seqs = []
        for ticker in list(self._tickers):
            seq = xtdata.subscribe_quote(ticker, period="tick", start_time="", end_time="", count=0,
                                         callback=self._on_push_datas)
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

    def _on_push_datas(self, datas: dict) -> None:
        """分笔推送回调：行转 TickerData 再交 tick 回调。"""
        if not self._running:
            return
        # datas 结构：{标的代码: [分笔行, ...]}
        for code, rows in (datas or {}).items():
            for row in rows or []:
                # 跳过格式异常的推送数据
                if not isinstance(row, dict):
                    continue
                # 兼容多种字段名
                price = row.get("lastPrice") or row.get("last_price") or row.get("price")
                if price is None:
                    continue
                vol = row.get("volume") or row.get("lastVolume")
                ts = self._ts_from_millis_or_now(row.get("time"))
                bid, ask = self._bid_ask_from_dict(row)
                ticker_data = TickerData(ticker=code, price=float(price), timestamp=ts,
                                         volume=int(vol) if vol is not None else None, bid=bid, ask=ask)
                if self._push:
                    self._push(ticker_data)

    def _get_full_tick(self, ticker: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """调 get_full_tick；成功返回快照和 None，失败返回 None 和错误说明。"""
        try:
            data = xtdata.get_full_tick([ticker])
            if not data or ticker not in data:
                return None, f"{ticker} 无快照"
            return data[ticker], None
        except Exception as e:
            return None, str(e)

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
