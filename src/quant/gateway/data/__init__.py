from .base import DataGateway
from .baostock_gateway import BaostockDataGateway

try:
    from .qmt_gateway import QmtDataGateway
except ImportError:
    QmtDataGateway = None  # type: ignore

__all__ = ["DataGateway", "BaostockDataGateway", "QmtDataGateway"]
