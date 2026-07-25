"""
DeltaFQ - A comprehensive Python quantitative finance library.

This library provides tools for strategy development, backtesting, 
paper trading, and live trading.
"""

import os
from pathlib import Path

# 从 VERSION 文件读取版本号
_version_file = Path(__file__).parent.parent / "VERSION"
if _version_file.exists():
    __version__ = _version_file.read_text().strip()
else:
    __version__ = "0.9.1"

__author__ = "DeltaF"

# 导入核心模块
from . import core
from . import data
from . import strategy
from . import backtest
from . import indicators
from . import trader
from . import live

__all__ = [
    "core",
    "data", 
    "strategy",
    "backtest",
    "indicators",
    "trader",
    "live"
]

