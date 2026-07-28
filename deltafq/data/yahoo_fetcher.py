"""
yfinance 行情拉取。
"""

from typing import Optional

import pandas as pd

from .fetcher import DataFetcher
from ..enums import Interval


class YahooDataFetcher(DataFetcher):
    """基于 yfinance 的行情拉取器。"""

    def fetch_data(self, ticker: str, start_date: str, end_date: Optional[str] = None,
                   interval: Interval = Interval.DAY_1) -> pd.DataFrame:
        try:
            import yfinance as yf
            data = yf.download(ticker, start=start_date, end=end_date, interval=interval.value, progress=False)
            if isinstance(data.columns, pd.MultiIndex) and data.columns.nlevels > 1:
                data = data.droplevel(level=1, axis=1)
            return self._cleaner.dropna(data)
        except Exception as e:
            raise RuntimeError(f"拉取 {ticker} 数据失败: {str(e)}") from e
