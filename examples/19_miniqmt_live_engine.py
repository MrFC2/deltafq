"""Minimal example: LiveEngine + miniQMT 行情/交易；策略按次循环输出信号 0, 1, -1。"""

import os
import sys
import time

import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from source.live import LiveEngine
from source.adapters.data.qmt_gateway import QmtDataGateway
from source.adapters.trade.qmt_gateway import QmtTradeGateway
from source.strategy.base import BaseStrategy
from source.enums import Interval
from source.core.models import SignalData, TickerData
from source.enums import Signal
from typing import List

MIN_PATH = os.environ.get("QMT_USERDATA_MINI", r"D:\国金证券QMT交易端\userdata_mini")
ACCOUNT_ID = os.environ.get("QMT_ACCOUNT_ID", "8886180407")


class DemoStrategy(BaseStrategy):
    """信号按次循环输出：0 → 1 → -1 → 0 → …；order_quantity 统一买卖股数上限。"""

    _SEQ = (0, 1, -1)

    def __init__(self, **kwargs):
        super().__init__(interval=Interval.MINUTE_1, **kwargs)
        self.order_quantity = 100
        self._i = 0

    def generate_signals(self, data: List[TickerData]) -> List[SignalData]:
        sig = Signal(self._SEQ[self._i % len(self._SEQ)])
        self._i += 1
        return [SignalData(timestamp=t.timestamp, signal=sig) for t in data]


def main() -> None:
    engine = LiveEngine(
        ticker="159118.SZ",
        data_gateway=QmtDataGateway(interval=5.0, mode="poll"),
        trade_gateway=QmtTradeGateway(
            userdata_mini_path=MIN_PATH,
            account_id=ACCOUNT_ID,
            strategy_name="deltafq_order_amount_demo",
            lot_size=100,
        ),
        strategy=DemoStrategy(name="SeqNeg010"),
        strategy_input_size=10,
    )
    engine.run()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
