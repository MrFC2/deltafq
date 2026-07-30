"""
实盘引擎：在实时 Tick 上运行策略，并通过数据/交易网关拉行情、下单。

典型用法::
    engine = LiveEngine(
        ticker="BTC-USD",
        data_gateway=YFinanceDataGateway(),
        trade_gateway=PaperTradeGateway(initial_capital=100000),
        strategy=MyStrategy(),
        strategy_interval=Interval.MINUTE_1,
        strategy_input_size=50,
    )
    engine.run_live()
    # KeyboardInterrupt 时: engine.stop()

函数与方法索引（按模块）
------------------------
模块级
    _vol_str              将成交量格式化为 B/M/K 或整数字符串

LiveEngine — 运行
    __init__              构造：ticker、网关实例、策略实例、数据点数、信号周期、DataFetcher
    run_live              连接网关、注册 Tick 处理、订阅标的并启动数据流
    stop                  停止数据网关与交易网关

LiveEngine — 对外查询与绩效
    get_chart_data        返回缓存 K 线与信号列表（不落库、不重算）
    get_trades_df         从交易网关的执行引擎取成交明细 DataFrame
    get_values_df         净值记录（去重按日期取最后一条）
    calculate_metrics     基于成交与净值计算绩效指标（与回测接口一致）

LiveEngine — 内部：数据与网关
    _create_data_fetcher  按网关类型推断数据源并创建 DataFetcher
    _fetch_data           按 strategy_interval 拉取最近 strategy_input_size 根 K 线

LiveEngine — 内部：账户与挂单
    _account_snapshot     当前现金、持仓股数、佣金率（纸面引擎或 miniQMT 查询）
    _pending_order_no_cancel_needed  判断挂单是否已终态，可跳过撤单

LiveEngine — 内部：Tick
    _on_tick_match              将 Tick 交给纸面撮合引擎（若有）；打印非 warmup 的 Tick 日志
    _on_tick_strategy           编排：建 df → 信号 → 快照 → 净值 → sizing 日志 → 翻转处理
    _build_strategy_input       由 tick 与缓存构造策略输入 DataFrame（K 线或 tick 滑动窗口）
    _append_values_record       追加一条净值记录（与回测 values 形状一致）
    _size_and_log_action        按信号与策略 order_* 计算买卖数量并打一行 Signal 日志
    _handle_signal_transition   信号相对上次变化时：撤挂单、下限价、更新 _last_signal
"""

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict, List, NamedTuple, Tuple

import pandas as pd

from ..backtest.performance import PerformanceReporter
from ..core.base import BaseComponent
from ..data import DataFetcher, YahooDataFetcher, BaostockDataFetcher, MiniQmtDataFetcher
from ..strategy.base import BaseStrategy
from .event_engine import EventEngine
from ..adapters.data.base import DataGateway
from ..adapters.trade.base import TradeGateway
from ..adapters.trade.paper_gateway import PaperTradeGateway
from ..core.models import OrderRequest, SignalData, TickerData
from ..enums import OrderType, EventType, Interval, Signal
from ..adapters.data.yfinance_gateway import YFinanceDataGateway
from ..adapters.data.miniqmt_gateway import MiniQmtDataGateway

# 各周期下「多久重拉一次 K 线」（秒）
_REFETCH_INTERVAL = {
    Interval.MINUTE_1: 60, Interval.MINUTE_5: 300, Interval.MINUTE_15: 900,
    Interval.HOUR_1: 3600, Interval.DAY_1: 86400,
}
# 按信号周期估算「每根 K 线对应多少日历日」，用于拉足 lookback（1d≈252 交易日/365 日）
_FETCH_DAYS_PER_BAR = {Interval.DAY_1: 365 / 252, Interval.WEEK_1: 365 / 52, Interval.MONTH_1: 365 / 12}
_SIG_ICON = {1: "↑", -1: "↓", 0: "-"}
_ACTION_ICON = {"buy": "↑", "sell": "↓", "skip": "x", "no_change": "-"}


