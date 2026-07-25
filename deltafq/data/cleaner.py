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
        self.logger.info("初始化数据清洗器")

    def dropna(self, data: pd.DataFrame) -> pd.DataFrame:
        """删除含 NaN 的行。"""
        cleaned_data = data.dropna()
        self.logger.info(f"删除 NaN 行：{len(data)} -> {len(cleaned_data)} 行")
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
        self.logger.info(f"填充 NaN：{na_count_before} -> {na_count_after}（method={method}）")

        return filled_data
