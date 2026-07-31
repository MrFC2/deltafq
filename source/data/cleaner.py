"""
数据清洗工具。
"""

import pandas as pd
from ..core.base import BaseComponent


class DataCleaner(BaseComponent):
    """数据清洗工具。"""

    def __init__(self, **kwargs):
        """初始化数据清洗器。"""
        super().__init__(**kwargs)

    def dropna(self, data: pd.DataFrame) -> pd.DataFrame:
        """删除含 NaN 的行。"""
        cleaned_data = data.dropna()
        return cleaned_data

    def fillna(self, data: pd.DataFrame, method: str = "forward") -> pd.DataFrame:
        """填充缺失值。method: 'forward'（前向）、'backward'（后向）或填 0。"""
        na_count_before = data.isna().sum().sum()

        if method == "forward":
            filled_data = data.ffill()
        elif method == "backward":
            filled_data = data.bfill()
        else:
            filled_data = data.fillna(0)

        na_count_after = filled_data.isna().sum().sum()

        return filled_data
