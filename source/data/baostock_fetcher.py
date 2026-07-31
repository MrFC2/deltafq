"""
baostock 历史 K 线适配。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd

from source.data.fetcher import DataFetcher
from source.enums import Interval
from source.core.models import TickerData

# Interval 枚举 → baostock frequency
_FREQ = {
    Interval.DAY_1: "d", Interval.WEEK_1: "w", Interval.MONTH_1: "m",
    Interval.MINUTE_5: "5", Interval.MINUTE_15: "15", Interval.MINUTE_30: "30", Interval.HOUR_1: "60",
}


def to_bs_code(ticker: str) -> str:
    """600000.SH / 000001.SZ → sh.600000 / sz.000001；已是 baostock 格式则原样返回。"""
    s = ticker.strip()
    u = s.upper()
    if u.endswith(".SH"):
        return "sh." + s.split(".")[0]
    if u.endswith(".SZ"):
        return "sz." + s.split(".")[0]
    return s.lower() if s[:3].lower() in ("sh.", "sz.") else s


class BaostockDataFetcher(DataFetcher):
    """基于 baostock 的行情拉取器（A 股历史 K 线）。"""

    def __init__(self, bs=None, **kwargs):
        super().__init__(**kwargs)
        # 外部已登录的 baostock session；None 时每次 fetch 自动 login/logout
        self.bs = bs

    def fetch_data(self,
                   ticker: str,
                   interval: Interval,
                   start_date: str,
                   end_date: Optional[str] = None) -> List[TickerData]:
        """拉取历史 K 线，返回 TickerData 列表。end_date 排他（与 yahoo 一致）。"""
        if self.bs is not None:
            bs = self.bs
            owns_session = False
        else:
            import baostock as bs  # type: ignore
            bs.login()
            owns_session = True

        freq = _FREQ.get(interval, interval.value)
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
                frequency=freq, adjustflag="3",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                return []

            raw = pd.DataFrame(rows, columns=rs.fields)
            # 分钟线用 time（YYYYMMDDHHmmssSSS），日线用 date
            idx = (
                pd.to_datetime(raw["time"].str[:14], format="%Y%m%d%H%M%S")
                if "time" in raw.columns else pd.to_datetime(raw["date"])
            )
            df = self._cleaner.dropna(pd.DataFrame(
                {
                    "Open": pd.to_numeric(raw["open"]).to_numpy(),
                    "High": pd.to_numeric(raw["high"]).to_numpy(),
                    "Low": pd.to_numeric(raw["low"]).to_numpy(),
                    "Close": pd.to_numeric(raw["close"]).to_numpy(),
                    "Volume": pd.to_numeric(raw["volume"]).to_numpy(),
                },
                index=pd.DatetimeIndex(idx),
            ).sort_index())
            return self.df_to_ticker_data(ticker, df)
        except Exception as e:
            raise RuntimeError(f"拉取 {ticker} 数据失败: {str(e)}") from e
        finally:
            if owns_session:
                bs.logout()
