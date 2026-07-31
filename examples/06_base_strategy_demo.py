"""Minimal BaseStrategy usage example (fetch data + generate signals)."""

import os
import sys
from typing import Any, List

import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from source.data import BaostockDataFetcher
from source.strategy.base import BaseStrategy
from source.core.models import SignalData, TickerData
from source.enums import Signal


class DemoStrategy(BaseStrategy):
    """Simple moving-average crossover strategy."""

    def __init__(self, fast_period: int = 5, slow_period: int = 20, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signals(self, data: List[TickerData]) -> List[SignalData]:
        closes = pd.Series([t.price for t in data], index=[t.timestamp for t in data])
        fast_ma = closes.rolling(window=self.fast_period, min_periods=1).mean()
        slow_ma = closes.rolling(window=self.slow_period, min_periods=1).mean()

        result = []
        for t in data:
            ts = t.timestamp
            if fast_ma[ts] > slow_ma[ts]:
                sig = Signal.BUY
            elif fast_ma[ts] < slow_ma[ts]:
                sig = Signal.SELL
            else:
                sig = Signal.HOLD
            result.append(SignalData(timestamp=ts, signal=sig))
        return result


def run_strategy_demo() -> None:
    print("=== BaseStrategy Demo Strategy ===")

    fetcher = BaostockDataFetcher() # switch to YahooDataFetcher / MiniQmtDataFetcher as needed
    strategy = DemoStrategy(name="DemoStrategy", fast_period=10, slow_period=30)

    data = fetcher.fetch_data(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2024-06-30",
    )

    signals = strategy.run(data)

    print(f"Strategy name: {strategy.name}")
    print(f"Signals:\n{signals}")
    print(f"Buy count: {(signals == 1).sum()}")
    print(f"Sell count: {(signals == -1).sum()}")
    print(f"Hold count: {(signals == 0).sum()}")


if __name__ == "__main__":
    run_strategy_demo()
