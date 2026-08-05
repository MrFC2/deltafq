from .base import DataGateway
from .dev_gateway import DevDataGateway

try:
    from .qmt_gateway import QmtDataGateway
except ImportError:
    QmtDataGateway = None  # type: ignore

__all__ = ["DataGateway", "DevDataGateway", "QmtDataGateway"]
