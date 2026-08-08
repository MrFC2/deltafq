"""
回测引擎。
"""

import pandas as pd
from typing import Dict, Any, Optional, List
from ..core.base import BaseComponent
from ..data import DataFetcher, DataStorage, BaostockDataFetcher
from ..strategy.base import BaseStrategy
from ..trader.engine import TraderEngine
from ..enums import OrderType, Signal, Period
from .performance import PerformanceReporter
from ..charts.performance import PerformanceChart
from ..core.models import SignalData, TickerData
from abc import ABC


class BacktestEngine(BaseComponent, ABC):
    """回测引擎。"""

    def __init__(self,
                 ticker: str,
                 strategy: BaseStrategy,
                 start_date: str,
                 end_date: Optional[str] = None,
                 benchmark: Optional[str] = None,
                 initial_capital: float = 1000000,
                 commission: float = 0.001,
                 data_fetcher: Optional[DataFetcher] = None,
                 **kwargs):
        """初始化回测引擎。"""
        super().__init__(**kwargs)
        # 回测标的代码
        self.ticker = ticker
        # 策略实例
        self.strategy = strategy
        # 回测起始日期
        self.start_date = start_date
        # 回测结束日期
        self.end_date = end_date
        # 基准标的代码，用于图表对比
        self.benchmark = benchmark
        # 行情拉取器（默认 baostock）
        self.data_fetcher: DataFetcher = data_fetcher or BaostockDataFetcher()
        # 订单执行与持仓管理引擎
        self.trader = TraderEngine(cash=initial_capital, commission=commission)
        # 绩效报告生成器
        self.reporter = PerformanceReporter()
        # 绩效图表渲染器
        self.chart = PerformanceChart()
        # 本地数据存储
        self.storage = DataStorage()

    def run(self, save_results: bool = False) -> None:
        """完整回测流程入口。"""
        # 加载行情数据
        data = self._fetch_data()
        # 运行策略，生成信号
        signals = self._run_strategy(data)
        # 逐 bar 回放
        trades_df, values_df = self._run_backtest(signals, data)
        # 计算绩效指标、打印报告、展示图表
        self._report(trades_df, values_df, data)
        # 保存结果
        if save_results:
            self.save_backtest_results(trades_df, values_df)

    def _fetch_data(self) -> List[TickerData]:
        """加载行情数据。"""
        if not self.ticker or not self.start_date:
            raise ValueError("ticker 和 start_date 不能为空。")
        return self.data_fetcher.fetch_data(self.ticker, Period.DAY_1, self.start_date, self.end_date)

    def _run_strategy(self, data: List[TickerData]) -> List[SignalData]:
        """运行策略，返回信号列表。"""
        if not data:
            raise ValueError("行情数据为空，请先调用 _load_data()。")
        return self.strategy.generate_signals(data)

    def _run_backtest(self, signals: List[SignalData], data: List[TickerData]) -> tuple:
        """逐 bar 回放，返回 trades_df 和 values_df。"""
        if not signals:
            raise ValueError("信号列表为空，请检查策略。")
        if not data:
            raise ValueError("价格序列为空。")

        try:
            values_records: List[Dict[str, Any]] = []

            for i, (ticker_data, sig_data) in enumerate(zip(data, signals)):
                signal = sig_data.signal
                price = ticker_data.price
                date = ticker_data.timestamp

                if signal == Signal.BUY:
                    # 全仓买入：按手（100股）计算最大可买数量
                    max_qty = int(self.trader.cash / (price * (1 + self.trader.commission))) // 100 * 100
                    if max_qty > 0:
                        self.trader.execute_order(self.ticker, Signal.BUY, max_qty, OrderType.LIMIT, price, date)

                elif signal == Signal.SELL:
                    # 清仓卖出：卖出全部持仓
                    current_qty = self.trader.position_manager.get_position(self.ticker)
                    if current_qty > 0:
                        self.trader.execute_order(self.ticker, Signal.SELL, current_qty, OrderType.LIMIT, price, date)

                # 记录当日资产快照
                position_qty = self.trader.position_manager.get_position(self.ticker)
                position_value = position_qty * price
                total_value = position_value + self.trader.cash
                daily_pnl = 0.0 if i == 0 else total_value - values_records[-1]['total_value']

                values_records.append({
                    'date': date,
                    'signal': signal.value,
                    'price': price,
                    'cash': self.trader.cash,
                    'position': position_qty,
                    'position_value': position_value,
                    'total_value': total_value,
                    'daily_pnl': daily_pnl,
                })

            # 汇总成交记录和净值表
            trades_df = pd.DataFrame(self.trader.trade_records)
            values_df = pd.DataFrame(values_records)
            return trades_df, values_df

        except Exception as e:
            self.logger.exception(f"_run_backtest 执行失败: {e}")
            raise RuntimeError(f"回测执行失败: {e}") from e

    def _report(self,
                trades_df: pd.DataFrame,
                values_df: pd.DataFrame,
                data: List[TickerData] = None) -> None:
        """计算绩效指标、打印报告、展示图表。"""
        if trades_df is None or values_df is None:
            raise ValueError("trades_df 或 values_df 为空，请先执行回测。")
        # 计算绩效指标
        _, metrics = self.reporter.compute(self.ticker, trades_df, values_df)
        # 展示图表（含指标表格）
        benchmark_close = None
        if self.benchmark is not None:
            benchmark_bars = self.data_fetcher.fetch_data(self.benchmark, Period.DAY_1, self.start_date, self.end_date)
            benchmark_close = pd.Series(
                [t.price for t in benchmark_bars],
                index=[t.timestamp for t in benchmark_bars],
            )
        ohlcv_df = self.to_ohlcv_df(data) if data else None
        self.chart.plot_backtest_charts(values_df=values_df, ohlcv_df=ohlcv_df, trades_df=trades_df, benchmark_close=benchmark_close, metrics=metrics)

    @staticmethod
    def to_ohlcv_df(bars: List[TickerData]) -> pd.DataFrame:
        """将 TickerData 列表转为标准 OHLCV DataFrame，供回测与图表使用。"""
        return pd.DataFrame(
            {
                "Open": [t.open for t in bars],
                "High": [t.high for t in bars],
                "Low": [t.low for t in bars],
                "Close": [t.price for t in bars],
                "Volume": [t.volume for t in bars],
            },
            index=[t.timestamp for t in bars],
        )

    def save_backtest_results(self, trades_df: pd.DataFrame, values_df: pd.DataFrame) -> None:
        """将回测结果保存为 CSV 文件。"""
        self.storage.save_backtest_results(trades_df=trades_df, values_df=values_df, ticker=self.ticker,
                                           strategy_name=self.strategy.name if self.strategy is not None else None)
