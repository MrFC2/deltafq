"""
回测引擎。
"""

import pandas as pd
from typing import Dict, Any, Optional, List
from ..core.base import BaseComponent
from ..data import DataFetcher, DataStorage
from ..strategy.base import BaseStrategy
from ..trader.engine import TraderEngine
from ..enums import OrderType
from .performance import PerformanceReporter
from ..charts.performance import PerformanceChart
from abc import ABC


class BacktestEngine(BaseComponent, ABC):
    """回测引擎。"""

    def __init__(self, ticker: str, strategy: BaseStrategy, start_date: str,
                 end_date: Optional[str] = None, benchmark: Optional[str] = None,
                 initial_capital: float = 1000000, commission: float = 0.001,
                 data_source: str = "baostock", **kwargs):
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
        # 行情数据源（yahoo / baostock / miniqmt）
        self.data_source = data_source
        # 行情拉取器
        self.data_fetcher = DataFetcher(source=self.data_source)
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
        data = self._load_data()
        # 运行策略，生成信号
        signals, price_series = self._run_strategy(data)
        # 逐 bar 回放
        trades_df, values_df = self._run_backtest(signals, price_series)
        # 计算绩效指标、打印报告、展示图表
        self._report(trades_df, values_df)
        # 保存结果
        if save_results:
            self.save_backtest_results(trades_df, values_df)

    def _load_data(self) -> pd.DataFrame:
        """加载行情数据。"""
        if not self.ticker or not self.start_date:
            raise ValueError("ticker 和 start_date 不能为空。")
        return self.data_fetcher.fetch_data(self.ticker, self.start_date, self.end_date)

    def _run_strategy(self, data: pd.DataFrame):
        """运行策略，返回信号序列和收盘价序列。"""
        if data is None or data.empty:
            raise ValueError("行情数据为空，请先调用 _load_data()。")
        if 'Close' not in data.columns:
            raise ValueError("行情数据缺少 Close 列。")
        signals = self.strategy.run(data)
        return signals, data['Close']

    def _run_backtest(self, signals: pd.Series, price_series: pd.Series) -> tuple:
        """逐 bar 回放，返回 trades_df 和 values_df。"""
        if signals is None or signals.empty:
            raise ValueError("信号序列为空，请检查策略。")
        if price_series is None or price_series.empty:
            raise ValueError("价格序列为空。")

        try:
            # 合并信号与价格
            df_sig = pd.DataFrame({'Signal': signals, 'Close': price_series})
            values_records: List[Dict[str, Any]] = []

            for i, (date, row) in enumerate(df_sig.iterrows()):
                signal = row['Signal']
                price = row['Close']

                if signal == 1:
                    # 全仓买入：按手（100股）计算最大可买数量
                    max_qty = int(self.trader.cash / (price * (1 + self.trader.commission))) // 100 * 100
                    if max_qty > 0:
                        self.trader.execute_order(
                            ticker=self.ticker,
                            quantity=max_qty,
                            order_type=OrderType.LIMIT,
                            price=price,
                            timestamp=date
                        )

                elif signal == -1:
                    # 清仓卖出：卖出全部持仓
                    current_qty = self.trader.position_manager.get_position(self.ticker)
                    if current_qty > 0:
                        self.trader.execute_order(
                            ticker=self.ticker,
                            quantity=-current_qty,
                            order_type=OrderType.LIMIT,
                            price=price,
                            timestamp=date
                        )

                # 记录当日资产快照
                position_qty = self.trader.position_manager.get_position(self.ticker)
                position_value = position_qty * price
                total_value = position_value + self.trader.cash
                daily_pnl = 0.0 if i == 0 else total_value - values_records[-1]['total_value']

                values_records.append({
                    'date': date,
                    'signal': signal,
                    'price': price,
                    'cash': self.trader.cash,
                    'position': position_qty,
                    'position_value': position_value,
                    'total_value': total_value,
                    'daily_pnl': daily_pnl,
                })

            # 汇总成交记录和净值表
            trades_df = pd.DataFrame(self.trader.trades)
            values_df = pd.DataFrame(values_records)
            return trades_df, values_df

        except Exception as e:
            self.logger.error(f"_run_backtest 执行失败: {e}")
            raise RuntimeError(f"回测执行失败: {e}") from e

    def _report(self, trades_df: pd.DataFrame, values_df: pd.DataFrame) -> None:
        """计算绩效指标、打印报告、展示图表。"""
        if trades_df is None or values_df is None:
            raise ValueError("trades_df 或 values_df 为空，请先执行回测。")
        # 计算绩效指标并打印报告
        self.reporter.print_summary(ticker=self.ticker, trades_df=trades_df, values_df=values_df)
        # 展示图表
        benchmark_close = None
        if self.benchmark is not None:
            benchmark_close = \
                self.data_fetcher.fetch_data(self.benchmark, self.start_date, self.end_date)['Close']
        self.chart.plot_backtest_charts(values_df=values_df, benchmark_close=benchmark_close)

    def save_backtest_results(self, trades_df: pd.DataFrame, values_df: pd.DataFrame) -> None:
        """将回测结果保存为 CSV 文件。"""
        self.storage.save_backtest_results(trades_df=trades_df, values_df=values_df, ticker=self.ticker,
                                            strategy_name=self.strategy.name if self.strategy is not None else None)
