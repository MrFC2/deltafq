"""Minimal example: fetch A-share OHLCV via DataFetcher with source=miniqmt (xtquant / miniQMT)."""

import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from source.data import QmtDataFetcher, DataStorage
from source.enums import Interval

# 需本机启动 miniQMT、已安装 xtquant；标的为 xt 代码，如 000001.SZ、600000.SH

def main() -> None:
    ticker = "600000.SH"
    start_date = "2026-04-01"
    end_date = "2026-04-16"

    fetcher = QmtDataFetcher()
    data = fetcher.fetch_data(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        interval=Interval.MINUTE_1,
    )
    
    storage = DataStorage()
    path = storage.save_price_data(data, ticker=ticker, start_date=start_date, end_date=end_date)
    print(data)
    print(f"Saved to: {path}")


if __name__ == "__main__":
    main()
