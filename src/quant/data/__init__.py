"""
Data management module for DeltaFQ.
"""

from .fetcher import DataFetcher
from .baostock_fetcher import BaostockDataFetcher
from .cleaner import DataCleaner
from .storage import DataStorage

try:
    from .qmt_fetcher import QmtDataFetcher
except ImportError:
    QmtDataFetcher = None  # type: ignore

__all__ = [
    "DataFetcher",
    "BaostockDataFetcher",
    "QmtDataFetcher",
    "DataCleaner",
    "DataStorage",
]
