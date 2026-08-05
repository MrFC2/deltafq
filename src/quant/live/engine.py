"""
实盘引擎：在实时 Tick 上运行策略，并通过数据/交易网关拉行情、下单。

典型用法::
    engine = LiveEngine(
        ticker_strategies={
            "600519.SH": StrategyA(name="A_600519"),
            "002415.SZ": StrategyB(name="B_002415"),
        },
        data_gateway=QmtDataGateway(mode=GatewayMode.POLL),
        trade_gateway=PaperTradeGateway(initial_capital=1_000_000),
    )
    engine.run()
    # KeyboardInterrupt 时: engine.stop()

函数与方法索引（按模块）
------------------------
模块级
    TickerContext         单标的运行时状态容器（dataclass）

LiveEngine — 运行
    __init__              构造：ticker_strategies dict、网关实例
    run                   按 ticker 注册回调（携带 period）并启动数据流
    stop                  停止数据网关与交易网关

LiveEngine — 对外查询与绩效
    get_trades_df         从交易网关的执行引擎取成交明细 DataFrame

LiveEngine — 内部：数据与网关
    （已移至 DataGateway）

LiveEngine — 内部：账户与挂单
    （已内联至调用处）

LiveEngine — 内部：Tick
    _run_strategy               编排：撮合挂单 → 路由 ctx → 信号 → 快照 → 翻转处理
    _make_signal_to_order       信号相对上次变化时：撤挂单、下限价、更新 ctx.last_signal
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Dict

import pandas as pd
from ..core.base import BaseComponent
from ..strategy.base import BaseStrategy
from ..gateway.data.base import DataGateway
from ..gateway.trade.base import TradeGateway
from ..gateway.trade.paper_gateway import PaperTradeGateway
from ..core.models import SignalData, TickerData
from ..enums import Period, Signal


@dataclass
class TickerContext:
    """单标的运行时状态容器，随 LiveEngine 构造时按 ticker 初始化。"""
    # 绑定的策略实例（每个 ticker 独占，不共用）
    strategy: BaseStrategy
    # K线/Tick 滑动窗口，maxlen=strategy.data_size
    ticker_datas: Deque[TickerData]
    # 上次信号，用于检测翻转
    last_signal: Signal = Signal.HOLD
    # 当前未成交挂单委托号
    last_pending_order_id: Optional[str] = None


class LiveEngine(BaseComponent):
    """
    在实盘数据上跑策略并通过网关下单。

    策略可在 SignalData 中设置 ``order_quantity``（股）控制买卖双侧股数上限；未设置时买入用可承受现金全仓。
    有纸面引擎时资金/持仓来自引擎，否则 miniQMT 查询。
    """

    def __init__(self,
                 ticker_strategies: Dict[str, BaseStrategy],
                 data_gateway: DataGateway,
                 trade_gateway: TradeGateway,
                 **kwargs):
        super().__init__(**kwargs)

        # --- 核心组件 ---
        # 行情网关
        self.data_gateway: DataGateway = data_gateway
        # 交易网关
        self.trade_gateway: TradeGateway = trade_gateway

        # --- 统计记录 ---
        # 唯一的 per-ticker 状态容器，deque 大小由各策略的 data_size 决定
        self._ticker_contexts: Dict[str, TickerContext] = {
            ticker: TickerContext(strategy=strategy, ticker_datas=deque(maxlen=strategy.data_size))
            for ticker, strategy in ticker_strategies.items()
        }

    # ---------- 运行 ----------

    def run(self) -> None:
        """注册 Tick 回调并启动行情推送。"""
        for ticker, ctx in self._ticker_contexts.items():
            # 注册回调时携带 period，gateway 内部按 period 分组建线程
            self.data_gateway.register_ticker_callback(ticker, self._run_strategy, ctx.strategy.period)
            # 数据预热：仅 K 线模式需要，TICK 模式不需要历史窗口
            if ctx.strategy.period != Period.TICK:
                datas = self.data_gateway.get_kline_warm_up(ticker, ctx.strategy.period, ctx.strategy.data_size)
                ctx.ticker_datas.extend(datas)

        self.data_gateway.start()

    def stop(self) -> None:
        """停止数据流与交易网关。"""
        if self.data_gateway:
            self.data_gateway.stop()
        if self.trade_gateway:
            self.trade_gateway.stop()

    # ---------- 对外查询与绩效 ----------

    def get_trades_df(self) -> pd.DataFrame:
        """从纸面交易网关取成交列表（结构与回测一致）；实盘网关返回空 DataFrame。"""
        if not isinstance(self.trade_gateway, PaperTradeGateway):
            return pd.DataFrame()
        return pd.DataFrame(self.trade_gateway.get_trades())

    # ---------- 内部：Tick ----------

    def _run_strategy(self, ticker_data: TickerData) -> None:
        """编排：撮合挂单 → 建 df → 信号 → 账户快照 → 权益 → 信号翻转时撤单/下单。"""
        # 按 ticker 路由到对应 ctx，无对应标的时跳过
        ctx = self._ticker_contexts.get(ticker_data.ticker)
        if ctx is None:
            return

        # 幂等校验：时间戳未变说明是重复数据，跳过
        if ctx.ticker_datas and ctx.ticker_datas[-1].timestamp == ticker_data.timestamp:
            return

        # 模拟交易撮合成交（实盘交易依赖第三方平台不需要）
        if isinstance(self.trade_gateway, PaperTradeGateway):
            self.trade_gateway.match_pending_orders(ticker_data)

        ctx.ticker_datas.append(ticker_data)

        # 获取账户持仓信息（先于策略，以便策略计算 quantity）
        cash = self.trade_gateway.get_cash()
        position = self.trade_gateway.get_position(ticker_data.ticker)
        commission = self.trade_gateway.get_commission()

        # 执行策略，生成信号
        try:
            signals = ctx.strategy.generate_signals(list(ctx.ticker_datas), cash, position, commission)
            if not signals:
                return
        except Exception as e:
            self.logger.exception(f"[{ticker_data.ticker}] 策略执行失败: {e}")
            return

        # 取最新一根 bar 的信号
        latest_signal = signals[-1]

        # 根据信号生成买卖订单
        self._make_signal_to_order(ctx, latest_signal, position, ticker_data)

    def _make_signal_to_order(self,
                              ctx: TickerContext,
                              signal_data: SignalData,
                              position: int,
                              ticker_data: TickerData) -> None:
        """相对 last_signal 发生变化时：尝试撤上一笔挂单，再按规则下限价单。"""
        if self.trade_gateway is None:
            return

        # 信号未变，无需操作
        signal = signal_data.signal
        if signal == ctx.last_signal:
            return

        # 撤掉上一笔未成交的挂单，腾出仓位再挂新单
        if ctx.last_pending_order_id:
            oid = ctx.last_pending_order_id
            ctx.last_pending_order_id = None
            if not self.trade_gateway.is_order_terminal(oid):
                self.trade_gateway.cancel_order(oid)

        # 空仓/观望 → 买入：策略必须给出 quantity，否则不下单
        if signal == Signal.BUY:
            if signal_data.quantity:
                buy_price = float(ticker_data.ask) if ticker_data.ask is not None else ticker_data.price  # 优先用卖一价成交
                ctx.last_pending_order_id = self.trade_gateway.send_order(ticker_data.ticker, signal_data, buy_price)

        # 持仓 → 卖出：quantity 缺失则跳过下单但仍更新信号状态
        if signal == Signal.SELL and position > 0:
            if not signal_data.quantity:
                ctx.last_signal = signal
                return
            sell_price = float(ticker_data.bid) if ticker_data.bid is not None else ticker_data.price  # 优先用买一价成交
            ctx.last_pending_order_id = self.trade_gateway.send_order(ticker_data.ticker, signal_data, sell_price)

        # signal == HOLD：撤旧单后不下新单，等待下次信号
        ctx.last_signal = signal
