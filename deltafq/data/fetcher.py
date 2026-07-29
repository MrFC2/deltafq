"""
行情数据拉取抽象基类。

子类实现：
- YahooDataFetcher    — yahoo_fetcher.py
- BaostockDataFetcher — baostock_fetcher.py
- MiniQmtDataFetcher  — miniqmt_fetcher.py
"""

import re
import requests
import pandas as pd
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from ..core.base import BaseComponent
from .cleaner import DataCleaner
from ..enums import Interval

import warnings
warnings.filterwarnings('ignore')


class DataFetcher(BaseComponent, ABC):
    """行情数据拉取器抽象基类。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cleaner = DataCleaner()

    @abstractmethod
    def fetch_data(self, ticker: str, start_date: str, end_date: Optional[str] = None,
                   interval: Interval = Interval.DAY_1) -> pd.DataFrame:
        """拉取单个标的行情数据并清洗。"""
        raise NotImplementedError

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
                resp = requests.get(base_url, params={**base_params, "page": 1})
                match = re.search(r'pages:(\d+)', resp.text)
                max_pages = int(match.group(1)) if match else 1
                all_dfs = [_get_page(p) for p in range(1, max_pages + 1)]
                return pd.concat(all_dfs, ignore_index=True)
            return _get_page(page)
        except Exception as e:
            raise RuntimeError(f"拉取基金 {code} 数据失败: {str(e)}") from e
