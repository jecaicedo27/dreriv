---
name: trading-risk-management
description: "Risk management for automated trading bots. Use when implementing Kelly Criterion position sizing, progressive drawdown recovery, correlation limits between instruments, daily loss limits, cooldown periods after consecutive losses, A/B testing frameworks for strategy comparison, or any capital preservation logic in a trading system."
---

# Trading Risk Management

## Overview

Comprehensive risk management layer for automated trading. Implements fractional Kelly Criterion for dynamic position sizing, progressive drawdown recovery, instrument correlation limits, and A/B testing to measure strategy effectiveness. These are the non-negotiable guardrails that protect capital.

## When to Use This Skill

- Calculating trade size based on edge (Kelly Criterion)
- Implementing daily/weekly/total loss limits
- Building cooldown logic after consecutive losses
- Preventing correlated overexposure
- Progressive drawdown recovery (reduce size as losses mount)
- A/B testing different strategy configurations

## Core Principle

**Risk management rules are HARDCODED and cannot be overridden by any AI/LLM decision.** The AI suggests trades; risk management has absolute veto power.

## Fractional Kelly Criterion

```python
def kelly_stake(win_prob: float, win_loss_ratio: float, balance: float,
                fraction: float = 0.25, max_pct: float = 0.02) -> dict:
    """
    Calculate optimal stake using fractional Kelly.
    
    Args:
        win_prob: Estimated probability of winning (0-1)
        win_loss_ratio: Average win / average loss
        balance: Current account balance
        fraction: Kelly fraction (0.25 = quarter Kelly, conservative)
        max_pct: Maximum percentage of balance (hard cap)
    
    Returns:
        Dict with stake amount and metadata
    """
    if win_prob <= 0 or win_loss_ratio <= 0:
        return {"stake": 0, "kelly_pct": 0, "reason": "no_edge"}
    
    q = 1 - win_prob
    
    # Kelly formula: f* = (p*b - q) / b
    kelly_full = (win_prob * win_loss_ratio - q) / win_loss_ratio
    
    if kelly_full <= 0:
        return {"stake": 0, "kelly_pct": 0, "reason": "negative_edge"}
    
    # Apply fraction and cap
    kelly_adjusted = min(kelly_full * fraction, max_pct)
    stake = balance * kelly_adjusted
    
    return {
        "stake": round(stake, 2),
        "kelly_full_pct": round(kelly_full * 100, 2),
        "kelly_adjusted_pct": round(kelly_adjusted * 100, 2),
        "fraction_used": fraction,
        "balance": balance
    }
```

### Kelly Fraction Guidelines
| Situation | Fraction | Rationale |
|-----------|----------|-----------|
| Normal operation | 0.25 | Conservative, proven optimal for noisy estimates |
| High confidence (3/3 layers agree) | 0.35 | Slightly more aggressive when all signals align |
| Groq meta-confidence < 50% | 0.15 | Reduce when AI is underperforming |
| Drawdown > 10% | 0.15 | Capital preservation mode |
| First 2 weeks live | 0.10 | Learning period, minimal risk |

## Risk Limits (Hardcoded)

```python
class RiskManager:
    # NEVER change these without manual approval
    MAX_STAKE_PCT = 0.02          # 2% of balance per trade
    MAX_DAILY_LOSS_PCT = 0.08     # 8% of starting daily balance
    MAX_TOTAL_DRAWDOWN_PCT = 0.25 # 25% from peak balance
    MAX_CONCURRENT_TRADES = 3
    MAX_CORRELATED_TRADES = 2     # Max 2 in same correlation group
    MAX_TRADES_PER_DAY = 40
    MIN_TRADE_INTERVAL_SEC = 30   # At least 30s between trades
    
    COOLDOWN_RULES = {
        3: 15 * 60,   # 3 consecutive losses → 15 min pause
        4: 60 * 60,   # 4 consecutive losses → 1 hour pause
        5: 4 * 3600,  # 5 consecutive losses → 4 hour pause
    }
    
    def can_trade(self, state: dict) -> tuple[bool, str]:
        """Check ALL risk rules. Returns (allowed, reason)."""
        
        # Daily loss limit
        if abs(state['daily_pnl']) >= state['daily_start_balance'] * self.MAX_DAILY_LOSS_PCT:
            return False, "daily_loss_limit_reached"
        
        # Total drawdown
        drawdown = (state['peak_balance'] - state['current_balance']) / state['peak_balance']
        if drawdown >= self.MAX_TOTAL_DRAWDOWN_PCT:
            return False, "max_drawdown_reached"
        
        # Concurrent trades
        if state['open_trades'] >= self.MAX_CONCURRENT_TRADES:
            return False, "max_concurrent_trades"
        
        # Daily trade count
        if state['trades_today'] >= self.MAX_TRADES_PER_DAY:
            return False, "max_daily_trades"
        
        # Cooldown
        for losses, cooldown in sorted(self.COOLDOWN_RULES.items(), reverse=True):
            if state['consecutive_losses'] >= losses:
                if state['time_since_last_loss'] < cooldown:
                    return False, f"cooldown_{losses}_losses"
                break
        
        # Trade interval
        if state['time_since_last_trade'] < self.MIN_TRADE_INTERVAL_SEC:
            return False, "min_interval"
        
        return True, "ok"
```

