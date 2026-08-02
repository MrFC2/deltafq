"""
实盘引擎：在实时 Tick 上运行策略，并通过数据/交易网关拉行情、下单。

典型用法::
    engine = LiveEngine(
        ticker="600519.SH",
        data_gateway=BaostockDataGateway(),
        trade_gateway=PaperTradeGateway(initial_capital=100000),
        strategy=MyStrategy(),
        strategy_input_size=50,
    )
    engine.run_live()
    # KeyboardInterrupt 时: engine.stop()

函数与方法索引（按模块）
------------------------
模块级
    （无）

LiveEngine — 运行
    __init__              构造：ticker、网关实例、策略实例、数据点数、信号周期、DataFetcher
    run                   连接网关、注册 Tick 回调、订阅标的并启动数据流
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
    （已内联至调用处）

LiveEngine — 内部：Tick
    _on_tick_strategy           编排：撮合挂单 → 建 df → 信号 → 快照 → 净值 → 翻转处理
    _build_strategy_input       由 tick 与缓存构造策略输入 DataFrame（K 线或 tick 滑动窗口）
    _append_values_record       追加一条净值记录（与回测 values 形状一致）
    # _calc_order_quantity      按信号与策略 order_* 计算买卖数量（已移至策略层）
    _handle_signal_transition   信号相对上次变化时：撤挂单、下限价、更新 _last_signal
"""

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict, List, Tuple

import pandas as pd

from ..backtest.performance import PerformanceReporter
from ..core.base import BaseComponent
from ..data import DataFetcher, BaostockDataFetcher, QmtDataFetcher
from ..strategy.base import BaseStrategy
from ..adapters.data.base import DataGateway
from ..adapters.trade.base import TradeGateway
from ..adapters.trade.paper_gateway import PaperTradeGateway
from ..core.models import SignalData, TickerData
from ..enums import Period, Signal
from ..adapters.data.qmt_gateway import QmtDataGateway

_SIG_ICON = {1: "↑", -1: "↓", 0: "-"}
_ACTION_ICON = {"buy": "↑", "sell": "↓", "skip": "x", "no_change": "-"}


