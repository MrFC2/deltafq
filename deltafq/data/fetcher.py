"""
行情数据拉取。

- yahoo: yfinance api
- miniQMT: xtquant api，需要本机运行 miniQMT 终端
- baostock: baostock api（A 股历史 K 线）
- eastmoney: 东方财富 api
"""

import pandas as pd
import yfinance as yf
import re
import requests
from typing import List, Optional, Dict, Any, Union
from ..core.base import BaseComponent
from .cleaner import DataCleaner
from ..enums import DataSource
import warnings

warnings.filterwarnings('ignore')


class DataFetcher(BaseComponent):
    """多数据源行情拉取器。"""

    def __init__(self, source: Union[DataSource, str] = DataSource.BAOSTOCK, **kwargs: Any) -> None:
        """初始化数据拉取器。"""
        super().__init__(**kwargs)
        self.source = source.value if isinstance(source, DataSource) else source
        self._cleaner = DataCleaner()

    def fetch_data(self, ticker: str, start_date: str, end_date: Optional[str] = None,
                   interval: str = "1d") -> pd.DataFrame:
        """拉取行情数据并清洗。interval 示例：'1m'、'1h'、'1d'（默认）、'1wk'、'1mo'。"""
        try:
            if self.source == "baostock":
                from ..adapters.data.baostock_bars import fetch_baostock_bars
                data = fetch_baostock_bars(ticker, start_date, end_date, interval=interval)
            elif self.source == "miniqmt":
                from ..adapters.data.miniqmt_bars import fetch_miniqmt_bars
                data = fetch_miniqmt_bars(ticker, start_date, end_date, interval=interval)
            else:
                data = yf.download(ticker, start=start_date, end=end_date, interval=interval, progress=False)
                if isinstance(data.columns, pd.MultiIndex) and data.columns.nlevels > 1:
                    data = data.droplevel(level=1, axis=1)
            return self._cleaner.dropna(data)
        except Exception as e:
            raise RuntimeError(f"拉取 {ticker} 数据失败: {str(e)}") from e

    def fetch_datas(self, tickers: List[str], start_date: str, end_date: Optional[str] = None,
                    interval: str = "1d") -> Dict[str, pd.DataFrame]:
        """批量拉取多个标的行情数据。"""
        return {s: self.fetch_data(s, start_date, end_date, interval) for s in tickers}

    def fetch_data_from_fund(self, code: str, page: Optional[int] = None) -> pd.DataFrame:
        """从东方财富 API 拉取基金净值数据。"""
        base_url = "https://fundf10.eastmoney.com/F10DataApi.aspx"
        base_params = {"type": "lsjz", "per": 20, "code": code}

        def _get_page(p: int) -> pd.DataFrame:
            params = {**base_params, "page": p}
            resp = requests.get(base_url, params=params)
            match = re.search(r'content:"([^"]+)"', resp.text, re.DOTALL)
            if not match:
                raise ValueError(f"无法解析 API 响应（page={p}）")
            html_content = match.group(1).replace('\\r\\n', '\n').replace('\\"', '"')
            dfs = pd.read_html(html_content)
            return dfs[0] if dfs else pd.DataFrame()

        try:
            if page is None:
                params = {**base_params, "page": 1}
                resp = requests.get(base_url, params=params)
                match = re.search(r'pages:(\d+)', resp.text)
                max_pages = int(match.group(1)) if match else 1


                all_dfs = [_get_page(p) for p in range(1, max_pages + 1)]
                result = pd.concat(all_dfs, ignore_index=True)
                return result

            return _get_page(page)
        except Exception as e:
            raise RuntimeError(f"拉取基金 {code} 数据失败: {str(e)}") from e
