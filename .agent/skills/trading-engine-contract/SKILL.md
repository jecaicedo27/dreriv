---
name: trading-engine-contract
description: Contract and requirements for creating new trading analysis engines. Use when building a new engine to ensure it integrates correctly with TradingCore, replay_bot, engine battles, trade persistence, and the live trading bot.
---

# Trading Engine Contract

Every trading engine must fulfill this contract to work with the full system: TradingCore, replay_bot simulations, engine battles, trade-level database persistence, and the live trading bot.

> [!IMPORTANT]
> **Architecture Rule:** `engine_registry.py` is the SINGLE SOURCE OF TRUTH for all engine parameters (hurst, slope, cooldown, duration, defensive filters). When MODIFYING an existing engine's config, change ONLY `engine_registry.py` — never bot.py, replay_bot.py, or simulation_api.py. See workflow `/engine-config-changes` for the full modification guide.

---

## 1. Extend `BaseAnalysisEngine`

File: `backend/app/analysis/base_engine.py`

```python
from app.analysis.base_engine import BaseAnalysisEngine

class MyNewEngine(BaseAnalysisEngine):
    name = "my_engine_v5"
    version = "5.0"
    description = "Short description of strategy"

    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        # kwargs includes: hurst_min, hurst_max
        ...
```

---

## 2. Required Return Dict from `analyze()`

The `analyze()` method **MUST** return a dict with ALL of these keys:

```python
return {
    # === REQUIRED: Core signal ===
    "signal": "CALL" | "PUT" | "HOLD",          # Trading direction
    "final_signal": "CALL" | "PUT" | "HOLD",    # Same as signal (used by TradingCore)
    "confidence": 0.0 - 1.0,                     # Signal strength
    "final_confidence": 0.0 - 1.0,               # Same as confidence
    "contract_type": "CALL" | "PUT" | None,       # For Deriv API
    "stake_multiplier": 1.0,                      # GARCH-adjusted multiplier
    "duration": 300,                              # Trade duration in seconds
    "reasoning": "EMA21>EMA50 | RSI=62 | ...",    # Human-readable reasoning string

    # === REQUIRED: Hurst signal ===
    "hurst_signal": {"hurst": 0.6500, "regime": "TRENDING"},

    # === REQUIRED: Technical indicators (for DB persistence) ===
    "indicators": {
        "rsi_14": 62.5,              # RSI(14) value
        "ema_21": 4502.33,           # EMA 21 value
        "ema_50": 4498.10,           # EMA 50 value (if available)
        "macd_histogram": 0.0023,    # MACD histogram value
        "bb_width": 0.00812,         # Bollinger Band width ratio
        "momentum_5": 0.003,         # 5-period momentum (if available)
    },
}
```

> [!CAUTION]
> If `indicators` is missing, trades from this engine will have NULL indicator columns in `engine_battle_trades`, making analysis impossible.

> [!IMPORTANT]
> Both `signal`/`final_signal` and `confidence`/`final_confidence` must be present. `TradingCore` reads `final_signal` and `final_confidence`, while some code paths read `signal` and `confidence`.

---

## 3. HOLD Response

When the engine decides NOT to trade, return a HOLD dict. **Must still include all required keys:**

```python
def _hold_response(self, reasoning: list) -> Dict[str, Any]:
    return {
        "signal": "HOLD",
        "final_signal": "HOLD",
        "confidence": 0.0,
        "final_confidence": 0.0,
        "contract_type": None,
        "stake_multiplier": 1.0,
        "duration": 300,
        "reasoning": " | ".join(reasoning),
        "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
        "indicators": {},  # Empty dict, NOT missing
    }
```

---

## 4. Register in Engine Registry

File: `backend/app/analysis/engine_registry.py`

Add entry to `_ENGINES` dict:

```python
"my_engine_v5": {
    "module": "app.analysis.my_engine",
    "class": "MyNewEngine",
    "description": "Short description for UI",
    "version": "5.0",
    "hurst_min": 0.6,       # Default Hurst range
    "hurst_max": 0.7,
    "blocked_hours": [],     # Hours to skip (Colombia time 0-23)
    "defensive": {**_DEFAULT_DEFENSIVE},  # Risk management defaults
},
```

---

## 5. How the Engine is Called

`TradingCore.analyze_async()` in `backend/app/simulation/trading_core.py` orchestrates everything:

```
1. TradingCore receives engine + DataFrame (last 250 candles)
2. Calls engine.analyze(window, symbol, hurst_min=..., hurst_max=...)
3. Reads signal["final_signal"], signal["final_confidence"]
4. Reads signal["hurst_signal"]["hurst"]
5. Reads signal["indicators"] → passes to trade object
6. Optionally passes to AI Layer 2 (Groq/OpenAI/Claude)
7. Returns enriched result to replay_bot
```

---

## 6. Data Flow: Engine → Database

The full persistence chain:

```
Engine.analyze()
  → signal dict (with indicators)
    → TradingCore.analyze_async() extracts indicators
      → replay_bot.py builds trade object (includes indicators)
        → _run_engine_sim() collects all trades
          → _run_engine_battle_coordinator() batch INSERTs to DB
```

**Database table: `engine_battle_trades`**

| Column           | Source                          |
|------------------|---------------------------------|
| `battle_id`      | Auto-generated UUID             |
| `engine_name`    | Engine registry key             |
| `trade_date`     | Simulation date                 |
| `trade_time`     | Candle open_time - 5h (COL)     |
| `direction`      | `result["action"]` (CALL/PUT)   |
| `stake`          | Kelly-sized stake               |
| `entry_price`    | Candle close at entry           |
| `exit_price`     | Candle close at exit            |
| `result`         | WIN / LOSS                      |
| `pnl`            | Profit/loss in USD              |
| `confidence`     | Final confidence 0-1            |
| `l1_signal`      | Layer 1 raw signal              |
| `l1_confidence`  | Layer 1 raw confidence          |
| `hurst`          | From `signal["hurst_signal"]`   |
| `rsi_14`         | From `signal["indicators"]`     |
| `ema_9`          | From `signal["indicators"]`     |
| `ema_21`         | From `signal["indicators"]`     |
| `macd_histogram` | From `signal["indicators"]`     |
| `bb_width`       | From `signal["indicators"]`     |
| `reasoning`      | First 500 chars of reasoning    |

---

## 7. DataFrame Columns Available

The DataFrame passed to `analyze()` has these columns from the `candles` table:

```
open, high, low, close, volume, open_time, close_time,
ema_9, ema_21, ema_50, rsi_14, atr_14,
bollinger_upper, bollinger_middle, bollinger_lower,
macd, macd_signal, macd_histogram,
returns, log_returns, momentum_5, momentum_10,
volatility_realized, volume_delta, price_position,
is_order_block, ob_type, is_fvg, fvg_type, bos, choch,
hurst_exponent, hurst_fast, ou_deviation, garch_volatility_forecast, regime
```

> [!IMPORTANT]
> **Engines should READ pre-computed indicators from the DataFrame**, NOT calculate them internally.
> The `safe_analyze()` layer (in `BaseAnalysisEngine`) validates data quality automatically—
> if an indicator is NULL, it computes it on-the-fly as a safety net. But the PRIMARY source
> must be the pre-computed data pipeline.
>
> **To add a NEW indicator to the system:**
>
> 1. Add the column to the `candles` table (`ALTER TABLE candles ADD COLUMN ...`)
> 2. Add the column to the SQLAlchemy model (`backend/app/models/models.py`)
> 3. Add calculation to `TechnicalIndicators.calculate_all()` (`backend/app/analysis/indicators.py`)
> 4. Add assignment in `DataCollector._calculate_indicators()` (`backend/app/services/data_collector.py`)
>    — this ensures NEW candles arriving via the feeder get the indicator computed
> 5. Add to `REQUIRED_INDICATORS` or `DESIRED_INDICATORS` in `BaseAnalysisEngine` (`base_engine.py`)
>    — this ensures `safe_analyze()` validates it
> 6. Run a backfill script for historical candles that don't have it yet
> 7. Read it from the DataFrame in the engine — do NOT add calculation logic inside the engine
>
> **Indicator Pipeline Flow:**
> ```
> Deriv WS → Feeder → DataCollector._finalize_candle()
>                           ↓
>                   _calculate_indicators()     ← Computes ALL indicators
>                           ↓
>                      Saved to DB (candles table)
>                           ↓
>                   Bot/Sim reads from DB → TradingCore → safe_analyze() → engine.analyze()
>                                                              ↑
>                                                    Validates data quality,
>                                                    computes missing on-the-fly
> ```
>
> This ensures consistency across all engines, simulations, and live mode.

---

## 8. Live Bot Integration

File: `backend/app/bot.py`

The live `TradingBot` loads engines via `settings.ENGINE_NAME` (set in `.env`):