class LiveEngine(BaseComponent):
    """
    在实盘数据上跑策略并通过网关下单。

    策略可在 SignalData 中设置 ``order_quantity``（股）控制买卖双侧股数上限；未设置时买入用可承受现金全仓。
    有纸面引擎时资金/持仓来自引擎，否则 miniQMT 查询。
    """

    def __init__(self,
                 ticker: str,
                 data_gateway: DataGateway,
                 trade_gateway: TradeGateway,
                 strategy: BaseStrategy,
                 strategy_input_size: int = 100,
                 **kwargs):
        super().__init__(**kwargs)

        # --- 配置参数 ---
        # 交易标的代码
        self.ticker: str = ticker
        # 策略所需数据点数（K 线根数或 tick 数）
        self.strategy_input_size: int = strategy_input_size

        # --- 核心组件 ---
        # 行情网关
        self.data_gateway: DataGateway = data_gateway
        # 交易网关
        self.trade_gateway: TradeGateway = trade_gateway
        # 信号策略
        self._strategy: BaseStrategy = strategy
        # K 线拉取器（tick 模式下为 None）
        self._data_fetcher: Optional[DataFetcher] = self._create_data_fetcher()

        # --- 运行时状态 ---
        # 上次信号值，用于检测翻转
        self._last_signal: Signal = Signal.HOLD
        # 当前未成交挂单的委托号
        self._last_pending_order_id: Optional[str] = None
        # 缓存最近一次策略输入（List[TickerData]），供 get_chart_data 使用
        self._cached_strategy_input: Optional[List[TickerData]] = None
        # 最近一次策略产生的信号序列
        self._cached_signals: Optional[List[SignalData]] = None
        # K 线/TICK 模式下的 tick 滑动窗口
        self._ticker_datas: deque = deque(maxlen=strategy_input_size)

        # --- 统计记录 ---
        # 净值记录列表
        self._values_records: List[Dict[str, Any]] = []

    # ---------- 运行 ----------

    def run(self) -> None:
        """注册 Tick 回调并启动行情推送。"""
        self.data_gateway.register_ticker_callback(self.ticker, self._run_strategy)
        self.data_gateway.start(self._strategy.period)

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

        date_fmt = "%Y-%m-%d" if self._strategy.period == Period.DAY_1 else "%Y-%m-%d %H:%M:%S"

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
        if self._strategy.period == Period.TICK:
            return None
        if isinstance(self.data_gateway, QmtDataGateway):
            return QmtDataFetcher()
        return BaostockDataFetcher()

    def _fetch_data(self) -> Optional[List[TickerData]]:
        """用 DataFetcher 拉当前 strategy_interval 下最近 strategy_input_size 根 K 线。"""
        # TICK 模式不拉 K 线，数据由 tick 实时积累
        if self._data_fetcher is None:
            return None
        now = datetime.now(timezone.utc)
        if self._strategy.period.days_per_bar > 0:
            # 日/周/月线：按每根 bar 对应日历天数估算拉取范围，多留 60 天缓冲
            cal_days = int(self.strategy_input_size * self._strategy.period.days_per_bar) + 60
            start = (now - timedelta(days=max(cal_days, 60))).strftime("%Y-%m-%d")
        else:
            # 分钟/小时线：按 strategy_input_size 估算天数，最少 7 天、最多 60 天
            start = (now - timedelta(days=max(7, min(60, self.strategy_input_size // 10)))).strftime("%Y-%m-%d")
        end = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            data = self._data_fetcher.fetch_data(self.ticker, self._strategy.period, start, end)
        except Exception as e:
            self.logger.exception(f"DataFetcher 拉取失败: {e}")
            return None
        if not data:
            return None

        # 只取策略需要的 n 条数据
        n = min(len(data), self.strategy_input_size)
        return data[-n:]

    # ---------- 内部：账户与挂单 ----------

    # ---------- 内部：Tick ----------

    def _run_strategy(self, ticker_data: TickerData) -> None:
        """编排：撮合挂单 → 建 df → 信号 → 账户快照 → 权益 → 信号翻转时撤单/下单。"""
        # 模拟交易撮合成交（实盘交易依赖第三方平台不需要）
        if isinstance(self.trade_gateway, PaperTradeGateway):
            self.trade_gateway.on_tick(ticker_data)

        # 暖机 tick 只用于喂价格撮合，不触发策略
        if ticker_data.is_warm_up:
            return

        # 非本标的或策略未挂载时跳过
        if ticker_data.ticker != self.ticker or self._strategy is None:
            return

        # 未到重拉间隔或数据不足时跳过本次信号计算
        if not self._append_ticker_datas(ticker_data):
            return

        # 获取账户持仓信息（先于策略，以便策略计算 quantity）
        cash = self.trade_gateway.get_cash()
        position = self.trade_gateway.get_position(self.ticker)
        commission = self.trade_gateway.get_commission()

        # 执行策略，生成信号
        try:
            signals = self._strategy.generate_signals(list(self._ticker_datas), cash, position, commission)
            if not signals:
                return
        except Exception as e:
            self.logger.exception(f"策略信号执行失败: {e}")
            return

        # 缓存供 get_chart_data 使用
        self._cached_strategy_input = list(self._ticker_datas)
        self._cached_signals = signals

        # 取最新一根 bar 的信号
        latest_signal = signals[-1]

        # 根据信号生成买卖订单
        self._make_signal_to_order(latest_signal, position, ticker_data)

        # 追加净值记录 TODO 放在这里不太合理，而且用的价格也不太对，后续看下怎么调整
        self._append_values_record(ticker_data, latest_signal.signal, cash, position)

    def _append_ticker_datas(self, ticker_data: TickerData) -> bool:
        """由网关推来的 ticker_data 直接 append；网关层负责按 period 控制推送频率。"""
        self._ticker_datas.append(ticker_data)
        return True

        # 原版逻辑（网关层无 period 感知时在引擎层做时间窗口判断）：
        # if self._strategy.period == Period.TICK:
        #     self._ticker_datas.append(ticker_data)
        #     return True
        #
        # # K 线模式：_tick_datas 最后一根的时间戳未超过重拉间隔时跳过
        # if self._ticker_datas:
        #     period = (datetime.now() - self._ticker_datas[-1].timestamp).total_seconds()
        #     if period < self._strategy.period.refetch_seconds:
        #         return False
        #
        # datas = self._fetch_data()
        # if datas is None:
        #     return False
        #
        # self._ticker_datas.clear()
        # for data in datas:
        #     self._ticker_datas.append(data)
        # return True

    def _append_values_record(self,
                              ticker_data: TickerData,
                              signal: Signal,
                              cash: float,
                              position: int) -> None:
        """追加一条净值记录，供 get_values_df / calculate_metrics 使用。"""
        price = ticker_data.price
        position_value = position * price
        total_value = cash + position_value
        prev_total = self._values_records[-1]["total_value"] if self._values_records else total_value
        daily_pnl = total_value - prev_total
        self._values_records.append({
            "date": ticker_data.timestamp,
            "signal": signal.value,
            "price": price,
            "cash": cash,
            "position": position,
            "position_value": position_value,
            "total_value": total_value,
            "daily_pnl": daily_pnl,
        })

    # def _calc_order_quantity(self, signal_data: SignalData, price: float, cash: float, position: int,
    #                          commission: float) -> Tuple[int, int]:
    #     """按当前信号与上次信号计算本次应买卖的数量，返回 (buy_quantity, sell_quantity)。"""
    #     signal = signal_data.signal
    #     order_quantity = signal_data.quantity
    #     # 信号由非买转买
    #     if self._last_signal != Signal.BUY and signal == Signal.BUY:
    #         # 现金可承受的最大股数
    #         max_buy_quantity = max(0, int(cash / (price * (1 + commission))))
    #         if order_quantity and order_quantity > 0:
    #             # 股数上限优先
    #             return min(order_quantity, max_buy_quantity), 0
    #         # 无限制则全仓买入
    #         return max_buy_quantity, 0
    #
    #     # 信号由非卖转卖
    #     if self._last_signal != Signal.SELL and signal == Signal.SELL and position > 0:
    #         # 有股数上限则不超过持仓，否则清仓
    #         if order_quantity and order_quantity > 0:
    #             return 0, min(position, order_quantity)
    #         return 0, position
    #
    #     return 0, 0

    def _make_signal_to_order(self,
                              signal_data: SignalData,
                              position: int,
                              ticker_data: TickerData) -> None:
        """相对 _last_signal 发生变化时：尝试撤上一笔挂单，再按规则下限价单。"""
        if self.trade_gateway is None:
            return

        # 信号未变，无需操作
        signal = signal_data.signal
        if signal == self._last_signal:
            return

        # 撤掉上一笔未成交的挂单，腾出仓位再挂新单
        if self._last_pending_order_id:
            oid = self._last_pending_order_id
            self._last_pending_order_id = None
            if not self.trade_gateway.is_order_terminal(oid):
                self.trade_gateway.cancel_order(oid)

        # 空仓/观望 → 买入：策略必须给出 quantity，否则不下单
        if signal == Signal.BUY:
            if signal_data.quantity:
                buy_price = float(ticker_data.ask) if ticker_data.ask is not None else ticker_data.price  # 优先用卖一价成交
                self._last_pending_order_id = self.trade_gateway.send_order(self.ticker, signal_data, buy_price)

        # 持仓 → 卖出：quantity 缺失则跳过下单但仍更新信号状态
        if signal == Signal.SELL and position > 0:
            if not signal_data.quantity:
                self._last_signal = signal
                return
            sell_price = float(ticker_data.bid) if ticker_data.bid is not None else ticker_data.price  # 优先用买一价成交
            self._last_pending_order_id = self.trade_gateway.send_order(self.ticker, signal_data, sell_price)

        # signal == HOLD：撤旧单后不下新单，等待下次信号
        self._last_signal = signal
