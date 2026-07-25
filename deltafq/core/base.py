"""
Base classes for DeltaFQ components.
"""

from abc import ABC
from .logger import Logger


class BaseComponent(ABC):
    """所有组件的基类。"""
    
    def __init__(self, name: str = None, **kwargs):
        """初始化组件。"""
        self.name = name or self.__class__.__name__
        self.logger = Logger(self.name)
    
    def initialize(self) -> bool:
        """初始化组件，如建立外部服务连接。"""
        return True

