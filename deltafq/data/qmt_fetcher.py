"""
miniQMT 历史 K 线适配（xtdata）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

import pandas as pd

from deltafq.data.fetcher import DataFetcher
from deltafq.enums import Interval
from deltafq.core.models import TickerData

# Interval 枚举 → xt 周期；未命中的 Interval 直接用其 value 透传。
_PERIOD_MAP = {
    Interval.MINUTE_1: "1m",
    Interval.MINUTE_5: "5m",
    Interval.MINUTE_15: "15m",
    Interval.MINUTE_30: "30m",
    Interval.HOUR_1: "60m",
    Interval.DAY_1: "1d",
    Interval.WEEK_1: "1w",
    Interval.MONTH_1: "1mon",
}
_XT_PERIODS = frozenset(_PERIOD_MAP.values())

_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")
_OHLCV_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class QmtDataFetcher(DataFetcher):
    """基于 xtquant 的行情拉取器（需本机运行 miniQMT 终端）。"""

    def fetch_data(self,
                   ticker: str,
                   start_date: str,
                   end_date: Optional[str] = None,
                   interval: Interval = Interval.DAY_1) -> List[TickerData]:
        try:
            data = fetch_data(ticker, start_date, end_date, interval=interval)
            data = self._cleaner.dropna(data)
            return self.df_to_ticker_data(ticker, data)
        except Exception as e:
            raise RuntimeError(f"拉取 {ticker} 数据失败: {str(e)}") from e


def import_xtdata() -> Any:
    """导入 xtdata；未安装 xtquant 时给出明确错误提示。"""
    try:
        from xtquant import xtdata  # type: ignore
    except ImportError as e:
        raise ImportError(
            "miniQMT requires xtquant (pip install xtquant). Ensure miniQMT is running when using xtdata."
        ) from e
    return xtdata


def interval_to_xt_period(interval: Interval) -> str:
    """把 Interval 枚举转为 xt 周期并校验合法性。"""
    p = _PERIOD_MAP.get(interval)
    if p is None:
        raise ValueError(f"不支持的周期: {interval!r}")
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


def fetch_data(
        ticker: str,
        start_date: str,
        end_date: Optional[str] = None,
        interval: Interval = Interval.DAY_1,
        dividend_type: str = "none",
) -> pd.DataFrame:
    """拉取历史 K 线并返回 Open/High/Low/Close/Volume 列。"""
    xtdata = import_xtdata()
    period = interval_to_xt_period(interval)
    t0 = _compact_date(start_date)
    t1 = _end_exclusive_to_xt(end_date) if end_date else ""

    xtdata.download_history_data(ticker, period, t0, t1)

    fields = ["time", *_OHLCV_FIELDS]
    bars = xtdata.get_market_data(
        field_list=fields,
        stock_list=[ticker],
        period=period,
        start_time=t0,
        end_time=t1,
        count=-1,
        dividend_type=dividend_type,
        fill_data=True,
    )

    loc = bars["time"].loc[ticker].values
    idx = pd.DatetimeIndex(pd.to_datetime(loc, unit="ms"))
    data = {col: bars[f].loc[ticker].values for f, col in zip(_OHLCV_FIELDS, _OHLCV_COLUMNS)}
    return pd.DataFrame(data, index=idx).sort_index()
