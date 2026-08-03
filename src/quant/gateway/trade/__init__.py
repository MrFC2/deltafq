from .base import TradeGateway
from .paper_gateway import PaperTradeGateway

try:
    from .qmt_client import QmtXtTraderClient
    from .qmt_gateway import QmtTradeGateway
except ImportError:
    QmtXtTraderClient = None  # type: ignore
    QmtTradeGateway = None  # type: ignore

__all__ = ["TradeGateway", "QmtTradeGateway", "QmtXtTraderClient", "PaperTradeGateway"]
