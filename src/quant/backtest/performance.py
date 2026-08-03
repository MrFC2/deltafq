"""绩效计算工具。"""

from __future__ import annotations

import math
from typing import Any, Dict

import pandas as pd

from ..core.base import BaseComponent
from .metrics import (
    calculate_annualized_return,
    calculate_calmar_ratio,
    calculate_max_drawdown,
    calculate_returns,
    calculate_sharpe_ratio,
    calculate_total_return,
    calculate_volatility,
    compute_cumulative_returns,
    compute_drawdown_series,
)

_EMPTY_TRADE_METRICS: Dict[str, Any] = {
    "total_trades": 0,
    "total_pnl": 0.0,
    "win_rate": 0.0,
    "winning_trades": 0,
    "losing_trades": 0,
    "avg_win": 0.0,
    "avg_loss": 0.0,
    "profit_loss_ratio": 0.0,
}

_EMPTY_TRADING_METRICS: Dict[str, float] = {
    "total_commission": 0.0,
    "total_turnover": 0.0,
    "avg_daily_pnl": 0.0,
    "avg_daily_commission": 0.0,
    "avg_daily_turnover": 0.0,
    "avg_daily_trade_count": 0.0,
}


class PerformanceReporter(BaseComponent):
    """计算回测绩效指标。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @staticmethod
    def compute(
            ticker: str,
            trades_df: pd.DataFrame,
            values_df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, Dict[str, Any]]:
        """
        计算所有绩效指标。

        Returns
        -------
        values : pd.DataFrame
            附加了 returns / cumulative_returns / drawdown 列的净值表。
        metrics : dict
            所有绩效指标字典。
        """
        values = _prepare_values(values_df)
        trades = _prepare_trades(trades_df)

        equity = values.get("total_value", pd.Series(dtype=float, index=values.index)).astype(float)
        has_equity = len(equity) > 1

        # ── 日收益率及衍生序列 ─────────────────────────────────
        returns = (
            calculate_returns(equity).reindex(values.index, fill_value=0.0)
            if has_equity else pd.Series(0.0, index=values.index)
        )
        values["returns"] = returns
        values["cumulative_returns"] = compute_cumulative_returns(returns)
        values["drawdown"] = compute_drawdown_series(returns)

        # ── 资金 ──────────────────────────────────────────────
        start_capital = float(equity.iloc[0]) if not equity.empty else 0.0
        end_capital = float(equity.iloc[-1]) if not equity.empty else start_capital

        # ── 交易日统计 ────────────────────────────────────────
        total_days = len(values)
        pnl_series = values.get("daily_pnl", pd.Series(0.0, index=values.index))
        profitable_days = int((pnl_series > 0).sum())
        losing_days = int((pnl_series < 0).sum())

        # ── 首末日期：回测区间取 values，实际首末交易取 trades ──
        first_trade_date = values.index[0]  if not values.empty else None
        last_trade_date  = values.index[-1] if not values.empty else None

        # ── 收益 / 风险指标 ───────────────────────────────────
        total_return = calculate_total_return(equity) if has_equity else 0.0
        annualized_return = calculate_annualized_return(returns) if has_equity else 0.0
        avg_daily_return = float(returns.mean())
        return_std = float(returns.std())  # 日频标准差
        volatility = calculate_volatility(returns) if has_equity else 0.0  # 年化波动率
        sharpe_ratio = calculate_sharpe_ratio(returns) if has_equity else 0.0
        max_drawdown = calculate_max_drawdown(equity) if has_equity else 0.0
        calmar = calculate_calmar_ratio(annualized_return, max_drawdown)
        return_drawdown_ratio = (
            calmar if math.isfinite(calmar)
            else (abs(annualized_return / max_drawdown) if max_drawdown else float("inf"))
        )

        # ── 交易统计 ──────────────────────────────────────────
        trade_metrics = _calculate_trade_metrics(trades)
        trading_metrics = _calculate_trading_metrics(trades, total_days)

        # ── 浮动盈亏（未平仓持仓）────────────────────────────
        unrealized_pnl = _calc_unrealized_pnl(values_df, trades)
        total_pnl = trade_metrics.get("total_pnl", 0.0) + unrealized_pnl

        metrics: Dict[str, Any] = {
            "ticker": ticker,
            "first_trade_date": first_trade_date,
            "last_trade_date": last_trade_date,
            "total_trading_days": total_days,
            "profitable_days": profitable_days,
            "losing_days": losing_days,
            # 资金
            "start_capital": start_capital,
            "end_capital": end_capital,
            # 收益
            "total_return": total_return,
            "annualized_return": annualized_return,
            "avg_daily_return": avg_daily_return,
            # 风险
            "max_drawdown": max_drawdown,
            "return_std": return_std,
            "volatility": volatility,
            # 绩效
            "sharpe_ratio": sharpe_ratio,
            "return_drawdown_ratio": return_drawdown_ratio,
            "win_rate": trade_metrics.get("win_rate", 0.0),
            "profit_loss_ratio": trade_metrics.get("profit_loss_ratio", 0.0),
            "avg_win": trade_metrics.get("avg_win", 0.0),
            "avg_loss": trade_metrics.get("avg_loss", 0.0),
            # 交易汇总
            "total_pnl": total_pnl,
            "total_commission": trading_metrics.get("total_commission", 0.0),
            "total_turnover": trading_metrics.get("total_turnover", 0.0),
            "total_trade_count": trade_metrics.get("total_trades", 0),
            # 日均
            "avg_daily_pnl": trading_metrics.get("avg_daily_pnl", 0.0),
            "avg_daily_commission": trading_metrics.get("avg_daily_commission", 0.0),
            "avg_daily_turnover": trading_metrics.get("avg_daily_turnover", 0.0),
            "avg_daily_trade_count": trading_metrics.get("avg_daily_trade_count", 0.0),
        }

        return values, metrics


# ── 内部辅助函数 ───────────────────────────────────────────────────────

def _prepare_values(values_df: pd.DataFrame) -> pd.DataFrame:
    df = values_df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def _prepare_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    df = trades_df.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def _calculate_trade_metrics(trades: pd.DataFrame) -> Dict[str, Any]:
    """从交易记录计算胜率、盈亏比等。"""
    if trades.empty or "profit_loss" not in trades.columns:
        return _EMPTY_TRADE_METRICS.copy()

    pnl = trades["profit_loss"].dropna()
    if pnl.empty:
        return _EMPTY_TRADE_METRICS.copy()

    winning = pnl[pnl > 0]
    losing = pnl[pnl < 0]
    avg_win = float(winning.mean()) if not winning.empty else 0.0
    avg_loss = float(losing.mean()) if not losing.empty else 0.0
    profit_loss_ratio = (
        float(avg_win / abs(avg_loss)) if avg_loss
        else (float("inf") if avg_win > 0 else 0.0)
    )

    return {
        "total_trades": int(len(trades)),  # 全部交易笔数（含买入）
        "total_pnl": float(pnl.sum()),
        "win_rate": float((pnl > 0).mean()),
        "winning_trades": int((pnl > 0).sum()),
        "losing_trades": int((pnl < 0).sum()),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_loss_ratio": profit_loss_ratio,
    }


def _calculate_trading_metrics(trades: pd.DataFrame, total_days: int) -> Dict[str, float]:
    """计算成交额、手续费等日均统计。"""
    if trades.empty:
        return _EMPTY_TRADING_METRICS.copy()

    commission = float(trades.get("commission", pd.Series(dtype=float)).sum())
    if "quantity" in trades.columns and "price" in trades.columns:
        turnover = float((trades["quantity"].abs() * trades["price"]).sum())
    else:
        turnover = float(trades.get("gross_revenue", pd.Series(dtype=float)).sum())

    pnl = float(trades.get("profit_loss", pd.Series(dtype=float)).sum())
    divisor = total_days or 1

    return {
        "total_commission": commission,
        "total_turnover": turnover,
        "avg_daily_pnl": pnl / divisor,
        "avg_daily_commission": commission / divisor,
        "avg_daily_turnover": turnover / divisor,
        "avg_daily_trade_count": len(trades) / divisor,
    }


def _calc_unrealized_pnl(values_df: pd.DataFrame, trades: pd.DataFrame) -> float:
    """计算未平仓持仓的浮动盈亏。无持仓或数据不足时返回 0.0。"""
    if values_df.empty or trades.empty:
        return 0.0
    required = {"type", "cost", "quantity"}
    if not required.issubset(trades.columns):
        return 0.0

    last_row = values_df.iloc[-1]
    final_position = last_row.get("position", 0)
    if final_position <= 0:
        return 0.0

    final_position_value = float(last_row.get("position_value", 0.0))
    buy_trades = trades[trades["type"] == "buy"]
    sell_trades = trades[trades["type"] == "sell"]

    if buy_trades.empty:
        return 0.0

    total_buy_qty = buy_trades["quantity"].sum()
    total_buy_cost = buy_trades["cost"].sum()
    total_sell_qty = sell_trades["quantity"].sum() if not sell_trades.empty else 0

    open_qty = total_buy_qty - total_sell_qty
    if open_qty <= 0 or total_buy_qty <= 0:
        return 0.0

    # 未平仓成本按平均成本比例分摊
    avg_cost = total_buy_cost / total_buy_qty
    open_cost = open_qty * avg_cost
    return float(final_position_value - open_cost)


__all__ = ["PerformanceReporter"]
