"""
miniQMT 历史 K 线适配（xtdata）。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import pandas as pd
from xtquant import xtdata  # type: ignore

from source.data.fetcher import DataFetcher
from source.enums import Period
from source.core.models import TickerData

# Period 枚举 → xt 周期；未命中的 Period 直接用其 value 透传。
_PERIOD_MAP = {
    Period.MINUTE_1: "1m",
    Period.MINUTE_5: "5m",
    Period.MINUTE_15: "15m",
    Period.MINUTE_30: "30m",
    Period.HOUR_1: "60m",
    Period.DAY_1: "1d",
    Period.WEEK_1: "1w",
    Period.MONTH_1: "1mon",
}
_XT_PERIODS = frozenset(_PERIOD_MAP.values())

_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")
_OHLCV_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class QmtDataFetcher(DataFetcher):
    """基于 xtquant 的行情拉取器（需本机运行 miniQMT 终端）。"""

    def fetch_data(self,
                   ticker: str,
                   period: Period,
                   start_date: str,
                   end_date: Optional[str] = None) -> List[TickerData]:
        try:
            return fetch_data(ticker, start_date, end_date, period)
        except Exception as e:
            raise RuntimeError(f"拉取 {ticker} 数据失败: {str(e)}") from e


def period_to_xt_period(period: Period) -> str:
    """把 Period 枚举转为 xt 周期并校验合法性。"""
    p = _PERIOD_MAP.get(period)
    if p is None:
        raise ValueError(f"不支持的周期: {period!r}")
    return p


def _compact_date(s: str) -> str:
    return s.replace("-", "")[:8]


def _end_exclusive_to_xt(end_date: Optional[str]) -> str:
    """把排他 end_date 转成 xt 结束日字符串；默认加 1 天。"""
    if not end_date:
        return ""
    ymd = _compact_date(end_date)
    try:
        return (datetime.strptime(ymd, "%Y%m%d") + pd.Timedelta(days=1)).strftime("%Y%m%d")
    except ValueError:
        return ymd


def fetch_data(ticker: str,
               start_date: str,
               end_date: Optional[str] = None,
               period: Period = Period.DAY_1,
               dividend_type: str = "none") -> List[TickerData]:
    """拉取历史 K 线并返回 TickerData 列表。"""
    xt_period = period_to_xt_period(period)
    start_time = _compact_date(start_date)
    end_time = _end_exclusive_to_xt(end_date) if end_date else ""

    fields = ["time", *_OHLCV_FIELDS]
    bars = xtdata.get_market_data(field_list=fields, stock_list=[ticker], period=xt_period, start_time=start_time,
                                  end_time=end_time, count=-1, dividend_type=dividend_type, fill_data=True)

    loc = bars["time"].loc[ticker].values
    idx = pd.DatetimeIndex(pd.to_datetime(loc, unit="ms"))
    data = {col: bars[f].loc[ticker].values for f, col in zip(_OHLCV_FIELDS, _OHLCV_COLUMNS)}
    df = pd.DataFrame(data, index=idx).sort_index()
    return DataFetcher.df_to_ticker_data(ticker, df)
