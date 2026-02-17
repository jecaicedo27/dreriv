# Simulation Sandbox - Quick Start Guide

## What is it?

A **completely isolated** testing environment where you can:
- Test new trading strategies on 6 months of historical data
- Compare multiple strategies side-by-side
- Validate improvements before deploying to live bot
- **Zero risk** - doesn't touch production bot or live candles

---

## Architecture

```
PRODUCTION (Untouched)          SIMULATION (Isolated)
├─ candles (live feed)          ├─ historical_candles (6 months)
├─ trades (real money)          ├─ simulation_runs (metadata)
├─ bot_state (live)             └─ simulation_trades (test results)
```

---

## Quick Start

### 1. Download Historical Data (One-Time)

```bash
# Download 6 months of R_100 candles (~259k candles)
docker exec deriv-backend python /app/download_historical_data.py 6

# Or download 3 months for faster testing
docker exec deriv-backend python /app/download_historical_data.py 3
```

**Expected:** ~15-20 minutes for 6 months

---

### 2. Run Your First Simulation

```bash
# Test current bot strategy on last 3 months
docker exec deriv-backend python /app/simulate.py \
  --strategy CurrentBotStrategy \
  --months 3 \
  --name "baseline-3m"
```

**Output:**
```
🎉 SIMULATION COMPLETE
Strategy: CurrentBotStrategy
Period: 2025-11-01 → 2026-02-01

📊 RESULTS:
  Initial Balance:  $10,000.00
  Final Balance:    $12,450.00
  Total P&L:        +$2,450.00
  Total Trades:     145
  Winning Trades:   82
  Losing Trades:    63
  Win Rate:         56.6%
  Max Drawdown:     12.3%
```

---

### 3. Create Custom Strategy

```python
# backend/app/simulation/strategies/my_strategy.py

from app.simulation.strategy import Strategy
import pandas as pd

class MyAggressiveStrategy(Strategy):
    
    async def analyze(self, current_candle, history):
        # Your custom logic here
        rsi = current_candle.get('rsi_14')
        
        if rsi < 25:  # More aggressive than current bot (30)
            return {
                'signal': 'CALL',
                'confidence': 0.8,
                'stake': 80.0,  # Higher stake
                'reasoning': 'Extreme oversold'
            }
        elif rsi > 75:
            return {
                'signal': 'PUT',
                'confidence': 0.8,
                'stake': 80.0,
                'reasoning': 'Extreme overbought'
            }
        
        return {'signal': 'HOLD', 'confidence': 0.0}
```

Then register in `simulate.py`:

```python
from app.simulation.strategies.my_strategy import MyAggressiveStrategy

STRATEGIES = {
    'CurrentBotStrategy': CurrentBotStrategy,
    'MyAggressiveStrategy': MyAggressiveStrategy,  # Add this
}
```

Run it:
```bash
docker exec deriv-backend python /app/simulate.py \
  --strategy MyAggressiveStrategy \
  --months 3 \
  --name "aggressive-test"
```

---

## CLI Options

```bash
# Date range
--start YYYY-MM-DD      # Start date
--end YYYY-MM-DD        # End date
--months N              # Last N months from now

# Strategy
--strategy NAME         # Strategy class name (required)
--name TEXT             # Simulation run name

# Config
--balance FLOAT         # Initial balance (default: 10000)
--stake FLOAT           # Stake per trade (default: 60)
--min-confidence FLOAT  # Min confidence (default: 0.70)
```

---

## View Results

```bash
# List all simulation runs
docker exec -e PGPASSWORD='DerIv_B0t_2026_Secure!Pass' deriv-postgres psql -U deriv_bot -d deriv_bot -c "
SELECT id, name, strategy_name, total_trades, win_rate, total_pnl, max_drawdown_pct
FROM simulation_runs
ORDER BY id DESC
LIMIT 10;
"

# View trades from specific run
docker exec -e PGPASSWORD='DerIv_B0t_2026_Secure!Pass' deriv-postgres psql -U deriv_bot -d deriv_bot -c "
SELECT entry_time, direction, outcome, profit_loss, confidence
FROM simulation_trades
WHERE run_id = 1
ORDER BY entry_time DESC
LIMIT 20;
"
```

---

## Safety Guarantees

✅ **Isolated:** Never touches `candles`, `trades`, or `bot_state`  
✅ **Safe:** No real Deriv trades executed  
✅ **Fast:** Run months of backtests in minutes  
✅ **Reproducible:** Same data = same results

---

## Next Steps

1. Download 6 months historical data
2. Run baseline simulation (CurrentBotStrategy)
3. Create custom strategy
4. Compare results
5. If simulation wins → deploy to live bot!
