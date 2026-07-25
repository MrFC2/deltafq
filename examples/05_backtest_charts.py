"""Minimal example: plot price, signal, and performance charts using Plotly."""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from deltafq.data import DataFetcher
from deltafq.indicators import TechnicalIndicators
from deltafq.strategy import SignalGenerator
from deltafq.backtest import BacktestEngine
from deltafq.charts import PriceChart, SignalChart, PerformanceChart


def main() -> None:
    fetcher = DataFetcher()
    indicators = TechnicalIndicators()
    generator = SignalGenerator()
    engine = BacktestEngine() # initial_capital=1000000, commission=0.001

    price_chart = PriceChart()
    signal_chart = SignalChart()
    performance_chart = PerformanceChart()

    ticker = "AAPL"
    start_date = "2024-01-01"
    end_date = "2024-06-30"
    benchmark = "SPY"

    data = fetcher.fetch_data(ticker=ticker, start_date=start_date, end_date=end_date)
    benchmark_data = fetcher.fetch_data(ticker=benchmark, start_date=start_date, end_date=end_date)
    
    boll = indicators.boll(data["Close"], period=10, std_dev=2, method="population")
    signals = generator.boll_signals(price=data["Close"], bands=boll, method="touch")

    # TODO: 将信号逻辑封装为 BaseStrategy 子类，通过 add_strategy() 传入后再调用 run_backtest()
    # trades_df, values_df = engine.run_backtest(
    #     ticker=ticker,
    #     signals=signals,
    #     price_series=data["Close"],
    #     strategy_name="BOLL",
    # )
    # print(trades_df)
    
    print("Plotting Plotly charts...")

    data_dict = {ticker: data, benchmark: benchmark_data}
    price_chart.plot_prices(
        data=data_dict,
        title=f"{ticker} Price vs {benchmark} Price",
        use_plotly=True,
    )

    signal_chart.plot_boll_signals(
        data=data,
        bands=boll,
        signals=signals,
        title="Bollinger Signals",
        use_plotly=True,
    )

    performance_chart.plot_backtest_charts(
        values_df=values_df,
        benchmark_close=benchmark_data["Close"],
        title="Bollinger Bands Backtest Performance",
        use_plotly=True,
    )


if __name__ == "__main__":
    main()

