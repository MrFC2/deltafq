"""策略基类。"""

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from ..core.base import BaseComponent
from ..core.models import SignalData, TickerData
from ..enums import Period


class BaseStrategy(BaseComponent, ABC):
    """策略基类，子类实现 generate_signals 即可。"""

    def __init__(self, name: str, period: Period, data_size: int = 100, **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)
        # 策略期望收到的 K 线周期，引擎据此决定拉取数据的粒度
        self.period: Period = period
        # 策略需要的历史数据点数（K 线根数或 tick 数），引擎据此设置滑动窗口大小
        self.data_size: int = data_size

    @abstractmethod
    def generate_signals(self,
                         data: List[TickerData],
                         cash: Optional[float] = None,
                         position: Optional[int] = None,
                         commission: Optional[float] = None) -> List[SignalData]:
        """返回信号列表，按时间升序，与 data 等长。
        cash/position/commission 由引擎传入，策略可据此为最新信号填写 quantity。
        """
        pass
