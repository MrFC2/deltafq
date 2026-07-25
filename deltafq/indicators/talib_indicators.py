"""
Technical indicators using TA-Lib library.
"""

import pandas as pd
import talib
from ..core.base import BaseComponent


class TalibIndicators(BaseComponent):
    """基于 TA-Lib 的技术指标计算器。"""
    
    def __init__(self, **kwargs):
        """初始化技术指标计算器。"""
        super().__init__(**kwargs)
        self.logger.info("初始化 TA-Lib 技术指标计算器")
    
    def sma(self, data: pd.Series, period: int) -> pd.Series:
        """计算简单移动均线（SMA）。"""
        self.logger.info(f"计算 SMA(period={period})")
        return pd.Series(talib.SMA(data.values.astype(float), timeperiod=period), index=data.index)
    
    def ema(self, data: pd.Series, period: int) -> pd.Series:
        """计算指数移动均线（EMA）。"""
        self.logger.info(f"计算 EMA(period={period})")
        return pd.Series(talib.EMA(data.values.astype(float), timeperiod=period), index=data.index)
    
    def rsi(self, data: pd.Series, period: int = 14) -> pd.Series:
        """计算相对强弱指数（RSI）。"""
        self.logger.info(f"计算 RSI(period={period})")
        return pd.Series(talib.RSI(data.values.astype(float), timeperiod=period), index=data.index)
    
    def kdj(self, high: pd.Series, low: pd.Series, close: pd.Series, 
            n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
        """计算 KDJ 指标。"""
        self.logger.info(f"计算 KDJ(n={n}, m1={m1}, m2={m2})")
        k, d = talib.STOCH(high.values.astype(float), low.values.astype(float), close.values.astype(float),
                           fastk_period=n, slowk_period=m1, slowd_period=m2)
        return pd.DataFrame({
            'k': pd.Series(k, index=close.index),
            'd': pd.Series(d, index=close.index),
            'j': pd.Series(3 * k - 2 * d, index=close.index)
        })
    
    def boll(self, data: pd.Series, period: int = 20, std_dev: float = 2) -> pd.DataFrame:
        """计算布林带（BOLL）。"""
        self.logger.info(f"计算 BOLL(period={period}, std_dev={std_dev})")
        upper, middle, lower = talib.BBANDS(data.values.astype(float), timeperiod=period, 
                                            nbdevup=std_dev, nbdevdn=std_dev, matype=0)
        return pd.DataFrame({
            'upper': pd.Series(upper, index=data.index),
            'middle': pd.Series(middle, index=data.index),
            'lower': pd.Series(lower, index=data.index)
        })
    
    # 与 TechnicalIndicators 接口对齐，统一使用 boll()
    
    def atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """计算平均真实波幅（ATR）。"""
        self.logger.info(f"计算 ATR(period={period})")
        return pd.Series(talib.ATR(high.values.astype(float), low.values.astype(float), 
                                   close.values.astype(float), timeperiod=period), index=close.index)
    
    def obv(self, close: pd.Series, volume: pd.Series) -> pd.Series:
        """计算能量潮（OBV）。"""
        self.logger.info("计算 OBV")
        return pd.Series(talib.OBV(close.values.astype(float), volume.values.astype(float)), index=close.index)
