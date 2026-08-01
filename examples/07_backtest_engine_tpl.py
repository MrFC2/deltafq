"""Minimal BacktestEngine usage example."""

import os
import sys
from typing import Any, List

import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from source.backtest import BacktestEngine
from source.strategy.base import BaseStrategy
from source.data import BaostockDataFetcher
from source.core.models import SignalData, TickerData
from source.enums import Signal, Interval


class SimpleMAStrategy(BaseStrategy):
    """Simple moving-average crossover strategy."""

    def __init__(self, fast_period: int = 5, slow_period: int = 20, **kwargs: Any) -> None:
        super().__init__(name="SimpleMA", interval=Interval.DAY_1, **kwargs)
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


def main() -> None:
    strategy = SimpleMAStrategy(fast_period=5, slow_period=10)
    engine = BacktestEngine(
        ticker="sz.000001",  # 平安银行
        strategy=strategy,
        start_date="2024-01-01",
        end_date="2024-12-31",
        # benchmark="sh.000300",  # 沪深300
        data_fetcher=BaostockDataFetcher(),
    )
    engine.run()


if __name__ == "__main__":
    main()
