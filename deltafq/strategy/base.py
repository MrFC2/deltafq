"""策略基类。"""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from ..core.base import BaseComponent


class BaseStrategy(BaseComponent, ABC):
    """策略基类，子类实现 generate_signals 即可。"""

    def __init__(self, name: str = None, **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """返回 {-1, 0, 1} 信号序列。"""
        pass
