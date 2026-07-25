"""
回测引擎。
"""

import pandas as pd
from typing import Dict, Any, Optional, Tuple, List
from ..core.base import BaseComponent
from ..data import DataFetcher, DataStorage
from ..strategy.base import BaseStrategy
from ..trader.engine import ExecutionEngine
from .performance import PerformanceReporter
from ..charts.performance import PerformanceChart
from abc import ABC


class BacktestEngine(BaseComponent, ABC):
    """回测引擎。"""

    def __init__(self, ticker: str, start_date: str, end_date: Optional[str] = None,
                 benchmark: Optional[str] = None, initial_capital: float = 1000000,
                 commission: float = 0.001, data_source: str = "baostock", **kwargs):
        """初始化回测引擎。"""
        super().__init__(**kwargs)
        self.logger.info("初始化回测引擎")
        # 回测标的代码
        self.ticker = ticker
        # 回测起始日期
        self.start_date = start_date
        # 回测结束日期
        self.end_date = end_date
        # 基准标的代码，用于图表对比
        self.benchmark = benchmark
        # 初始资金
        self.initial_capital = initial_capital
        # 每笔交易手续费率
        self.commission = commission
        # 行情数据源（yahoo / baostock / miniqmt）
        self.data_source = data_source
        # 行情拉取器
        self.data_fetcher = DataFetcher(source=self.data_source)
        # 本地数据存储
        self.storage = DataStorage()
        # 绩效报告生成器
        self.reporter = PerformanceReporter()
        # 绩效图表渲染器
        self.chart = PerformanceChart()
        # 订单执行与持仓管理引擎
        self.execution = ExecutionEngine(broker=None, initial_capital=self.initial_capital, commission=self.commission)
        # 原始行情 DataFrame
        self.data = None
        # 当前策略实例
        self.strategy = None
        # 策略信号序列 {-1, 0, 1}
        self.signals = None
        # 收盘价序列，供回测逐 bar 使用
        self.price_series = None
        # 成交记录
        self.trades_df = pd.DataFrame()
        # 逐日净值快照
        self.values_df = pd.DataFrame()
        # 附加了 returns/cumulative_returns/drawdown 列的净值表
        self.values_metrics = pd.DataFrame()
        # 回测绩效指标字典
        self.metrics: Dict[str, Any] = {}

    def load_data(self) -> pd.DataFrame:
        """通过数据获取器加载行情数据。"""
        self.data = self.data_fetcher.fetch_data(self.ticker, self.start_date, self.end_date)
        return self.data

    def add_strategy(self, strategy: BaseStrategy) -> None:
        """添加策略并运行，生成信号序列。"""
        self.strategy = strategy
        self.strategy.run(self.data)
        self.signals = self.strategy.signals
        self.price_series = self.data['Close']

    def run_backtest(self, signals: Optional[pd.Series] = None,
                     price_series: Optional[pd.Series] = None,
                     save_csv: bool = False) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """逐 bar 回放，返回 trades_df 和 values_df。"""
        if signals is None and self.signals is None:
            raise ValueError("请先调用 add_strategy() 设置策略。")

        try:
            ticker = self.ticker
            signals = signals if signals is not None else self.signals
            price_series = price_series if price_series is not None else self.price_series

            df_sig = pd.DataFrame({'Signal': signals, 'Close': price_series})
            values_records: List[Dict[str, Any]] = []

            for i, (date, row) in enumerate(df_sig.iterrows()):
                signal = row['Signal']
                price = row['Close']

                if signal == 1:
                    max_qty = int(self.execution.cash / (price * (1 + self.commission)))
                    if max_qty > 0:
                        self.execution.execute_order(
                            symbol=ticker,
                            quantity=max_qty,
                            order_type="limit",
                            price=price,
                            timestamp=date
                        )

                elif signal == -1:
                    current_qty = self.execution.position_manager.get_position(ticker)
                    if current_qty > 0:
                        self.execution.execute_order(
                            symbol=ticker,
                            quantity=-current_qty,
                            order_type="limit",
                            price=price,
                            timestamp=date
                        )

                position_qty = self.execution.position_manager.get_position(ticker)
                position_value = position_qty * price
                total_value = position_value + self.execution.cash
                daily_pnl = 0.0 if i == 0 else total_value - values_records[-1]['total_value']

                values_records.append({
                    'date': date,
                    'signal': signal,
                    'price': price,
                    'cash': self.execution.cash,
                    'position': position_qty,
                    'position_value': position_value,
                    'total_value': total_value,
                    'daily_pnl': daily_pnl,
                })

            self.trades_df = pd.DataFrame(self.execution.trades)
            self.values_df = pd.DataFrame(values_records)

            if save_csv:
                self.save_backtest_results()

            return self.trades_df, self.values_df

        except Exception as e:
            self.logger.error(f"run_backtest 执行失败: {e}")
            raise RuntimeError(f"回测执行失败: {e}") from e

    def calculate_metrics(self) -> Tuple[pd.DataFrame, Dict[str, float]]:
        """计算回测指标，包括收益率、最大回撤、夏普比率等。"""
        self.values_metrics, self.metrics = self.reporter.compute(self.ticker, self.trades_df, self.values_df)
        return self.values_metrics, self.metrics

    def show_report(self) -> None:
        """打印回测汇总报告。"""
        self.reporter.print_summary(symbol=self.ticker, trades_df=self.trades_df, values_df=self.values_df)

    def show_chart(self, use_plotly: bool = True) -> None:
        """展示回测绩效图表。"""
        if self.benchmark is not None:
            benchmark_data = self.data_fetcher.fetch_data(self.benchmark, self.start_date, self.end_date)
            self.chart.plot_backtest_charts(values_df=self.values_df, benchmark_close=benchmark_data['Close'],
                                            use_plotly=use_plotly)
        else:
            self.chart.plot_backtest_charts(values_df=self.values_df, use_plotly=use_plotly)

    def save_backtest_results(self) -> None:
        """将回测结果保存为 CSV 文件。"""
        self.storage.save_backtest_results(trades_df=self.trades_df, values_df=self.values_df, symbol=self.ticker,
                                           strategy_name=self.strategy.name if self.strategy is not None else None)
