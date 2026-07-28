"""
baostock 历史 K 线适配。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from deltafq.data.fetcher import DataFetcher
from deltafq.enums import Interval

# yfinance 风格 → baostock frequency
_FREQ = {
    "1d": "d", "1wk": "w", "1mo": "m",
    "5m": "5", "15m": "15", "30m": "30", "60m": "60", "1h": "60",
}


class BaostockDataFetcher(DataFetcher):
    """基于 baostock 的行情拉取器（A 股历史 K 线）。"""

    def fetch_data(self, ticker: str, start_date: str, end_date: Optional[str] = None,
                   interval: Interval = Interval.DAY_1) -> pd.DataFrame:
        try:
            data = fetch_data(ticker, start_date, end_date, interval=interval)
            return self._cleaner.dropna(data)
        except Exception as e:
            raise RuntimeError(f"拉取 {ticker} 数据失败: {str(e)}") from e


def to_bs_code(ticker: str) -> str:
    """600000.SH / 000001.SZ → sh.600000 / sz.000001；已是 baostock 格式则原样返回。"""
    s = ticker.strip()
    u = s.upper()
    if u.endswith(".SH"):
        return "sh." + s.split(".")[0]
    if u.endswith(".SZ"):
        return "sz." + s.split(".")[0]
    return s.lower() if s[:3].lower() in ("sh.", "sz.") else s


def fetch_data(ticker: str, start_date: str, end_date: Optional[str] = None,
                interval: Interval = Interval.DAY_1,
                adjust_flag: str = "3", bs=None) -> pd.DataFrame:
    """拉取历史 K 线，返回 Open/High/Low/Close/Volume。end_date 排他（与 yahoo 一致）。

    bs: 已登录的 baostock 模块实例；为 None 时自动 login/logout。
    """
    _owns_session = bs is None
    if _owns_session:
        import baostock as bs  # type: ignore
        bs.login()

    freq = _FREQ.get(interval.value, interval.value)
    # baostock end 为包含，故排他结束日减一天
    end = ""
    if end_date:
        end = (datetime.strptime(end_date.replace("-", "")[:8], "%Y%m%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    fields = "date,time,open,high,low,close,volume" if freq in ("5", "15", "30",
                                                                "60") else "date,open,high,low,close,volume"
    try:
        rs = bs.query_history_k_data_plus(
            to_bs_code(ticker), fields,
            start_date=start_date[:10], end_date=end,
            frequency=freq, adjustflag=str(adjust_flag),
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        raw = pd.DataFrame(rows, columns=rs.fields)
        # 分钟线用 time（YYYYMMDDHHmmssSSS），日线用 date
        idx = (
            pd.to_datetime(raw["time"].str[:14], format="%Y%m%d%H%M%S")
            if "time" in raw.columns else pd.to_datetime(raw["date"])
        )
        return pd.DataFrame(
            {
                "Open": pd.to_numeric(raw["open"]).to_numpy(),
                "High": pd.to_numeric(raw["high"]).to_numpy(),
                "Low": pd.to_numeric(raw["low"]).to_numpy(),
                "Close": pd.to_numeric(raw["close"]).to_numpy(),
                "Volume": pd.to_numeric(raw["volume"]).to_numpy(),
            },
            index=pd.DatetimeIndex(idx),
        ).sort_index()
    finally:
        if _owns_session:
            bs.logout()
