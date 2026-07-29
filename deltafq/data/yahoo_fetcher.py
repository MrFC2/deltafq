"""
yfinance 行情拉取。
"""

from typing import List, Optional

import pandas as pd

from .fetcher import DataFetcher
from ..enums import Interval
from ..core.models import TickerData


class YahooDataFetcher(DataFetcher):
    """基于 yfinance 的行情拉取器。"""

    def fetch_data(self, ticker: str, start_date: str, end_date: Optional[str] = None,
                   interval: Interval = Interval.DAY_1) -> List[TickerData]:
        try:
            import yfinance as yf
            data = yf.download(ticker, start=start_date, end=end_date, interval=interval.value, progress=False)
            if isinstance(data.columns, pd.MultiIndex) and data.columns.nlevels > 1:
                data = data.droplevel(level=1, axis=1)
            data = self._cleaner.dropna(data)
            return self.df_to_ticker_data(ticker, data)
        except Exception as e:
            raise RuntimeError(f"拉取 {ticker} 数据失败: {str(e)}") from e