```python
# bot.py __init__
self.signal_engine = get_engine(settings.ENGINE_NAME)   # Instantiates engine
self.engine_config = get_engine_config(settings.ENGINE_NAME)  # Loads full config
```

### What the live bot reads from engine config:

| Config Key | Used For |
|---|---|
| `hurst_min` / `hurst_max` | Passed to `TradingCore.analyze_async()` → then to `engine.analyze(**kwargs)` |
| `blocked_hours` | Bot skips analysis during these hours (Colombia time, UTC-5) |
| `defensive` | WR monitor, global streak, direction cooldown, ATR gate settings |

### Live trade execution flow:

```
1. New 1m candle arrives via WebSocket
2. Cooldown / blocked-hour / ATR gate checks
3. TradingCore.analyze_async(engine, df, symbol, hurst_min, hurst_max)
     → Calls engine.safe_analyze() (validates indicators, computes if missing)
     → Then engine.analyze() processes clean data
4. If CALL/PUT with confidence >= 0.60:
     → Build trade_signal dict
     → TradeExecutor.execute_trade(trade_signal, balance)
     → Trade placed on Deriv via WebSocket API
5. Save AnalysisHistory to DB (hurst, ou_dev, rsi, ema, signal)
6. Update latest candle row with hurst/ou/regime values
```

### trade_signal dict (passed to TradeExecutor):

```python
trade_signal = {
    "symbol": "R_100",
    "contract_type": "CALL",         # From result["action"]
    "decision": "CALL",
    "final_signal": "CALL",
    "confidence": 0.82,
    "final_confidence": 0.82,
    "current_price": 4502.33,
    "suggested_stake_multiplier": 1.0,
    "duration": 300,
    "reasoning": "EMA21>EMA50 | RSI=62 | ...",
    "hurst_signal": {"hurst": 0.65},
    "engine_name": "university_v2",   # From settings.ENGINE_NAME
}
```

### Switching the live bot to a new engine:

1. Set `ENGINE_NAME=my_engine_v5` in `.env`
2. Restart: `docker restart deriv-backend`
3. Bot logs will show: `🔧 Live bot engine: my_engine_v5`

> [!IMPORTANT]
> The live bot reads ALL config from the engine registry entry (`_ENGINES` dict). This includes hurst range, blocked hours, and defensive filter presets. Make sure your engine's registry entry has correct values for live trading.

---

## 9. Checklist for New Engine

### Engine Code
- [ ] Extends `BaseAnalysisEngine`
- [ ] Implements `analyze(df, symbol, **kwargs)` with correct return dict
- [ ] Returns `final_signal` and `final_confidence` (not just `signal`/`confidence`)
- [ ] Returns `hurst_signal` dict with `hurst` key
- [ ] Returns `indicators` dict with at least: `rsi_14`, `ema_21`, `macd_histogram`, `bb_width`
- [ ] Has `_hold_response()` that returns complete dict with `indicators: {}`
- [ ] Engine is **stateless** — `analyze()` is pure function, no internal state between calls
- [ ] Reasoning string uses `" | "` separator for readability
- [ ] Does NOT calculate indicators internally — reads pre-computed from DataFrame

### New Indicators (if engine needs indicators not yet in the pipeline)
- [ ] Column added to `candles` table (SQL migration)
- [ ] Column added to SQLAlchemy model (`app/models/models.py`)
- [ ] Calculation added to `TechnicalIndicators.calculate_all()` (`app/analysis/indicators.py`)
- [ ] Assignment added to `DataCollector._calculate_indicators()` (`app/services/data_collector.py`)
- [ ] Added to `REQUIRED_INDICATORS` or `DESIRED_INDICATORS` in `BaseAnalysisEngine` (`base_engine.py`)
- [ ] Backfill script created/updated for historical data

### Registration & UI
- [ ] Registered in `engine_registry.py` `_ENGINES` dict with all fields
- [ ] Registry entry has correct `hurst_min/max`, `blocked_hours`, and `defensive` config
- [ ] Added to **dashboard.html** engine selector dropdown
- [ ] Added to **simulations.html** in ALL locations:
  - [ ] Top engine `<select>` (id=`engineSelect`)
  - [ ] Multi-day engine `<select>` (id=`multiEngineSelect`)
  - [ ] `engineNames` map (for hour filter label)
  - [ ] `engineIcons` map (for battle history display)
  - [ ] Engine color map (for equity curve chart)

### Deployment
- [ ] Works with live bot: set `ENGINE_NAME` in `.env` to switch
- [ ] Backend restarted after adding: `docker restart deriv-backend`

