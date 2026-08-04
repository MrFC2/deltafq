"""
LiveEngine 示例：baostock 回放 + 纸面交易。

用法：
    source .venv/bin/activate
    python examples/22_baostock_live_engine.py
"""
import time

import pandas as pd
from typing import List

from quant.live import LiveEngine
from quant.gateway.data import BaostockDataGateway
from quant.gateway.trade.paper_gateway import PaperTradeGateway
from quant.strategy.base import BaseStrategy
from quant.core.models import SignalData, TickerData
from quant.enums import Period, Signal


class MaStrategy(BaseStrategy):
    """双均线策略：短均线上穿长均线买入，下穿卖出。"""

    def __init__(self, short: int = 5, long: int = 20, **kwargs):
        super().__init__(period=Period.MINUTE_5, data_size=long + 1, **kwargs)
        self.short = short
        self.long = long

    def generate_signals(self, data: List[TickerData], cash=None, position=None, commission=None) -> List[SignalData]:
        if len(data) < self.long:
            return [SignalData(timestamp=t.timestamp, signal=Signal.HOLD) for t in data]

        closes = [t.price for t in data]
        signals = []
        for i, t in enumerate(data):
            if i < self.long - 1:
                signals.append(SignalData(timestamp=t.timestamp, signal=Signal.HOLD))
                continue
            ma_short = sum(closes[i - self.short + 1: i + 1]) / self.short
            ma_long = sum(closes[i - self.long + 1: i + 1]) / self.long
            if ma_short > ma_long:
                sig = Signal.BUY
            elif ma_short < ma_long:
                sig = Signal.SELL
            else:
                sig = Signal.HOLD

            # 最新信号携带下单数量
            quantity = None
            if i == len(data) - 1 and cash and sig == Signal.BUY:
                quantity = int(cash * 0.9 // (t.price * 100)) * 100
            signals.append(SignalData(timestamp=t.timestamp, signal=sig, quantity=quantity))

        return signals


TICKERS = {
    "600519.SH": MaStrategy(name="ma_600519"),
    "000001.SZ": MaStrategy(name="ma_000001"),
}


def _fmt_dt_cols(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].apply(lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(x) else "")
    return df


def _print_section(title: str, body: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}\n{body}")


def main():
    engine = LiveEngine(
        ticker_strategies=TICKERS,
        data_gateway=BaostockDataGateway(),
        trade_gateway=PaperTradeGateway(initial_capital=1_000_000),
    )
    engine.run()
    print("LiveEngine 启动，Ctrl+C 停止回放并打印报告...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
        print("\n已停止。")

    # 成交记录
    df_t = _fmt_dt_cols(engine.get_trades_df())
    _print_section("Trades", df_t.to_string(float_format="%.2f") if not df_t.empty else "（暂无成交）")

    # 各标的绩效
    for ticker in TICKERS:
        values_df, metrics = engine.calculate_metrics(ticker)
        if values_df.empty:
            _print_section(f"Metrics [{ticker}]", "（数据不足，无法计算）")
            continue
        lines = [f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}" for k, v in metrics.items()]
        _print_section(f"Metrics [{ticker}]", "\n".join(lines))


if __name__ == "__main__":
    main()
