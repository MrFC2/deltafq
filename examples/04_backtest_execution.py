"""Minimal example: run the backtest engine and execute the trades."""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from source.data import BaostockDataFetcher
from source.indicators import TechnicalIndicators
from source.strategy import SignalGenerator
from source.backtest import BacktestEngine


def main() -> None:
    fetcher = BaostockDataFetcher() # switch to YahooDataFetcher / MiniQmtDataFetcher as needed
    indicators = TechnicalIndicators()
    generator = SignalGenerator()
    engine = BacktestEngine(initial_capital=10000, commission=0.0005) # default initial_capital=1000000, commission=0.001

    ticker = "AAPL"
    start_date = "2024-01-01"
    end_date = "2024-06-30"
    data = fetcher.fetch_data(ticker=ticker, start_date=start_date, end_date=end_date)

    # Take BOLL as signal
    boll = indicators.boll(data["Close"], period=20, std_dev=2, method="population")
    signals = generator.boll_signals(price=data["Close"], bands=boll, method="touch")

    # TODO: 将信号逻辑封装为 BaseStrategy 子类，通过 add_strategy() 传入后再调用 run_backtest()
    # trades_df, values_df = engine.run_backtest(ticker=ticker, signals=signals, price_series=data["Close"])

    print("Trades:")
    # print(trades_df)
    print("\nPortfolio values:")
    # print(values_df)


if __name__ == "__main__":
    main()