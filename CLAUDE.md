# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

```bash
# Activate venv before any command
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt

# Install in editable mode (for development)
pip install -e .

# Lint
flake8 deltafq/

# Format
black deltafq/
```

No test suite is configured. Run examples directly to verify behavior:

```bash
python examples/04_backtest_execution.py
python examples/15_live_engine_tpl.py
```

## Architecture

DeltaFQ is a three-layer quantitative trading framework: **Research → Backtest → Live**.

### Data flow

```
DataFetcher (data/fetcher.py)
  ├── source="yahoo"     → yfinance
  ├── source="baostock"  → adapters/data/baostock_bars.py
  └── source="miniqmt"   → adapters/data/miniqmt_bars.py
       ↓
DataCleaner (data/cleaner.py)   # dropna, normalize columns
       ↓
strategy.generate_signals(df)   # returns pd.Series of {-1, 0, 1}
```

### Backtest path

`BacktestEngine` (`backtest/engine.py`) is abstract — subclass it and implement `generate_signals`. Typical usage:

```python
engine.set_parameters(symbol, start, end)
engine.load_data()
engine.add_strategy(MyStrategy())  # calls strategy.run() internally
engine.run()
engine.print_report()
```

Execution replay lives in `trader/engine.py` (`ExecutionEngine`), which delegates to `order_manager.py` and `position_manager.py`.

### Live path

`LiveEngine` (`live/engine.py`) wires together:
- **DataGateway** → pushes `TickData` into `EventEngine`
- **EventEngine** (`live/event_engine.py`) → dispatches `EVENT_TICK` to two handlers
  - `_on_tick_match` — forwards tick to paper execution engine for limit-order matching
  - `_on_tick_strategy` — re-fetches K-line bars at `_REFETCH_SEC` intervals, calls `strategy.generate_signals()`, then handles signal transitions (cancel pending → send limit order)

Gateways are registered in `live/gateway_registry.py`:
- Data: `yfinance`, `baostock`, `miniqmt`
- Trade: `paper`, `miniqmt`

### Strategy contract

Subclass `BaseStrategy` (`strategy/base.py`) and implement one method:

```python
def generate_signals(self, data: pd.DataFrame) -> pd.Series:
    # return Series of {-1, 0, 1} indexed by date
```

Optional attributes on the strategy instance control position sizing:
- `order_quantity` (int) — max shares per trade, applies to both buy and sell
- `order_amount` (float) — max spend per buy (sell uses full position when not set)

### Adding a new data/trade gateway

1. Implement `DataGateway` or `TradeGateway` abstract class (`live/gateways.py`)
2. Register it in `live/gateway_registry.py` under `DATA_GATEWAYS` or `TRADE_GATEWAYS`
3. If the gateway also serves historical bars for `DataFetcher`, add a source mapping in `data/source_map.py`

### Key design notes

- `BacktestEngine` is abstract (`ABC`) — it cannot be instantiated directly; always subclass it.
- `LiveEngine` lazily creates gateways on `run_live()` via `_ensure_gateways()`; calling `set_data_gateway()` or `set_trade_gateway()` after construction clears the cached instance.
- miniQMT requires a running QMT terminal on Windows; it cannot be used on macOS/Linux.
- `baostock` gateway polls at 5-minute intervals and is the recommended A-share data source when miniQMT is unavailable.
