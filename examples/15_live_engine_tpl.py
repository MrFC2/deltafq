"""Minimal LiveEngine demo."""

import sys
import os
import time

from source.adapters.data import BaostockDataGateway

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pandas as pd
from source.live import LiveEngine
from source.adapters.trade.paper_gateway import PaperTradeGateway
from source.strategy.base import BaseStrategy
from source.enums import Period
from source.core.models import SignalData, TickerData
from source.enums import Signal
from typing import List


class Every2BarFlipStrategy(BaseStrategy):
    """Every 2 strategy runs flip signal 1/-1 for quick verification."""

    def __init__(self, **kwargs):
        super().__init__(period=Period.MINUTE_1, **kwargs)
        self._run_count = 0

    def generate_signals(self, data: List[TickerData], cash=None, position=None, commission=None) -> List[SignalData]:
        self._run_count += 1
        sig = Signal.BUY if (self._run_count // 2) % 2 == 0 else Signal.SELL
        return [SignalData(timestamp=t.timestamp, signal=sig) for t in data]


def main():
    engine = LiveEngine(
        ticker="BTC-USD",
        data_gateway=BaostockDataGateway(interval=10.0),
        trade_gateway=PaperTradeGateway(initial_capital=1_000_000),
        strategy=Every2BarFlipStrategy(name="Every2Flip"),
        strategy_input_size=50,
    )
    engine.run()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()

    def _fmt_dt_cols(df):
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].apply(lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(x) else "")
        return df

    def _print_section(title, body):
        print(f"\n{'='*60}\n{title}\n{'='*60}\n{body}")

    # 1. Trades
    df_t = engine.get_trades_df()
    df_t = _fmt_dt_cols(df_t.copy())
    _print_section("Trades", df_t.to_string(float_format="%.2f"))

    # 2. Orders
    eng = engine.trade_gateway._engine if engine.trade_gateway else None
    orders = eng.order_manager.get_order_history() if eng else []
    df_o = _fmt_dt_cols(pd.DataFrame(orders))
    _print_section("Orders", df_o.to_string(float_format="%.2f"))

    # 3. Values (equity curve)
    values_metrics, metrics = engine.calculate_metrics()
    df_v = values_metrics.copy()
    if not df_v.empty and "date" not in df_v.columns:
        df_v = df_v.reset_index()
    df_v = _fmt_dt_cols(df_v)
    _print_section("Values", df_v.to_string(float_format="%.2f"))

    # 4. Metrics (summary)
    lines = [f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}" for k, v in metrics.items()]
    _print_section("Metrics", "\n".join(lines))

    # plot K-line & signal (Plotly)
    # chart = engine.get_chart_data()
    # if chart["candles"]:
    #     import plotly.graph_objects as go
    #     from plotly.subplots import make_subplots
    #     df = pd.DataFrame(chart["candles"]).set_index("date")
    #     df.index = pd.to_datetime(df.index)
    #     sig = pd.Series(chart["signals"], index=df.index)
    #     fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
    #                         specs=[[{"type": "candlestick"}], [{"type": "scatter"}]])
    #     fig.add_trace(go.Candlestick(x=df.index, open=df.open, high=df.high, low=df.low, close=df.close), row=1, col=1)
    #     fig.add_trace(go.Scatter(x=sig.index, y=sig.values, mode="lines", name="Signal", line=dict(dash="dot")), row=2, col=1)
    #     fig.update_layout(template="plotly_white")
    #     fig.show()


if __name__ == "__main__":
    main()