class _SizingLogResult(NamedTuple):
    """单次 tick 上用于日志与发单的买卖数量（买用 qty，卖用 sell_order_qty）。"""

    action_key: str
    action: str
    qty: int
    sell_order_qty: int


def _vol_str(v: float) -> str:
    """成交量友好显示：≥1e9 为 B，≥1e6 为 M，≥1e3 为 K，否则整数。"""
    if v >= 1e9:
        return f"{v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.1f}K"
    return str(int(v))


class LiveEngine(BaseComponent):
    """
    在实盘数据上跑策略并通过网关下单。

    策略可选属性：``order_quantity``（股）买卖均封顶；未设时 ``order_amount`` 仅限制买入，
    卖出用满仓。二者皆无时买入用可承受现金。有纸面引擎时资金/持仓来自引擎，否则 miniQMT 查询。
    同时设置时买入侧 ``order_quantity`` 优先于 ``order_amount``。
    """

    def __init__(
            self,
            ticker: str,
            data_gateway: DataGateway,
            trade_gateway: TradeGateway,
            strategy: BaseStrategy,
            strategy_input_size: int = 100,
            strategy_interval: Interval = Interval.MINUTE_5,
            **kwargs,
    ):
        super().__init__(**kwargs)

        # --- 配置参数 ---
        # 交易标的代码
        self.ticker: str = ticker
        # 策略所需数据点数（K 线根数或 tick 数）
        self.strategy_input_size: int = strategy_input_size
        # K 线周期（Interval.REALTIME 时不拉 K 线）
        self.strategy_interval: Interval = strategy_interval

        # --- 核心组件 ---
        # 行情网关
        self.data_gateway: DataGateway = data_gateway
        # 交易网关
        self.trade_gateway: TradeGateway = trade_gateway
        # 信号策略
        self._strategy: BaseStrategy = strategy
        # 事件总线，驱动 tick 分发
        self._event_engine: EventEngine = EventEngine()
        # K 线拉取器（tick 模式下为 None）
        self._data_fetcher: Optional[DataFetcher] = self._create_data_fetcher()

        # --- 运行时状态 ---
        # 上次信号值，用于检测翻转
        self._last_signal: int = 0
        # 当前未成交挂单的委托号
        self._last_pending_order_id: Optional[str] = None
        # 缓存最近一次策略输入（List[TickerData]），供 get_chart_data 使用
        self._cached_strategy_input: Optional[List[TickerData]] = None
        # 最近一次策略产生的信号序列
        self._cached_signals: Optional[List[SignalData]] = None
        # K 线/REALTIME 模式下的 tick 滑动窗口
        self._tick_datas: deque = deque(maxlen=strategy_input_size)

        # --- 统计记录 ---
        # 净值记录列表
        self._values_records: List[Dict[str, Any]] = []

    # ---------- 运行 ----------

    def run_live(self) -> None:
        """连接网关、注册 Tick、订阅标的并启动推送。"""
        if not self.data_gateway.connect() or not self.trade_gateway.connect():
            raise RuntimeError("网关连接失败")
        # 注册 tick 处理：撮合 + 策略信号
        self._event_engine.register(EventType.TICK, self._on_tick_match)
        self._event_engine.register(EventType.TICK, self._on_tick_strategy)
        # 将网关推送的 tick 接入事件总线
        self.data_gateway.set_on_tick(lambda ticker_data: self._event_engine.trigger(EventType.TICK, ticker_data))
        # 订阅标的并启动行情流
        self.data_gateway.subscribe([self.ticker])
        self.data_gateway.start()

    def stop(self) -> None:
        """停止数据流与交易网关。"""
        if self.data_gateway:
            self.data_gateway.stop()
        if self.trade_gateway:
            self.trade_gateway.stop()

    # ---------- 对外查询与绩效 ----------

    def get_chart_data(self) -> Dict[str, Any]:
        """
        返回缓存 K 线与信号（不重拉、不重算）。尚无缓存时 candles/signals 为空列表。

        返回:
            candles: [{date, open, high, low, close}, ...]；signals: [int, ...]
        """
        if not self._cached_strategy_input or not self._cached_signals:
            return {"candles": [], "signals": []}

        date_fmt = "%Y-%m-%d" if self.strategy_interval == Interval.DAY_1 else "%Y-%m-%d %H:%M:%S"

        candles: List[Dict[str, Any]] = []
        for t in self._cached_strategy_input:
            c = t.price
            o = t.open if t.open is not None else c
            h = t.high if t.high is not None else c
            l_ = t.low if t.low is not None else c
            candles.append({"date": t.timestamp.strftime(date_fmt), "open": o, "high": h, "low": l_, "close": c})

        sig_map = {s.timestamp: s.signal.value for s in self._cached_signals}
        signals = [sig_map.get(t.timestamp, Signal.HOLD.value) for t in self._cached_strategy_input]

        return {"candles": candles, "signals": signals}

    def get_trades_df(self) -> pd.DataFrame:
        """从纸面交易网关取成交列表（结构与回测一致）；实盘网关返回空 DataFrame。"""
        if not isinstance(self.trade_gateway, PaperTradeGateway):
            return pd.DataFrame()
        return pd.DataFrame(self.trade_gateway.get_trades())

    def get_values_df(self) -> pd.DataFrame:
        """权益曲线 DataFrame；按 date 去重保留最后一条。"""
        if not self._values_records:
            return pd.DataFrame()
        df = pd.DataFrame(self._values_records)
        if "date" not in df.columns:
            return df
        df = df.drop_duplicates(subset=["date"], keep="last")
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def calculate_metrics(self) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """由成交与权益计算绩效；接口同 BacktestEngine.calculate_metrics；可在 run 中或结束后调用。"""
        trades_df = self.get_trades_df()
        values_df = self.get_values_df()
        if values_df.empty:
            return pd.DataFrame(), {}
        reporter = PerformanceReporter()
        return reporter.compute(self.ticker, trades_df, values_df)

    # ---------- 内部：数据与网关 ----------

    def _create_data_fetcher(self) -> Optional[DataFetcher]:
        """非 tick 模式时按网关类型创建对应 DataFetcher，tick 模式返回 None。"""
        if self.strategy_interval == Interval.REALTIME:
            return None
        if isinstance(self.data_gateway, YFinanceDataGateway):
            return YahooDataFetcher()
        if isinstance(self.data_gateway, MiniQmtDataGateway):
            return MiniQmtDataFetcher()
        return BaostockDataFetcher()

    def _fetch_data(self) -> Optional[List[TickerData]]:
        """用 DataFetcher 拉当前 strategy_interval 下最近 strategy_input_size 根 K 线。"""
        # REALTIME 模式不拉 K 线，数据由 tick 实时积累
        if self._data_fetcher is None or self.strategy_interval == Interval.REALTIME:
            return None
        now = datetime.now(timezone.utc)
        days_per_bar = _FETCH_DAYS_PER_BAR.get(self.strategy_interval)
        if days_per_bar is not None:
            # 日/周/月线：按每根 bar 对应日历天数估算拉取范围，多留 60 天缓冲
            cal_days = int(self.strategy_input_size * days_per_bar) + 60
            start = (now - timedelta(days=max(cal_days, 60))).strftime("%Y-%m-%d")
        else:
            # 分钟/小时线：按 strategy_input_size 估算天数，最少 7 天、最多 60 天
            start = (now - timedelta(days=max(7, min(60, self.strategy_input_size // 10)))).strftime("%Y-%m-%d")
        end = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            data = self._data_fetcher.fetch_data(self.ticker, start, end, self.strategy_interval)
        except Exception as e:
            self.logger.warning(f"DataFetcher 拉取失败: {e}")
            return None
        if not data:
            return None

        # 只取策略需要的 n 条数据
        n = min(len(data), self.strategy_input_size)
        return data[-n:]

    # ---------- 内部：账户与挂单 ----------

    def _account_snapshot(self) -> Tuple[float, int, float]:
        """返回 (现金, 持仓股数, 佣金率)，委托给网关实现。"""
        gw = self.trade_gateway
        return gw.get_cash(), gw.get_position(self.ticker), gw.get_commission()

    def _pending_order_no_cancel_needed(self, order_id: str) -> bool:
        """若上一笔委托已终结则返回 True，无需再撤单。"""
        return self.trade_gateway.is_order_terminal(order_id)

    # ---------- 内部：Tick ----------

    def _on_tick_match(self, ticker_data: TickerData) -> None:
        """非 warmup：打 Tick 日志；若网关带执行引擎则转发 on_tick 做限价撮合。"""
        if not ticker_data.is_warm_up:
            ts = ticker_data.timestamp.strftime("%H:%M:%S")
            v = ticker_data.volume
            ba = ""
            if ticker_data.bid is not None and ticker_data.ask is not None:
                ba = f" bid={ticker_data.bid:.4f} ask={ticker_data.ask:.4f}"
            elif ticker_data.bid is not None:
                ba = f" bid={ticker_data.bid:.4f}"
            elif ticker_data.ask is not None:
                ba = f" ask={ticker_data.ask:.4f}"
            self.logger.info(
                f"Tick: [{ticker_data.ticker}] {ticker_data.price:.4f}{ba} vol={v}({_vol_str(v)}) @ {ts}"
            )
        if isinstance(self.trade_gateway, PaperTradeGateway):
            self.trade_gateway.on_tick(ticker_data)

    def _on_tick_strategy(self, ticker_data: TickerData) -> None:
        """编排：建 df → 信号 → 账户快照 → 权益 → sizing 与日志 → 信号翻转时撤单/下单。"""
        # 暖机 tick 只用于喂价格撮合，不触发策略
        if ticker_data.is_warm_up:
            return
        # 非本标的或策略未挂载时跳过
        if ticker_data.ticker != self.ticker or self._strategy is None:
            return

        # 未到重拉间隔或数据不足时跳过本次信号计算
        if not self._append_tick_datas(ticker_data):
            return

        # 执行策略，生成信号
        try:
            signals = self._strategy.generate_signals(list(self._tick_datas))
            if not signals:
                return
        except Exception as e:
            self.logger.warning(f"策略信号执行失败: {e}")
            return

        # 缓存供 get_chart_data 使用
        self._cached_strategy_input = list(self._tick_datas)
        self._cached_signals = signals

        # 获取账户持仓信息
        cash, position, commission = self._account_snapshot()

        # 取最新一根 bar 的信号值
        signal = signals[-1].signal
        price = float(ticker_data.price)

        # 追加净值记录
        self._append_values_record(ticker_data, signal, price, cash, position)

        order_quantity = getattr(self._strategy, "order_quantity", None)
        order_amount = getattr(self._strategy, "order_amount", None)
        # 计算本次应买/卖数量并打 Signal 日志
        sizing = self._size_and_log_action(signal, price, cash, position, commission, self._last_signal, order_quantity,
                                           order_amount)

        # 信号相对上次发生变化时撤旧单、发新单
        self._handle_signal_transition(signal, price, position, sizing, ticker_data)

    def _append_tick_datas(self, ticker_data: TickerData) -> bool:
        """由当前 tick 更新 _tick_datas；未到重拉间隔时返回 False。"""
        if self.strategy_interval == Interval.REALTIME:
            self._tick_datas.append(ticker_data)
            return True

        # K 线模式：_tick_datas 最后一根的时间戳未超过重拉间隔时跳过
        refetch_interval = _REFETCH_INTERVAL.get(self.strategy_interval, 60)
        if self._tick_datas:
            interval = (datetime.now() - self._tick_datas[-1].timestamp).total_seconds()
            if interval < refetch_interval:
                return False

        data = self._fetch_data()
        if data is None:
            return False

        self._tick_datas.clear()
        for ticker_data in data:
            self._tick_datas.append(ticker_data)
        return True

    def _append_values_record(self, ticker_data: TickerData, signal: Signal, px: float, cash: float, position: int) -> None:
        """追加一条权益记录，供 get_values_df / calculate_metrics 使用。"""
        position_value = position * px
        total_value = cash + position_value
        prev_total = self._values_records[-1]["total_value"] if self._values_records else total_value
        daily_pnl = total_value - prev_total
        self._values_records.append({
            "date": ticker_data.timestamp,
            "signal": signal.value,
            "price": px,
            "cash": cash,
            "position": position,
            "position_value": position_value,
            "total_value": total_value,
            "daily_pnl": daily_pnl,
        })

    def _size_and_log_action(
            self,
            signal: int,
            px: float,
            cash: float,
            position: int,
            commission: float,
            last_signal: int,
            order_quantity: Optional[int],
            order_amount: Optional[float],
    ) -> _SizingLogResult:
        """按当前信号与上次信号计算买卖数量，并打一行 Signal 日志。"""
        action_key = "no_change"
        action = "no_change"
        qty = 0
        sell_order_qty = 0

        oq_cap: Optional[int] = None
        if order_quantity is not None and int(order_quantity) > 0:
            oq_cap = int(order_quantity)

        if signal == 1 and last_signal <= 0:
            max_qty = max(0, int(cash / (px * (1 + commission))))
            if oq_cap is not None:
                qty = min(oq_cap, max_qty)
            elif order_amount is not None and order_amount > 0:
                qty = min(max(0, int(order_amount / (px * (1 + commission)))), max_qty)
            else:
                qty = max_qty
            if qty > 0:
                action_key, action = "buy", f"BUY qty={qty}"
            else:
                action_key, action = "skip", "BUY skip (qty=0)"
        elif signal == -1 and last_signal >= 0:
            if position > 0:
                if oq_cap is not None:
                    sell_order_qty = min(position, oq_cap)
                else:
                    sell_order_qty = position
                action_key, action = "sell", f"SELL qty={sell_order_qty}"
            else:
                action_key, action = "skip", "SELL skip (position=0)"

        icon = _SIG_ICON.get(signal, "?")
        act_icon = _ACTION_ICON.get(action_key, "?")
        self.logger.info(
            f"Signal: {icon} {signal} [{self.ticker}] {px:.4f} cash={cash:.0f} pos={position} -> {act_icon} {action}"
        )
        return _SizingLogResult(action_key, action, qty, sell_order_qty)

    def _handle_signal_transition(
            self, signal: int, px: float, position: int, sizing: _SizingLogResult, ticker_data: TickerData
    ) -> None:
        """相对 _last_signal 发生变化时：尝试撤上一笔挂单，再按规则下限价单。"""
        last = self._last_signal
        if signal == last:
            return

        assert self.trade_gateway is not None

        if self._last_pending_order_id:
            oid = self._last_pending_order_id
            if self._pending_order_no_cancel_needed(oid):
                self.logger.info(f"挂单 {oid} 已完成，跳过撤单")
                self._last_pending_order_id = None
            else:
                cancelled = self.trade_gateway.cancel_order(oid)
                if cancelled:
                    self.logger.info(f"已撤销挂单: {oid}")
                else:
                    self.logger.warning(f"撤销挂单 {oid} 返回失败")
                self._last_pending_order_id = None

        if signal == 1 and last <= 0:
            if sizing.qty > 0:
                buy_px = float(ticker_data.ask) if ticker_data.ask is not None else px
                req = OrderRequest(ticker=self.ticker, quantity=sizing.qty, price=buy_px,
                                   order_type=OrderType.LIMIT)  # type: ignore[arg-type]
                self._last_pending_order_id = self.trade_gateway.send_order(req)
                self.logger.info(f"已发送买单: [{self.ticker}] qty={sizing.qty} @ {buy_px:.4f}")
        elif signal == -1 and last >= 0 and position > 0:
            if sizing.sell_order_qty <= 0:
                self._last_signal = signal
                return
            sell_px = float(ticker_data.bid) if ticker_data.bid is not None else px
            req = OrderRequest(
                ticker=self.ticker, quantity=-sizing.sell_order_qty, price=sell_px, order_type=OrderType.LIMIT
                # type: ignore[arg-type]
            )
            self._last_pending_order_id = self.trade_gateway.send_order(req)
            self.logger.info(f"已发送卖单: [{self.ticker}] qty={sizing.sell_order_qty} @ {sell_px:.4f}")

        self._last_signal = signal
