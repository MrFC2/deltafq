"""Minimal BacktestEngine usage example."""

import os
import sys
from typing import Any

import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from deltafq.backtest import BacktestEngine
from deltafq.strategy.base import BaseStrategy
from deltafq.data import BaostockDataFetcher


class SimpleMAStrategy(BaseStrategy):
    """Simple moving-average crossover strategy."""

    def __init__(self, fast_period: int = 5, slow_period: int = 20, **kwargs: Any) -> None:
        super().__init__(name="SimpleMA", **kwargs)
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        closes = data["Close"].astype(float)
        fast_ma = closes.rolling(window=self.fast_period, min_periods=1).mean()
        slow_ma = closes.rolling(window=self.slow_period, min_periods=1).mean()

        signals = pd.Series(0, index=closes.index, dtype=int)
        signals = signals.mask(fast_ma > slow_ma, 1)
        signals = signals.mask(fast_ma < slow_ma, -1)

        return signals


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
