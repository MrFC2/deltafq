"""Minimal example: compute metrics and show charts for a backtest."""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from deltafq.data import BaostockDataFetcher
from deltafq.indicators import TechnicalIndicators
from deltafq.strategy import SignalGenerator
from deltafq.backtest import BacktestEngine, PerformanceReporter
from deltafq.charts import PerformanceChart


def main() -> None:
    fetcher = BaostockDataFetcher()
    indicators = TechnicalIndicators()
    generator = SignalGenerator()
    engine = BacktestEngine(initial_capital=500_000, commission=0.001)
    reporter = PerformanceReporter()

    ticker = "AAPL"
    start_date = "2024-01-01"
    end_date = "2024-06-30"

    data = fetcher.fetch_data(ticker=ticker, start_date=start_date, end_date=end_date)
    boll = indicators.boll(data["Close"], period=20, std_dev=2, method="population")
    signals = generator.boll_signals(price=data["Close"], bands=boll, method="touch")

    # TODO: 将信号逻辑封装为 BaseStrategy 子类，通过 add_strategy() 传入后再调用 run_backtest()
    # trades_df, values_df = engine.run_backtest(
    #     ticker=ticker,
    #     signals=signals,
    #     price_series=data["Close"],
    #     strategy_name="BOLL",
    # )

    print("Performance Summary:")
    # reporter.print_summary(ticker=ticker, trades_df=trades_df, values_df=values_df, title="Performance Summary", language="zh")


if __name__ == "__main__":
    main()