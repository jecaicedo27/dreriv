"""
Simulation API — Market replay with pgvector pattern matching
Separated from live bot functionality
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date, timezone
from typing import Optional
import numpy as np
import threading

from app.core.database import get_db, SessionLocal
from app.services.vectorizer import vectorize_candles, find_similar_patterns, populate_patterns_from_history

router = APIRouter(tags=["Simulation"])

# Background job status
_populate_status = {"running": False, "progress": 0, "total": 0, "error": None, "last_result": None}


@router.get("/simulation/dates")
def get_available_dates(db: Session = Depends(get_db)):
    """Get list of dates with available candle data"""
    result = db.execute(text("""
        SELECT DATE(open_time AT TIME ZONE 'America/Bogota') as trade_date, 
               COUNT(*) as candle_count,
               MIN(open_time) as first_candle,
               MAX(open_time) as last_candle
        FROM candles 
        WHERE symbol = 'R_100'
        GROUP BY DATE(open_time AT TIME ZONE 'America/Bogota')
        HAVING COUNT(*) >= 30
        ORDER BY trade_date DESC
    """)).fetchall()
    
    dates = []
    for row in result:
        dates.append({
            "date": str(row.trade_date),
            "candle_count": row.candle_count,
            "first": str(row.first_candle),
            "last": str(row.last_candle)
        })
    
    return {"dates": dates, "total": len(dates)}


@router.get("/simulation/candles")
def get_replay_candles(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    index: int = Query(0, description="Number of candles to reveal (0 = just metadata)"),
    db: Session = Depends(get_db)
):
    """
    Get candles for replay up to the given index.
    Returns candles progressively — index=10 returns first 10 candles.
    """
    # Get all candles for the date
    result = db.execute(text("""
        SELECT open_time, open, high, low, close,
               rsi_14, ema_21, ema_50,
               macd, macd_signal, macd_histogram,
               bollinger_upper, bollinger_middle, bollinger_lower,
               hurst_exponent, ou_deviation, regime,
               returns, momentum_5, volatility_realized, price_position,
               atr_14, garch_volatility_forecast
        FROM candles 
        WHERE symbol = 'R_100' 
          AND DATE(open_time AT TIME ZONE 'America/Bogota') = :date
        ORDER BY open_time ASC
    """), {"date": date}).fetchall()
    
    total_candles = len(result)
    
    if total_candles == 0:
        raise HTTPException(status_code=404, detail=f"No data for date {date}")
    
    # Return only up to index
    revealed = result[:index] if index > 0 else []
    
    candles = []
    for row in revealed:
        candles.append({
            "time": str(row.open_time),
            "timestamp": int(row.open_time.timestamp()) if row.open_time else 0,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "rsi": round(float(row.rsi_14 or 50), 1),
            "ema_21": float(row.ema_21) if row.ema_21 else None,
            "ema_50": float(row.ema_50) if row.ema_50 else None,
            "macd": round(float(row.macd or 0), 4),
            "macd_signal": round(float(row.macd_signal or 0), 4),
            "macd_histogram": round(float(row.macd_histogram or 0), 4),
            "bb_upper": float(row.bollinger_upper) if row.bollinger_upper else None,
            "bb_middle": float(row.bollinger_middle) if row.bollinger_middle else None,
            "bb_lower": float(row.bollinger_lower) if row.bollinger_lower else None,
            "hurst": round(float(row.hurst_exponent or 0.5), 3),
            "ou_deviation": round(float(row.ou_deviation or 0), 2),
            "regime": row.regime or 'unknown',
            "returns": round(float(row.returns or 0), 6),
            "momentum": round(float(row.momentum_5 or 0), 2),
            "volatility": round(float(row.volatility_realized or 0), 6),
            "bb_position": round(float(row.price_position or 0.5), 3),
            "atr": round(float(row.atr_14 or 0), 2),
        })
    
    # Current indicators (last revealed candle)
    current_indicators = None
    if candles:
        last = candles[-1]
        current_indicators = {
            "rsi": last["rsi"],
            "hurst": last["hurst"],
            "ou_deviation": last["ou_deviation"],
            "macd": last["macd"],
            "macd_histogram": last["macd_histogram"],
            "regime": last["regime"],
            "bb_position": last["bb_position"],
            "momentum": last["momentum"],
            "atr": last["atr"],
        }
    
    return {
        "date": date,
        "total_candles": total_candles,
        "revealed": len(candles),
        "candles": candles,
        "indicators": current_indicators,
        "has_more": index < total_candles
    }


@router.get("/simulation/pattern-match")
def get_pattern_match(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    index: int = Query(..., description="Current candle index"),
    db: Session = Depends(get_db)
):
    """
    Find similar historical patterns for the current replay position.
    Uses pgvector cosine similarity to find top matches.
    """
    if index < 30:
        return {"message": "Need at least 30 candles for pattern matching", "matches": [], "prediction": None}
    
    # Get candles up to current index
    result = db.execute(text("""
        SELECT open, high, low, close,
               rsi_14, macd, macd_signal, macd_histogram,
               returns, momentum_5, volatility_realized,
               price_position, hurst_exponent, ou_deviation, regime
        FROM candles 
        WHERE symbol = 'R_100' 
          AND DATE(open_time) = :date
        ORDER BY open_time ASC
        LIMIT :idx
    """), {"date": date, "idx": index}).fetchall()
    
    if len(result) < 30:
        return {"message": "Not enough candles", "matches": [], "prediction": None}
    
    # Convert to dict list
    candle_dicts = [dict(row._mapping) for row in result]
    
    # Get current regime for filtering
    current_regime = candle_dicts[-1].get('regime')
    
    # Vectorize current window
    query_vector = vectorize_candles(candle_dicts, window=30)
    if query_vector is None:
        return {"message": "Vectorization failed", "matches": [], "prediction": None}
    
    # Find similar patterns (exclude patterns from the same date to avoid data leakage)
    matches = find_similar_patterns(
        db, query_vector, 
        symbol='R_100',
        regime=None,  # Search all regimes for variety
        limit=10,
        min_similarity=0.5
    )
    
    # Filter out patterns from the same date (prevent leakage)
    matches = [m for m in matches if date not in m['pattern_time']][:5]
    
    # Calculate prediction from matches
    prediction = None
    if matches:
        call_votes = sum(1 for m in matches if m['outcome_direction'] == 'CALL')
        put_votes = sum(1 for m in matches if m['outcome_direction'] == 'PUT')
        total_votes = call_votes + put_votes
        
        if total_votes > 0:
            # Weighted by similarity
            call_weight = sum(m['similarity'] for m in matches if m['outcome_direction'] == 'CALL')
            put_weight = sum(m['similarity'] for m in matches if m['outcome_direction'] == 'PUT')
            total_weight = call_weight + put_weight
            
            if total_weight > 0:
                call_pct = (call_weight / total_weight) * 100
                put_pct = (put_weight / total_weight) * 100
                
                prediction = {
                    "direction": "CALL" if call_pct > put_pct else "PUT",
                    "confidence": round(max(call_pct, put_pct), 1),
                    "call_pct": round(call_pct, 1),
                    "put_pct": round(put_pct, 1),
                    "call_votes": call_votes,
                    "put_votes": put_votes,
                    "avg_similarity": round(np.mean([m['similarity'] for m in matches]) * 100, 1),
                    "avg_outcome_pips": round(np.mean([m['outcome_pips'] for m in matches]), 2),
                }
    
    return {
        "index": index,
        "matches": matches,
        "prediction": prediction,
        "total_patterns_searched": len(matches),
    }


@router.post("/simulation/populate-patterns")
def trigger_populate_patterns():
    """Populate pattern vectors in background (non-blocking)"""
    global _populate_status
    
    if _populate_status["running"]:
        return {"status": "already_running", "message": "Vectorización en progreso..."}
    
    def _run_in_background():
        global _populate_status
        _populate_status = {"running": True, "progress": 0, "total": 0, "error": None, "last_result": None}
        db = SessionLocal()
        try:
            count = populate_patterns_from_history(db, symbol='R_100')
            _populate_status["last_result"] = count
            _populate_status["running"] = False
        except Exception as e:
            _populate_status["error"] = str(e)
            _populate_status["running"] = False
        finally:
            db.close()
    
    thread = threading.Thread(target=_run_in_background, daemon=True)
    thread.start()
    
    return {"status": "started", "message": "Vectorización iniciada en background. Consulta /api/simulation/populate-status"}


@router.get("/simulation/populate-status")
def get_populate_status():
    """Check status of pattern population job"""
    return _populate_status


@router.get("/simulation/pattern-stats")
def get_pattern_stats(db: Session = Depends(get_db)):
    """Get statistics about the pattern database"""
    result = db.execute(text("""
        SELECT 
            COUNT(*) as total_patterns,
            COUNT(DISTINCT DATE(pattern_time)) as days_covered,
            AVG(pattern_quality_score) as avg_quality,
            SUM(CASE WHEN outcome_direction = 'CALL' THEN 1 ELSE 0 END) as call_patterns,
            SUM(CASE WHEN outcome_direction = 'PUT' THEN 1 ELSE 0 END) as put_patterns,
            MIN(pattern_time) as earliest,
            MAX(pattern_time) as latest
        FROM candle_patterns WHERE symbol = 'R_100'
    """)).fetchone()
    
    # Regime distribution
    regimes = db.execute(text("""
        SELECT regime_at_formation, COUNT(*) as count
        FROM candle_patterns 
        WHERE symbol = 'R_100'
        GROUP BY regime_at_formation
        ORDER BY count DESC
    """)).fetchall()
    
    return {
        "total_patterns": result.total_patterns,
        "days_covered": result.days_covered,
        "avg_quality": round(float(result.avg_quality or 0), 2),
        "call_patterns": result.call_patterns,
        "put_patterns": result.put_patterns,
        "earliest": str(result.earliest) if result.earliest else None,
        "latest": str(result.latest) if result.latest else None,
        "regimes": {r.regime_at_formation: r.count for r in regimes}
    }


# ============================================
# BOT SIMULATION
# ============================================

_bot_sim_status = {
    "running": False,
    "date": None,
    "result": None,
    "error": None
}

def _run_bot_sim_background(date: str, config: dict):
    """Run bot simulation in background thread"""
    global _bot_sim_status
    _bot_sim_status = {"running": True, "date": date, "result": None, "error": None}
    
    try:
        from app.simulation.replay_bot import ReplayBotSimulator
        db = SessionLocal()
        try:
            simulator = ReplayBotSimulator(config=config)
            result = simulator.run(db, date)
            _bot_sim_status["result"] = result
        finally:
            db.close()
    except Exception as e:
        _bot_sim_status["error"] = str(e)
    finally:
        _bot_sim_status["running"] = False


@router.post("/simulation/simulate-bot")
def simulate_bot(
    date: str = Query(..., description="Date to simulate (YYYY-MM-DD)"),
    stake: float = Query(60.0, description="Stake per trade"),
    confidence: float = Query(0.60, description="Min confidence threshold"),
):
    """Run the current bot logic on historical replay data"""
    global _bot_sim_status
    
    if _bot_sim_status["running"]:
        return {"status": "already_running", "date": _bot_sim_status["date"]}
    
    config = {
        "stake": stake,
        "min_confidence": confidence,
        "payout_rate": 0.84,
        "duration_candles": 5,
        "initial_balance": 10000.0,
        "cooldown_candles": 3
    }
    
    thread = threading.Thread(target=_run_bot_sim_background, args=(date, config))
    thread.daemon = True
    thread.start()
    
    return {"status": "started", "date": date}


@router.get("/simulation/simulate-bot-status")
def simulate_bot_status():
    """Get the status and results of the bot simulation"""
    return _bot_sim_status


# ============================================
# LIVE BOT STEP (candle-by-candle)
# ============================================

@router.post("/simulation/bot-step")
async def bot_step(
    date: str = Query(..., description="Date YYYY-MM-DD"),
    candle_index: int = Query(..., description="Current candle index in replay"),
    use_groq: bool = Query(True, description="Enable Groq Layer 2"),
    db: Session = Depends(get_db)
):
    """
    Analyze a single candle step — same pipeline as the live bot.
    Called by the frontend on each candle during replay.
    
    Returns:
        { action, confidence, groq_used, reasoning, l1_signal, l1_confidence }
    """
    try:
        # Load candles up to current index
        result = db.execute(text("""
            SELECT open_time, open, high, low, close,
                   rsi_14, ema_9, ema_21, ema_50,
                   macd, macd_signal, macd_histogram,
                   bollinger_upper, bollinger_middle, bollinger_lower,
                   hurst_exponent, ou_deviation, regime,
                   returns, momentum_5, volatility_realized, price_position,
                   atr_14
            FROM candles
            WHERE symbol = 'R_100'
              AND DATE(open_time AT TIME ZONE 'America/Bogota') = :date
            ORDER BY open_time ASC
        """), {"date": date}).fetchall()

        if candle_index >= len(result) or candle_index < 50:
            return {"action": "HOLD", "confidence": 0, "reason": "insufficient_data"}

        # Build DataFrame up to current index
        columns = [
            'open_time', 'open', 'high', 'low', 'close',
            'rsi_14', 'ema_9', 'ema_21', 'ema_50',
            'macd', 'macd_signal', 'macd_histogram',
            'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
            'hurst_exponent', 'ou_deviation', 'regime',
            'returns', 'momentum_5', 'volatility_realized', 'price_position',
            'atr_14'
        ]
        import pandas as pd
        rows = [dict(zip(columns, row)) for row in result[:candle_index + 1]]
        df = pd.DataFrame(rows)

        numeric_cols = [c for c in columns if c not in ('open_time', 'regime')]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

        # Window: last 250 candles
        start_idx = max(0, len(df) - 250)
        window = df.iloc[start_idx:].copy()

        # ===== LAYER 1 =====
        from app.analysis.layer1_engine import Layer1SignalEngine
        engine = Layer1SignalEngine()
        signal = engine.analyze(window, 'R_100')

        l1_signal = signal.get('final_signal', 'HOLD')
        l1_confidence = signal.get('final_confidence', 0.0)
        l1_reasoning = signal.get('reasoning', '')
        hurst_value = signal.get('hurst_signal', {}).get('hurst', 0.5)

        # ===== LAYER 2: GROQ =====
        groq_used = False
        final_signal = l1_signal
        final_confidence = l1_confidence
        groq_reasoning = ""

        # Groq ONLY when L1 has directional signal — L1 is gatekeeper
        should_call_groq = use_groq and l1_signal in ['CALL', 'PUT']

        if should_call_groq:
            try:
                from app.analysis.layer2_groq import get_layer2_engine
                layer2 = get_layer2_engine()

                # Build simple candle objects for Groq context (last 25)
                class SC:
                    def __init__(self, r):
                        self.open = float(r['open'])
                        self.high = float(r['high'])
                        self.low = float(r['low'])
                        self.close = float(r['close'])

                candle_start = max(0, len(df) - 25)
                candles_for_groq = [SC(df.iloc[j]) for j in range(candle_start, len(df))]

                groq_result = await layer2.analyze(
                    layer1_signal=signal,
                    candles=candles_for_groq,
                    db=None  # No DB writes in simulation
                )

                groq_used = True
                final_signal = groq_result.get('decision', groq_result.get('final_signal', 'HOLD'))
                final_confidence = groq_result.get('confidence', groq_result.get('final_confidence', 0.0))

                chain = groq_result.get('reasoning_chain', {})
                if isinstance(chain, dict):
                    groq_reasoning = chain.get('step6_final_decision_rationale', str(chain)[:300])
                else:
                    groq_reasoning = str(chain)[:300]

            except Exception as e:
                from loguru import logger
                logger.warning(f"⚠️ Groq error in bot-step: {e}")
                # Fallback to L1
                final_signal = l1_signal
                final_confidence = l1_confidence

        entry_price = float(df.iloc[candle_index]['close'])

        return {
            "action": final_signal,
            "confidence": round(final_confidence, 3),
            "entry_price": round(entry_price, 2),
            "groq_used": groq_used,
            "l1_signal": l1_signal,
            "l1_confidence": round(l1_confidence, 3),
            "reasoning": groq_reasoning if groq_used else l1_reasoning[:200],
            "groq_reasoning": groq_reasoning,
            "hurst": round(hurst_value, 4)
        }

    except Exception as e:
        from loguru import logger
        logger.error(f"❌ bot-step error: {e}")
        return {"action": "HOLD", "confidence": 0, "error": str(e)}
