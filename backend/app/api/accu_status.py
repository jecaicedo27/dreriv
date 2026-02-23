"""
API endpoints for Accumulator Bot status and control
"""
from fastapi import APIRouter, Request, Query
from loguru import logger
from datetime import datetime
import time

from app.services.accu_db import get_accu_trades as db_get_accu_trades, get_accu_session_stats

router = APIRouter()

# In-memory state shared with the AccumulatorBot
# This gets updated by the bot when it runs
accu_bot_state = {
    "is_running": False,
    "symbol": "BOOM1000",
    "balance": 0.0,
    "total_trades": 0,
    "total_wins": 0,
    "total_losses": 0,
    "session_pnl": 0.0,
    "consecutive_losses": 0,
    "open_contract_id": None,
    "open_contract_pnl": 0.0,
    "growth_rate": 0.02,
    "stake": 1.0,
    "take_profit": 50.0,
    "cooldown_until": None,
    "last_updated": None,
    # Analysis metrics
    "total_ticks": 0,
    "spikes_detected": 0,
    "volatility_score": 0.0,
    "last_signal": "NOT_READY",
    "last_reasoning": "",
    "last_price": None,
}


def update_accu_state(bot):
    """Update shared state from bot instance (called by the bot)"""
    global accu_bot_state
    accu_bot_state.update({
        "is_running": bot.is_running,
        "balance": bot.balance,
        "total_trades": bot.total_trades,
        "total_wins": bot.total_wins,
        "total_losses": bot.total_losses,
        "session_pnl": bot.session_pnl,
        "consecutive_losses": bot.consecutive_losses,
        "open_contract_id": bot.open_contract_id,
        "open_contract_pnl": bot.open_contract_current_pnl,
        "cooldown_until": str(bot.cooldown_until) if bot.cooldown_until else None,
        "last_updated": datetime.now().isoformat(),
        # Config values (read live from bot config)
        "symbol": bot.config.SYMBOL,
        "stake": bot.config.STAKE,
        "growth_rate": bot.config.GROWTH_RATE,
        "take_profit": bot.config.TAKE_PROFIT,
    })

    # Update from analysis engine
    if hasattr(bot, 'analysis_engine'):
        stats = bot.analysis_engine.get_stats()
        accu_bot_state.update({
            "total_ticks": stats.get('total_ticks', 0),
            "spikes_detected": stats.get('spikes_detected', 0),
            "last_price": stats.get('last_price'),
            "volatility_score": stats.get('volatility_score', 0.0),
            "last_signal": stats.get('signal', 'NOT_READY'),
            "last_reasoning": stats.get('reasoning', ''),
        })


@router.get("/accu/status")
async def get_accu_status():
    """Get current status of the Accumulator bot — merges live state + DB stats"""
    state = accu_bot_state.copy()

    # Merge persistent stats from database
    db_stats = get_accu_session_stats()
    state["total_trades"] = db_stats["total_trades"]
    state["total_wins"] = db_stats["wins"]
    state["total_losses"] = db_stats["losses"]
    state["session_pnl"] = db_stats["session_pnl"]
    state["win_rate"] = db_stats["win_rate"]

    # Average ticks per spike
    if state["spikes_detected"] > 0 and state["total_ticks"] > 0:
        state["avg_ticks_per_spike"] = round(state["total_ticks"] / state["spikes_detected"])
    else:
        state["avg_ticks_per_spike"] = None

    return state


@router.get("/accu/trades")
async def get_accu_trades(limit: int = Query(50, description="Number of trades to return")):
    """Get recent ACCU trades from database"""
    trades = db_get_accu_trades(limit=limit)
    return {"trades": trades}


# In-memory trade log (limited to last 100)
accu_trade_log = []


def log_accu_trade(trade_data: dict):
    """Add a trade to the in-memory log"""
    accu_trade_log.insert(0, trade_data)
    if len(accu_trade_log) > 100:
        accu_trade_log.pop()


# ============================================
# In-memory storage for chart data
# ALL timeframes pre-loaded at bot startup
# ============================================
accu_candle_data = []  # List of {time, open, high, low, close} — 1m candles (live)
MAX_CANDLES = 500

# Tick-level data for tick chart (each tick = ~1 second for Vol100)
accu_tick_data = []  # List of {time, value} — raw ticks
MAX_TICKS = 500

# Pre-loaded cache for all timeframes {granularity: list of candles}
_candle_cache = {}


def push_accu_candle(candle: dict):
    """Add or update a candle in storage (1m live data)"""
    global accu_candle_data

    # Check if we already have a candle for this timestamp
    if accu_candle_data and accu_candle_data[-1]['time'] == candle['time']:
        # Update existing candle (live update)
        accu_candle_data[-1] = candle
    else:
        accu_candle_data.append(candle)
        if len(accu_candle_data) > MAX_CANDLES:
            accu_candle_data.pop(0)


def set_candle_cache(granularity: int, candles: list):
    """Store pre-fetched candles for a timeframe (called by bot at startup)"""
    _candle_cache[granularity] = candles


def push_accu_tick(tick: dict):
    """Add a tick to storage (called by bot on each tick)"""
    global accu_tick_data
    accu_tick_data.append(tick)
    if len(accu_tick_data) > MAX_TICKS:
        accu_tick_data.pop(0)


@router.get("/accu/candles")
async def get_accu_candles(
    granularity: int = Query(60, description="Candle granularity: 1 (ticks), 60, 300, 3600, 86400")
):
    """
    Get chart data for the ACCU bot.
    granularity=1: tick-by-tick data (~1s each)
    granularity=60+: candle data
    """
    # Tick chart: return raw ticks as OHLC (open=high=low=close=value)
    if granularity == 1:
        return [{
            "time": t["time"],
            "open": t["value"],
            "high": t["value"],
            "low": t["value"],
            "close": t["value"],
        } for t in accu_tick_data]

    # Validate granularity
    valid_granularities = {60, 300, 3600, 86400}
    if granularity not in valid_granularities:
        granularity = 60

    # 1-minute candles: return live streaming data
    if granularity == 60:
        return accu_candle_data

    # Other timeframes: return from pre-loaded cache
    cached = _candle_cache.get(granularity)
    if cached:
        return cached

    # Fallback: aggregate from 1m data if cache not yet populated
    return _aggregate_candles(accu_candle_data, granularity)


def _aggregate_candles(candles_1m: list, target_granularity: int) -> list:
    """Fallback: aggregate 1m candles into higher timeframes"""
    if not candles_1m:
        return []

    bucket_size = target_granularity // 60
    if bucket_size <= 1:
        return candles_1m

    result = []
    for i in range(0, len(candles_1m), bucket_size):
        bucket = candles_1m[i:i + bucket_size]
        if not bucket:
            continue
        result.append({
            "time": bucket[0]["time"],
            "open": bucket[0]["open"],
            "high": max(c["high"] for c in bucket),
            "low": min(c["low"] for c in bucket),
            "close": bucket[-1]["close"],
        })
    return result