## Correlation Groups

```python
CORRELATION_GROUPS = {
    "vol_high": {"R_75", "R_100"},
    "vol_low": {"R_25", "R_50"},
    "crash": {"CRASH500", "CRASH1000"},
    "boom": {"BOOM500", "BOOM1000"},
}

def check_correlation(symbol: str, open_trades: list[dict], max_correlated: int = 2) -> bool:
    """Returns True if trade is allowed (correlation limit not exceeded)."""
    my_group = None
    for group, symbols in CORRELATION_GROUPS.items():
        if symbol in symbols:
            my_group = group
            break
    
    if my_group is None:
        return True  # No group, always allowed
    
    correlated = sum(1 for t in open_trades 
                    if t['symbol'] in CORRELATION_GROUPS.get(my_group, set()))
    return correlated < max_correlated
```

## Progressive Drawdown Recovery

```python
def drawdown_adjustment(current_drawdown_pct: float) -> float:
    """
    Progressively reduce stake as drawdown increases.
    Returns multiplier for stake (0.0 to 1.0).
    """
    if current_drawdown_pct < 5:
        return 1.0     # Full stake
    elif current_drawdown_pct < 10:
        return 0.75    # Reduce 25%
    elif current_drawdown_pct < 15:
        return 0.50    # Reduce 50%
    elif current_drawdown_pct < 20:
        return 0.30    # Reduce 70%
    elif current_drawdown_pct < 25:
        return 0.15    # Minimal stake
    else:
        return 0.0     # STOP trading
```

## A/B Testing Framework

Every trade records what EACH layer would have decided independently:

```python
@dataclass
class TradeDecisionRecord:
    # Actual trade
    symbol: str
    direction: str
    result: str  # "won" or "lost"
    profit_loss: float
    
    # What each layer said
    layer1_mechanical: str      # BUY/SELL/WAIT
    layer1_confidence: float
    layer2_pgvector: str
    layer2_confidence: float
    layer3_groq: str
    layer3_confidence: float
    
    # Agreement level
    layers_agreed: int          # 1, 2, or 3
    decision_path: str          # "full_agreement", "groq_confirmed", etc.

def evaluate_ab_test(records: list[TradeDecisionRecord], min_trades: int = 100) -> dict:
    """Compare system performance with vs without Groq."""
    if len(records) < min_trades:
        return {"status": "insufficient_data", "trades": len(records)}
    
    # Group A: Trades where all 3 layers agreed
    # Group B: Would mechanical+pgvector have been right without Groq?
    
    full_system_wins = sum(1 for r in records if r.result == "won")
    full_system_total = len(records)
    
    # Simulate: what if we only traded when mechanical+pgvector agreed?
    mech_pgvec_trades = [r for r in records 
                         if r.layer1_mechanical == r.layer2_pgvector 
                         and r.layer1_mechanical != "WAIT"]
    mech_pgvec_wins = sum(1 for r in mech_pgvec_trades if r.result == "won")
    
    return {
        "full_system": {
            "trades": full_system_total,
            "wins": full_system_wins,
            "win_rate": full_system_wins / full_system_total
        },
        "without_groq": {
            "trades": len(mech_pgvec_trades),
            "wins": mech_pgvec_wins,
            "win_rate": mech_pgvec_wins / len(mech_pgvec_trades) if mech_pgvec_trades else 0
        },
        "groq_added_value": (full_system_wins/full_system_total) - 
                           (mech_pgvec_wins/len(mech_pgvec_trades) if mech_pgvec_trades else 0)
    }
```

## Circuit Breakers

```python
class CircuitBreaker:
    """Emergency stop for runaway bot behavior."""
    
    MAX_TRADES_PER_5MIN = 5       # Detect trading loops
    MAX_RECONNECTS_PER_10MIN = 5  # Detect connection issues
    
    def __init__(self):
        self.trade_timestamps = []
        self.reconnect_timestamps = []
    
    def record_trade(self):
        now = time.time()
        self.trade_timestamps.append(now)
        # Trim old entries
        self.trade_timestamps = [t for t in self.trade_timestamps if now - t < 300]
        
        if len(self.trade_timestamps) > self.MAX_TRADES_PER_5MIN:
            raise CircuitBreakerTripped("Too many trades in 5 minutes — possible loop")
    
    def record_reconnect(self):
        now = time.time()
        self.reconnect_timestamps.append(now)
        self.reconnect_timestamps = [t for t in self.reconnect_timestamps if now - t < 600]
        
        if len(self.reconnect_timestamps) > self.MAX_RECONNECTS_PER_10MIN:
            raise CircuitBreakerTripped("Too many reconnections — connection unstable")
```
