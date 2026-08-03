"""信号生成与合并工具。"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from ..core.base import BaseComponent
from ..enums import CombineMethod


class SignalGenerator(BaseComponent):
    """从预计算指标生成交易信号，并支持多信号合并。"""

    def __init__(self, **kwargs):
        """初始化信号生成器。"""
        super().__init__(**kwargs)

    def _log_signal_counts(self, label: str, series: pd.Series) -> None:
        """记录买入、卖出、持平信号数量。"""
        buy = int((series == 1).sum())
        sell = int((series == -1).sum())
        flat = int((series == 0).sum())

    # --- SMA -----------------------------------------------------------------
    def sma_signals(self, fast_ma: pd.Series, slow_ma: pd.Series) -> pd.Series:
        """快线在慢线上方为多头，下方为空头。"""
        if not fast_ma.index.equals(slow_ma.index):
            slow_ma = slow_ma.reindex(fast_ma.index)
        signals = pd.Series(
            np.where(fast_ma > slow_ma, 1, np.where(fast_ma < slow_ma, -1, 0)),
            index=fast_ma.index,
            dtype=int,
        )
        self._log_signal_counts("SMA crossover", signals)
        return signals

    # --- EMA -----------------------------------------------------------------
    def ema_signals(self, price: pd.Series, ema: pd.Series) -> pd.Series:
        """价格在 EMA 上方为多头，下方为空头。"""
        if not price.index.equals(ema.index):
            ema = ema.reindex(price.index)
        signals = pd.Series(
            np.where(price > ema, 1, np.where(price < ema, -1, 0)),
            index=price.index,
            dtype=int,
        )
        self._log_signal_counts("EMA price-vs-ema", signals)
        return signals

    # --- RSI -----------------------------------------------------------------
    def rsi_signals(self, rsi: pd.Series, oversold: float = 30, overbought: float = 70) -> pd.Series:
        """RSI 低于超卖线买入，高于超买线卖出。"""
        signals = pd.Series(
            np.where(rsi < oversold, 1, np.where(rsi > overbought, -1, 0)),
            index=rsi.index,
            dtype=int,
        )
        self._log_signal_counts("RSI", signals)
        return signals

    # --- KDJ -----------------------------------------------------------------
    def kdj_signals(self, kdj: pd.DataFrame) -> pd.Series:
        """K 上穿 D 为多头，下穿为空头。"""
        for col in ("k", "d"):
            if col not in kdj:
                raise ValueError("kdj 必须包含 k 和 d 列")
        signals = pd.Series(
            np.where(kdj["k"] > kdj["d"], 1, np.where(kdj["k"] < kdj["d"], -1, 0)),
            index=kdj.index,
            dtype=int,
        )
        self._log_signal_counts("KDJ K>D", signals)
        return signals

    # --- BOLL ----------------------------------------------------------------
    def boll_signals(self, price: pd.Series, bands: pd.DataFrame, method: str = "cross") -> pd.Series:
        """触及或穿越布林带外轨触发信号。"""
        if method not in ["touch", "cross", "cross_current"]:
            raise ValueError("无效的 method 参数")
        if not all(col in bands for col in ("upper", "middle", "lower")):
            raise ValueError("bands 缺少必要列")

        signals = pd.Series(0, index=price.index, dtype=int)

        if method == "touch":
            buy_condition = price <= bands["lower"]
            sell_condition = price >= bands["upper"]
            signals = np.where(buy_condition, 1, np.where(sell_condition, -1, 0))

        elif method == "cross":
            prev_price = price.shift(1)
            prev_bands = bands.shift(1)
            buy_condition = (prev_price <= prev_bands["lower"]) & (price >= bands["lower"])
            sell_condition = (prev_price >= prev_bands["upper"]) & (price <= bands["upper"])
            signals = np.where(buy_condition, 1, np.where(sell_condition, -1, 0))

        elif method == "cross_current":
            prev_price = price.shift(1)
            buy_condition = (prev_price <= bands["lower"]) & (price >= bands["lower"])
            sell_condition = (prev_price >= bands["upper"]) & (price <= bands["upper"])
            signals = np.where(buy_condition, 1, np.where(sell_condition, -1, 0))

        series = pd.Series(signals, index=price.index, dtype=int)
        self._log_signal_counts(f"Boll ({method})", series)
        return series

    # --- OBV -----------------------------------------------------------------
    def obv_signals(self, obv: pd.Series) -> pd.Series:
        """OBV 斜率为正为买压，为负为卖压。"""
        obv_change = obv.diff().fillna(0)
        signals = pd.Series(
            np.where(obv_change > 0, 1, np.where(obv_change < 0, -1, 0)),
            index=obv.index,
            dtype=int,
        )
        self._log_signal_counts("OBV slope", signals)
        return signals

    def combine_signals(
            self,
            signals_dict: Dict[str, pd.Series],
            method: CombineMethod = CombineMethod.VOTE,
            weights: Optional[Dict[str, float]] = None,
            threshold: float = 0.33,
    ) -> pd.Series:
        """合并多个 {-1,0,1} 信号序列，支持 vote / weighted 两种方式。

        - VOTE:     多数投票，买票 > 卖票取 1，卖票 > 买票取 -1，否则 0。
        - WEIGHTED: 加权求和，结果 >= threshold 取 1，<= -threshold 取 -1，否则 0。
                    weights 为 None 时各信号等权；threshold 默认 0.33。
        """
        if not signals_dict:
            raise ValueError("signals_dict 不能为空")

        names = list(signals_dict.keys())
        index = signals_dict[names[0]].index
        aligned = {}
        for name, sig in signals_dict.items():
            if len(sig) != len(signals_dict[names[0]]):
                raise ValueError(f"信号 '{name}' 长度不一致")
            aligned[name] = sig.reindex(index) if not sig.index.equals(index) else sig

        signals_df = pd.DataFrame(aligned)

        if method == CombineMethod.VOTE:
            buy_votes = (signals_df == 1).sum(axis=1)
            sell_votes = (signals_df == -1).sum(axis=1)
            combined = np.where(buy_votes > sell_votes, 1,
                                np.where(sell_votes > buy_votes, -1, 0))

        elif method == CombineMethod.WEIGHTED:
            if weights is None:
                w = {n: 1.0 / len(names) for n in names}
            else:
                total = sum(weights.values())
                if total == 0:
                    raise ValueError("权重之和不能为零")
                w = {k: v / total for k, v in weights.items()}

            weighted_sum = sum(signals_df[n] * w.get(n, 0) for n in names)
            combined = np.where(weighted_sum >= threshold, 1,
                                np.where(weighted_sum <= -threshold, -1, 0))

        else:
            raise ValueError(f"无效的 method: {method}，可选 CombineMethod.VOTE / CombineMethod.WEIGHTED")

        result = pd.Series(combined, index=index, dtype=int)
        self._log_signal_counts(f"Combined ({method.value})", result)
        return result
