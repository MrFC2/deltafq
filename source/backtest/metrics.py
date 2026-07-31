"""绩效指标计算函数集。"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def calculate_returns(equity: pd.Series) -> pd.Series:
    """计算逐日收益率。"""
    return equity.pct_change().fillna(0.0)


def compute_cumulative_returns(returns: pd.Series) -> pd.Series:
    """从日收益率计算累计收益。"""
    return (1 + returns).cumprod() - 1


def compute_drawdown_series(returns: pd.Series) -> pd.Series:
    """从累计收益计算回撤序列。"""
    cumulative = (1 + returns).cumprod()
    peak = cumulative.cummax()
    return (cumulative - peak) / peak


def calculate_total_return(equity: pd.Series) -> float:
    """计算总收益率。"""
    return float(equity.iloc[-1] / equity.iloc[0] - 1)


def calculate_annualized_return(returns: pd.Series,
                                periods: int = 252) -> float:
    """计算年化收益率（几何复利：(1+R_total)^(periods/n) - 1）。"""
    n = len(returns)
    if n == 0:
        return 0.0
    total_return = float((1 + returns).prod() - 1)
    return float((1 + total_return) ** (periods / n) - 1)


def calculate_volatility(returns: pd.Series,
                         periods: int = 252) -> float:
    """计算年化波动率。"""
    return float(returns.std() * np.sqrt(periods))


def calculate_sharpe_ratio(returns: pd.Series,
                           risk_free: float = 0.0,
                           periods: int = 252) -> float:
    """计算年化夏普比率。"""
    excess = returns - risk_free / periods
    return float(excess.mean() / excess.std() * np.sqrt(periods)) if excess.std() else 0.0


def calculate_max_drawdown(equity: pd.Series) -> float:
    """计算最大回撤。"""
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    return float(drawdown.min())


def calculate_calmar_ratio(annualized_return: float, max_drawdown: float) -> float:
    """计算 Calmar 比率。"""
    if max_drawdown == 0:
        return float("inf") if annualized_return > 0 else 0.0
    return float(abs(annualized_return / max_drawdown))


__all__ = [
    "calculate_returns",
    "compute_cumulative_returns",
    "compute_drawdown_series",
    "calculate_total_return",
    "calculate_annualized_return",
    "calculate_volatility",
    "calculate_sharpe_ratio",
    "calculate_max_drawdown",
    "calculate_calmar_ratio",
]

