"""Minimal demo: strategy automation — 5m signal every 5 min, daily signal once per day."""

import os
import sys
import time
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd
from quant.data import BaostockDataFetcher, DataStorage
from quant.strategy.base import BaseStrategy
from quant.trader.engine import TraderEngine
from quant.core.models import SignalData, TickerData
from quant.enums import Signal, Period
from typing import List


class SimpleMAStrategy(BaseStrategy):
    def __init__(self, fast_period: int = 5, slow_period: int = 20, **kwargs):
        super().__init__(period=Period.DAY_1, **kwargs)
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


def run_signal(fetcher, strategy, ticker, start, end, interval, storage=None):
    data = fetcher.fetch_data(ticker, start, end, interval=interval)
    if storage is not None and data:
        storage.save_price_data(data, ticker, start, end)
    if not data or len(data) < 2:
        return Signal.HOLD, None
    signals = strategy.generate_signals(data)
    return signals[-1].signal, float(data[-1].price)


def try_trade(engine, ticker, signal, price, qty, now):
    if signal == 1 and price:
        buy_qty = min(qty, int(engine.cash / (price * (1 + engine.commission))))
        if buy_qty > 0:
            engine.execute_order(ticker, buy_qty, "limit", price=price, timestamp=now)
    elif signal == -1 and price:
        pos = engine.position_manager.get_position(ticker)
        if pos > 0:
            engine.execute_order(ticker, -pos, "limit", price=price, timestamp=now)


def main():
    ticker = "000001.SS"
    fetcher = BaostockDataFetcher()
    storage = DataStorage()
    engine = TraderEngine(cash=100_000, commission=0.001, simulate_match=False)
    qty = 100
    # (interval, strategy, start, end, daily_only)
    tasks = [
        ("5m", SimpleMAStrategy(name="MA5m", fast_period=3, slow_period=8), "2026-02-01", "2026-02-14", False),
        ("1d", SimpleMAStrategy(name="MA1d", fast_period=5, slow_period=20), "2025-08-01", "2026-02-21", True),
    ]
    last_day_done = None

    while True:
        now = datetime.now()
        for interval, strategy, start, end, daily_only in tasks:
            if daily_only and last_day_done == now.date():
                continue
            s, p = run_signal(fetcher, strategy, ticker, start, end, interval, storage)
            print(now.isoformat(), interval, s)
            try_trade(engine, ticker, s, p, qty, now)
            if daily_only:
                last_day_done = now.date()
        time.sleep(5 * 60)


if __name__ == "__main__":
    main()
