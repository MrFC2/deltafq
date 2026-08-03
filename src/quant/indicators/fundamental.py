"""
Fundamental indicators for DeltaFQ.
"""

import pandas as pd
from ..core.base import BaseComponent


class FundamentalIndicators(BaseComponent):
    """基本面指标计算器。"""

    def __init__(self, **kwargs):
        """初始化基本面指标计算器。"""
        super().__init__(**kwargs)
                         
    def pe(self, price: pd.Series, eps_ttm: pd.Series) -> pd.Series:
        """PE = 价格 / EPS"""
        eps = eps_ttm.reindex(price.index).ffill()
        return price / eps

    def pb(self, price: pd.Series, bvps: pd.Series) -> pd.Series:
        """PB = 价格 / 每股净资产"""
        bvps = bvps.reindex(price.index).ffill()
        return price / bvps

    def ps(self, market_cap: pd.Series, revenue: pd.Series) -> pd.Series:
        """PS = 市值 / 营收"""
        revenue = revenue.reindex(market_cap.index).ffill()
        return market_cap / revenue

    def roa(self, net_income: pd.Series, total_assets: pd.Series) -> pd.Series:
        """ROA = 净利润 / 总资产"""
        assets = total_assets.reindex(net_income.index).ffill()
        return net_income / assets

    def roe(self, net_income: pd.Series, shareholders_equity: pd.Series) -> pd.Series:
        """ROE = 净利润 / 股东权益"""
        equity = shareholders_equity.reindex(net_income.index).ffill()
        return net_income / equity

    def gross_margin(self, gross_profit: pd.Series, revenue: pd.Series) -> pd.Series:
        """gross margin = gross profit / revenue"""
        revenue_aligned = revenue.reindex(gross_profit.index).ffill()
        return gross_profit / revenue_aligned