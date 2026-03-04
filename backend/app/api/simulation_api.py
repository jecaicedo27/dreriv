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
from loguru import logger

from app.core.database import get_db, SessionLocal
from app.services.vectorizer import vectorize_candles, find_similar_patterns, populate_patterns_from_history

router = APIRouter(tags=["Simulation"])

# Background job status
_populate_status = {"running": False, "progress": 0, "total": 0, "error": None, "last_result": None}

# Persistent engine for visual simulation (so session tracking works across bot-step calls)
_sim_engine = None
_sim_engine_date = None
_sim_engine_name = None

def _get_sim_engine(date: str, engine_name: str = "original_v1"):
    """Get or create a persistent analysis engine for the visual simulation.
    Resets when the date or engine changes (new simulation started)."""
    global _sim_engine, _sim_engine_date, _sim_engine_name
    if _sim_engine is None or _sim_engine_date != date or _sim_engine_name != engine_name:
        from app.analysis.engine_registry import get_engine
        _sim_engine = get_engine(engine_name)
        _sim_engine_date = date
        _sim_engine_name = engine_name
    return _sim_engine


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
            "candle_count": int(row.candle_count),
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
    """
    # Get all candles for the date
    result = db.execute(text("""
        SELECT open_time, open, high, low, close,
               rsi_14, ema_9, ema_21, ema_50,
               macd, macd_signal, macd_histogram,
               bollinger_upper, bollinger_middle, bollinger_lower,
               hurst_exponent, hurst_fast, ou_deviation, regime,
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
            "timestamp": int(row.open_time.timestamp()) - 5 * 3600 if row.open_time else 0,  # UTC-5 (Colombia)
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "rsi": round(float(row.rsi_14 or 50), 1),
            "ema_9": float(row.ema_9) if row.ema_9 else None,
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
               price_position, hurst_exponent, hurst_fast, ou_deviation, regime
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
    engine_name: str = Query("original_v1", description="Analysis engine to use"),
):
    """Run the current bot logic on historical replay data"""
    global _bot_sim_status
    
    if _bot_sim_status["running"]:
        return {"status": "already_running", "date": _bot_sim_status["date"]}
    
    # Pull hurst range from engine registry so each engine gets its correct config
    from app.analysis.engine_registry import get_engine_config
    engine_cfg = get_engine_config(engine_name) or {}
    
    config = {
        "stake": stake,
        "min_confidence": confidence,
        "payout_rate": 0.95,
        "duration_candles": engine_cfg.get("duration_candles", 5),
        "initial_balance": 10000.0,
        "cooldown_candles": 1,
        "engine_name": engine_name,
        "hurst_min": engine_cfg.get("hurst_min", 0.6),
        "hurst_max": engine_cfg.get("hurst_max", 0.7),
        "slope_min": engine_cfg.get("slope_min", 0.0),
        "slope_lookback": engine_cfg.get("slope_lookback", 20),
        "use_groq": False,
        # Disable defensive filters that kill recovery trades after pullback losses
        "dir_cooldown_candles": 0,
        "enable_global_streak": False,
        "enable_wr_monitor": False,
        "enable_atr_gate": False,
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
# MULTI-DAY SIMULATION
# ============================================

_multi_sim_status = {
    "running": False,
    "progress": 0,
    "total_days": 0,
    "current_date": None,
    "daily_results": [],
    "accumulated": None,
    "error": None,
}


def _run_multi_sim_background(dates: list, config: dict):
    """Run bot simulation across multiple dates sequentially"""
    global _multi_sim_status
    _multi_sim_status = {
        "running": True,
        "cancel": False,
        "progress": 0,
        "total_days": len(dates),
        "current_date": None,
        "daily_results": [],
        "accumulated": None,
        "error": None,
    }

    try:
        from app.simulation.replay_bot import ReplayBotSimulator
        from loguru import logger
        db = SessionLocal()

        cumulative_pnl = 0
        total_trades = 0
        total_wins = 0
        total_losses = 0
        balance = config.get("initial_balance", 10000.0)
        peak_balance = balance
        max_dd_pct = 0

        try:
            for i, date_str in enumerate(dates):
                # Check cancel flag
                if _multi_sim_status.get("cancel"):
                    logger.info("🛑 Multi-day simulation cancelled by user")
                    break

                _multi_sim_status["current_date"] = date_str
                _multi_sim_status["progress"] = i

                # Create simulator with current balance (carry over)
                day_config = {**config, "initial_balance": balance}
                simulator = ReplayBotSimulator(config=day_config)
                result = simulator.run(db, date_str)

                if "error" in result:
                    _multi_sim_status["daily_results"].append({
                        "date": date_str,
                        "error": result["error"],
                        "trades": 0, "wins": 0, "losses": 0,
                        "pnl": 0, "win_rate": 0, "balance": balance
                    })
                    continue

                day_summary = result.get("summary", result)
                day_pnl = day_summary.get("total_pnl", 0)
                day_trades = day_summary.get("total_trades", 0)
                day_wins = day_summary.get("wins", 0)
                day_losses = day_summary.get("losses", 0)
                day_wr = day_summary.get("win_rate", 0)

                balance += day_pnl
                cumulative_pnl += day_pnl
                total_trades += day_trades
                total_wins += day_wins
                total_losses += day_losses

                if balance > peak_balance:
                    peak_balance = balance
                dd = (peak_balance - balance) / peak_balance * 100 if peak_balance > 0 else 0
                if dd > max_dd_pct:
                    max_dd_pct = dd

                # ===== SAVE TO DB =====
                trade_list = result.get("trades", [])
                try:
                    strategy_name = f"Multi-Day_L1{'_Groq' if config.get('use_groq') else ''}"
                    import json as json_lib
                    sim_config = json_lib.dumps({
                        "min_confidence": config.get("min_confidence", 0.60),
                        "stake_type": "kelly_dynamic",
                        "use_groq": config.get("use_groq", False),
                        "payout_rate": config.get("payout_rate", 0.95),
                        "cooldown_candles": config.get("cooldown_candles", 1),
                        "trade_duration": config.get("trade_duration_candles", 3),
                        "engine_name": config.get("engine_name", "original_v1"),
                    })
                    run_result = db.execute(text("""
                        INSERT INTO simulation_runs 
                        (name, strategy_name, start_date, end_date, initial_balance, config, status, started_at)
                        VALUES (
                            :sim_name,
                            :strategy, :date, :date, :init_bal, CAST(:config AS jsonb), 'COMPLETED', NOW()
                        )
                        RETURNING id
                    """), {
                        "strategy": strategy_name,
                        "date": date_str,
                        "init_bal": day_config["initial_balance"],
                        "config": sim_config,
                        "sim_name": f"Sim | {date_str} | Conf {int(config.get('min_confidence', 0.60) * 100)}%",
                    })
                    run_id = run_result.fetchone()[0]

                    for t in trade_list:
                        # Parse entry_time safely — handle malformed timestamps
                        raw_time = t.get("time", "")
                        try:
                            from dateutil import parser as dt_parser
                            parsed_time = dt_parser.parse(str(raw_time)) if raw_time else None
                        except Exception:
                            parsed_time = None

                        db.execute(text("""
                            INSERT INTO simulation_trades 
                            (run_id, entry_time, exit_time, direction, entry_price, exit_price, 
                             stake, outcome, profit_loss, balance_after, confidence, reasoning)
                            VALUES (:run_id, :entry_time, NULL, :direction, :entry_price, :exit_price,
                                    :stake, :outcome, :profit_loss, :balance_after, :confidence, :reasoning)
                        """), {
                            "run_id": run_id,
                            "entry_time": parsed_time,
                            "direction": t.get("direction", ""),
                            "entry_price": t.get("entry_price", 0),
                            "exit_price": t.get("exit_price", 0),
                            "stake": t.get("stake", 0),
                            "outcome": t.get("result", ""),
                            "profit_loss": t.get("pnl", 0),
                            "balance_after": t.get("balance_after", 0),
                            "confidence": round(t.get("confidence", 0), 2),
                            "reasoning": t.get("reasoning", "")[:500],
                        })

                    # Update run with summary stats
                    db.execute(text("""
                        UPDATE simulation_runs 
                        SET total_trades = :total, winning_trades = :wins,
                            losing_trades = :losses, win_rate = :wr,
                            total_pnl = :pnl, final_balance = :bal,
                            max_drawdown_pct = 0, completed_at = NOW()
                        WHERE id = :run_id
                    """), {
                        "run_id": run_id, "total": day_trades,
                        "wins": day_wins, "losses": day_losses,
                        "wr": round(day_wr, 1), "pnl": round(day_pnl, 2),
                        "bal": round(balance, 2),
                    })
                    db.commit()
                    logger.info(f"💾 Saved multi-day sim {date_str}: run_id={run_id}, {day_trades} trades")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to save sim results for {date_str}: {e}")
                    db.rollback()

                _multi_sim_status["daily_results"].append({
                    "date": date_str,
                    "trades": day_trades,
                    "wins": day_wins,
                    "losses": day_losses,
                    "win_rate": round(day_wr, 1),
                    "pnl": round(day_pnl, 2),
                    "balance": round(balance, 2),
                    "trade_details": trade_list,
                })

            overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
            _multi_sim_status["accumulated"] = {
                "total_days": len(dates),
                "days_with_trades": sum(1 for d in _multi_sim_status["daily_results"] if d["trades"] > 0),
                "total_trades": total_trades,
                "total_wins": total_wins,
                "total_losses": total_losses,
                "win_rate": round(overall_wr, 1),
                "total_pnl": round(cumulative_pnl, 2),
                "final_balance": round(balance, 2),
                "initial_balance": config.get("initial_balance", 10000.0),
                "peak_balance": round(peak_balance, 2),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "roi_pct": round(cumulative_pnl / config.get("initial_balance", 10000.0) * 100, 2),
            }
            _multi_sim_status["progress"] = len(dates)

        finally:
            db.close()
    except Exception as e:
        _multi_sim_status["error"] = str(e)
        logger.error(f"Multi-day simulation error: {e}")
    finally:
        _multi_sim_status["running"] = False


@router.get("/simulation/engines")
def list_analysis_engines():
    """List available analysis engines for UI dropdown"""
    from app.analysis.engine_registry import list_engines
    return {"engines": list_engines()}


@router.post("/simulation/live-step")
async def live_step(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    candle_index: int = Query(..., description="Current candle index within the date"),
    use_groq: bool = Query(False),
    ai_provider: str = Query("groq"),
    hurst_min: float = Query(0.6),
    hurst_max: float = Query(0.7),
    engine_name: str = Query("original_v1"),
    db: Session = Depends(get_db),
):
    """
    Analyze a SINGLE candle position using the same TradingCore pipeline.
    L1 runs always. Groq is called LIVE only when L1 gives CALL/PUT.
    This endpoint is called by the frontend during chart playback for real-time decisions.
    """
    from app.analysis.engine_registry import get_engine
    from app.simulation.trading_core import TradingCore
    import pandas as pd

    import pandas as pd

    # Load candles: lookback + date candles up to candle_index
    lookback = 200
    result = db.execute(text("""
        WITH date_candles AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY open_time) as rn
            FROM candles
            WHERE symbol = 'R_100'
              AND DATE(open_time AT TIME ZONE 'America/Bogota') = :date
            ORDER BY open_time
        )
        SELECT open_time, open, high, low, close,
               rsi_14, ema_9, ema_21, ema_50,
               macd, macd_signal, macd_histogram,
               bollinger_upper, bollinger_middle, bollinger_lower,
               hurst_exponent, hurst_fast, ou_deviation, regime,
               returns, momentum_5, volatility_realized, price_position,
               atr_14
        FROM (
            SELECT * FROM candles
            WHERE symbol = 'R_100'
              AND open_time < (SELECT MIN(open_time) FROM date_candles)
            ORDER BY open_time DESC
            LIMIT :lookback
        ) lookback_data
        UNION ALL
        SELECT open_time, open, high, low, close,
               rsi_14, ema_9, ema_21, ema_50,
               macd, macd_signal, macd_histogram,
               bollinger_upper, bollinger_middle, bollinger_lower,
               hurst_exponent, hurst_fast, ou_deviation, regime,
               returns, momentum_5, volatility_realized, price_position,
               atr_14
        FROM date_candles
        WHERE rn <= :candle_idx
        ORDER BY open_time
    """), {"date": date, "lookback": lookback, "candle_idx": candle_index + 1}).fetchall()

    if len(result) < 50:
        return {"action": "HOLD", "confidence": 0, "reasoning": "Insufficient data", "groq_used": False}

    columns = [
        'open_time', 'open', 'high', 'low', 'close',
        'rsi_14', 'ema_9', 'ema_21', 'ema_50',
        'macd', 'macd_signal', 'macd_histogram',
        'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
        'hurst_exponent', 'hurst_fast', 'ou_deviation', 'regime',
        'returns', 'momentum_5', 'volatility_realized', 'price_position',
        'atr_14'
    ]
    df = pd.DataFrame([dict(zip(columns, row)) for row in result])
    numeric_cols = [c for c in columns if c not in ('open_time', 'regime')]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

    engine = get_engine(engine_name)
    analysis = await TradingCore.analyze_async(
        engine=engine,
        df=df,
        symbol='R_100',
        use_groq=use_groq,
        ai_provider=ai_provider,
        hurst_min=hurst_min,
        hurst_max=hurst_max,
    )

    return {
        "action": analysis.get("action", "HOLD"),
        "confidence": analysis.get("confidence", 0),
        "l1_signal": analysis.get("l1_signal", "HOLD"),
        "l1_confidence": analysis.get("l1_confidence", 0),
        "reasoning": analysis.get("reasoning", ""),
        "groq_reasoning": analysis.get("groq_reasoning", ""),
        "groq_used": analysis.get("groq_used", False),
        "ai_provider": analysis.get("ai_provider", "none"),
        "hurst": analysis.get("hurst", 0),
        "entry_price": analysis.get("entry_price", 0),
        "candle_index": candle_index,
    }


@router.post("/simulation/bot-precompute")
async def bot_precompute(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    confidence: float = Query(0.60),
    max_confidence: float = Query(1.0, description="Max confidence threshold"),
    use_groq: bool = Query(False),
    ai_provider: str = Query("groq"),
    hurst_min: float = Query(0.6, description="Min Hurst for trending trades"),
    hurst_max: float = Query(0.7, description="Max Hurst for trending trades"),
    blocked_hours: str = Query("", description="Comma-separated Colombia-time hours to skip, e.g. 7,18,21,23"),
    engine_name: str = Query("original_v1", description="Analysis engine to use"),
    db: Session = Depends(get_db),
):
    """
    Pre-compute ALL bot trades for a date using the EXACT same replay_bot code.
    Returns the full list of trades with their candle indices, so the frontend
    can overlay them on the chart. This guarantees 100% identical results
    between visual and multi-day simulations.
    """
    from app.simulation.replay_bot import ReplayBotSimulator
    from app.analysis.engine_registry import get_engine_config
    engine_cfg = get_engine_config(engine_name) or {}
    defensive = engine_cfg.get("defensive", {})
    config = {
        "min_confidence": engine_cfg.get("confidence_min", confidence),
        "max_confidence": engine_cfg.get("confidence_max", max_confidence),
        "payout_rate": 0.95,
        "duration_candles": engine_cfg.get("duration_candles", 5),
        "initial_balance": 10000.0,
        "cooldown_candles": defensive.get("cooldown_candles", 3),
        "use_groq": use_groq,
        "ai_provider": ai_provider,
        "hurst_min": engine_cfg.get("hurst_min", hurst_min),
        "hurst_max": engine_cfg.get("hurst_max", hurst_max),
        "slope_min": engine_cfg.get("slope_min", 0.0),
        "slope_lookback": engine_cfg.get("slope_lookback", 20),
        "engine_name": engine_name,
        # Defensive parameters from engine config
        "enable_wr_monitor": defensive.get("enable_wr_monitor", True),
        "wr_pause_threshold": defensive.get("wr_pause_threshold", 0.47),
        "wr_stop_threshold": defensive.get("wr_stop_threshold", 0.42),
        "enable_global_streak": defensive.get("enable_global_streak", True),
        "enable_atr_gate": defensive.get("enable_atr_gate", True),
        "dir_cooldown_candles": defensive.get("dir_cooldown_candles", 30),
    }
    bot = ReplayBotSimulator(config)
    result = await bot._run_async(db, date, 'R_100')
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


def _check_indicator_coverage(db, start_date=None, end_date=None):
    """Check indicator coverage for the given date range. Returns warnings list."""
    KEY_INDICATORS = [
        'ema_21', 'ema_50', 'rsi_14', 'macd_histogram',
        'bollinger_upper', 'momentum_5', 'hurst_fast',
        'log_returns', 'volume_delta', 'price_position',
        'garch_volatility_forecast'
    ]
    MIN_COVERAGE = 80  # percent

    date_filter = ""
    params = {}
    if start_date:
        date_filter += " AND DATE(open_time AT TIME ZONE 'America/Bogota') >= :start"
        params["start"] = start_date
    if end_date:
        date_filter += " AND DATE(open_time AT TIME ZONE 'America/Bogota') <= :end"
        params["end"] = end_date

    total = db.execute(text(f"""
        SELECT COUNT(*) FROM candles
        WHERE symbol='R_100' {date_filter}
    """), params).scalar() or 0

    if total == 0:
        return [], total, {}

    coverage = {}
    missing = []
    for col in KEY_INDICATORS:
        filled = db.execute(text(f"""
            SELECT COUNT(*) FROM candles
            WHERE symbol='R_100' {date_filter} AND {col} IS NOT NULL
        """), params).scalar() or 0
        pct = round(filled * 100 / total, 1) if total else 0
        coverage[col] = {"filled": filled, "total": total, "percent": pct}
        if pct < MIN_COVERAGE:
            missing.append(f"{col}: {pct}%")

    warnings = []
    if missing:
        warnings.append(
            f"⚠️ Indicadores incompletos ({len(missing)}/{len(KEY_INDICATORS)}): "
            + ", ".join(missing)
        )
        warnings.append(
            "Los resultados pueden ser poco confiables. "
            "Espere a que termine el backfill de indicadores."
        )

    return warnings, total, coverage


@router.get("/simulation/indicator-coverage")
def indicator_coverage(
    start_date: str = Query(None),
    end_date: str = Query(None),
    db: Session = Depends(get_db),
):
    """Check indicator data coverage for the given date range"""
    warnings, total, coverage = _check_indicator_coverage(db, start_date, end_date)
    return {
        "total_candles": total,
        "coverage": coverage,
        "warnings": warnings,
        "ready": len(warnings) == 0,
    }


@router.post("/simulation/simulate-multi")
def simulate_multi(
    start_date: str = Query(None, description="Start date (YYYY-MM-DD), null = all data"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD), null = all data"),
    stake: float = Query(60.0, description="Stake per trade"),
    confidence: str = Query("0.60", description="Min confidence threshold"),
    max_confidence: str = Query("1.0", description="Max confidence threshold"),
    use_groq: bool = Query(False, description="Use Groq AI Layer 2"),
    hurst_min: str = Query("0.6", description="Min Hurst for trending trades"),
    hurst_max: str = Query("0.7", description="Max Hurst for trending trades"),
    blocked_hours: str = Query("", description="Comma-separated Colombia-time hours to skip"),
    engine_name: str = Query("original_v1", description="Analysis engine to use"),
    db: Session = Depends(get_db),
):
    """Run bot simulation across multiple days (date range or all available data)"""
    # Parse numeric params safely (empty strings → defaults)
    confidence_val = float(confidence) if confidence else 0.60
    max_confidence_val = float(max_confidence) if max_confidence else 1.0
    hurst_min_val = float(hurst_min) if hurst_min else 0.6
    hurst_max_val = float(hurst_max) if hurst_max else 0.7
    global _multi_sim_status

    if _multi_sim_status["running"]:
        return {"status": "already_running", "current_date": _multi_sim_status["current_date"]}

    # Check indicator coverage — BLOCK if below threshold
    data_warnings, _, coverage = _check_indicator_coverage(db, start_date, end_date)
    if data_warnings:
        missing_detail = [
            f"{col}: {info['percent']}% poblado"
            for col, info in coverage.items()
            if info['percent'] < 80
        ]
        return {
            "status": "blocked",
            "message": "⚠️ Indicadores incompletos — no se puede simular con datos poco confiables.",
            "data_warnings": missing_detail + [
                "Espera a que termine el backfill de indicadores antes de simular."
            ]
        }

    # Build date filter
    date_filter = ""
    params = {}
    if start_date:
        date_filter += " AND DATE(open_time AT TIME ZONE 'America/Bogota') >= :start"
        params["start"] = start_date
    if end_date:
        date_filter += " AND DATE(open_time AT TIME ZONE 'America/Bogota') <= :end"
        params["end"] = end_date

    # Find all dates with sufficient data
    result = db.execute(text(f"""
        SELECT DATE(open_time AT TIME ZONE 'America/Bogota') as d,
               COUNT(*) as cnt
        FROM candles
        WHERE symbol = 'R_100' {date_filter}
        GROUP BY d
        HAVING COUNT(*) >= 100
        ORDER BY d ASC
    """), params).fetchall()

    dates = [str(row.d) for row in result]

    if not dates:
        return {"status": "error", "message": "No dates with sufficient candle data (100+) in the specified range"}

    # Pull per-engine hurst from registry (overrides UI params)
    from app.analysis.engine_registry import get_engine_config
    engine_cfg = get_engine_config(engine_name) or {}

    # Build full config — merge registry defensive filters as single source of truth
    defensive = engine_cfg.get("defensive", {})
    config = {
        "stake": stake,
        "min_confidence": engine_cfg.get("confidence_min", confidence_val),
        "max_confidence": engine_cfg.get("confidence_max", max_confidence_val),
        "payout_rate": 0.95,
        "duration_candles": engine_cfg.get("duration_candles", 5),
        "initial_balance": 10000.0,
        "cooldown_candles": defensive.get("cooldown_candles", 3),
        "use_groq": use_groq,
        "hurst_min": engine_cfg.get("hurst_min", hurst_min_val),
        "hurst_max": engine_cfg.get("hurst_max", hurst_max_val),
        "blocked_hours": [int(h.strip()) for h in blocked_hours.split(',') if h.strip()] if blocked_hours else engine_cfg.get("blocked_hours", []),
        "engine_name": engine_name,
        # Merge ALL defensive filters from registry
        **{k: v for k, v in defensive.items()},
    }

    thread = threading.Thread(target=_run_multi_sim_background, args=(dates, config))
    thread.daemon = True
    thread.start()

    return {"status": "started", "dates": dates, "total_days": len(dates)}


@router.get("/simulation/simulate-multi-status")
def simulate_multi_status():
    """Get status and results of multi-day simulation"""
    return _multi_sim_status


@router.post("/simulation/simulate-multi-stop")
def simulate_multi_stop():
    """Stop a running multi-day simulation"""
    global _multi_sim_status
    if _multi_sim_status["running"]:
        _multi_sim_status["cancel"] = True
        return {"status": "cancelling"}
    return {"status": "not_running"}


# ============================================
# LIVE BOT STEP (candle-by-candle)
# ============================================

@router.post("/simulation/bot-step")
async def bot_step(
    date: str = Query(..., description="Date YYYY-MM-DD"),
    candle_index: int = Query(..., description="Current candle index in replay"),
    use_groq: bool = Query(True, description="Enable AI Layer 2"),
    ai_provider: str = Query("groq", description="AI provider: groq or openai"),
    engine_name: str = Query("original_v1", description="Analysis engine to use"),
    db: Session = Depends(get_db)
):
    """
    Analyze a single candle step — same pipeline as the live bot.
    Called by the frontend on each candle during replay.
    
    Returns:
        { action, confidence, groq_used, reasoning, l1_signal, l1_confidence }
    """
    try:
        # Load candles: 300 from previous days (lookback) + all from selected date
        result = db.execute(text("""
            WITH date_candles AS (
                SELECT open_time, open, high, low, close,
                       rsi_14, ema_9, ema_21, ema_50,
                       macd, macd_signal, macd_histogram,
                       bollinger_upper, bollinger_middle, bollinger_lower,
                       hurst_exponent, hurst_fast, ou_deviation, regime,
                       returns, momentum_5, volatility_realized, price_position,
                       atr_14
                FROM candles
                WHERE symbol = 'R_100'
                  AND DATE(open_time AT TIME ZONE 'America/Bogota') = :date
                ORDER BY open_time ASC
            ),
            lookback_candles AS (
                SELECT open_time, open, high, low, close,
                       rsi_14, ema_9, ema_21, ema_50,
                       macd, macd_signal, macd_histogram,
                       bollinger_upper, bollinger_middle, bollinger_lower,
                       hurst_exponent, hurst_fast, ou_deviation, regime,
                       returns, momentum_5, volatility_realized, price_position,
                       atr_14
                FROM candles
                WHERE symbol = 'R_100'
                  AND open_time < (SELECT MIN(open_time) FROM date_candles)
                ORDER BY open_time DESC
                LIMIT 300
            )
            SELECT * FROM (SELECT * FROM lookback_candles ORDER BY open_time ASC) lb
            UNION ALL
            SELECT * FROM date_candles
        """), {"date": date}).fetchall()

        # Count lookback vs date candles
        # Find where the selected date starts
        from datetime import datetime as dt
        date_obj = dt.strptime(date, "%Y-%m-%d").date()
        lookback_count = 0
        for row in result:
            # Convert to Colombia time to check date
            from datetime import timedelta
            col_time = row.open_time - timedelta(hours=5) if row.open_time.tzinfo else row.open_time
            if col_time.date() < date_obj:
                lookback_count += 1
            else:
                break
        
        date_candle_count = len(result) - lookback_count
        actual_index = lookback_count + candle_index  # Adjust index for lookback

        if candle_index >= date_candle_count or candle_index < 0:
            return {"action": "HOLD", "confidence": 0, "reason": "insufficient_data"}

        # Build DataFrame up to current index (including lookback)
        columns = [
            'open_time', 'open', 'high', 'low', 'close',
            'rsi_14', 'ema_9', 'ema_21', 'ema_50',
            'macd', 'macd_signal', 'macd_histogram',
            'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
            'hurst_exponent', 'hurst_fast', 'ou_deviation', 'regime',
            'returns', 'momentum_5', 'volatility_realized', 'price_position',
            'atr_14'
        ]
        import pandas as pd
        rows = [dict(zip(columns, row)) for row in result[:actual_index + 1]]
        df = pd.DataFrame(rows)

        numeric_cols = [c for c in columns if c not in ('open_time', 'regime')]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

        # ===== THE SINGLE BRAIN — TradingCore =====
        from app.simulation.trading_core import TradingCore
        result = await TradingCore.analyze_async(
            engine=_get_sim_engine(date, engine_name),
            df=df,
            symbol='R_100',
            use_groq=use_groq,
            ai_provider=ai_provider,
        )
        return result

    except Exception as e:
        from loguru import logger
        logger.error(f"❌ bot-step error: {e}")
        return {"action": "HOLD", "confidence": 0, "error": str(e)}

# ============================================
# AI BATTLE MODE — Compare all providers
# ============================================

@router.post("/simulation/battle")
async def battle(
    date: str = Query(..., description="Date YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    """
    FAST battle mode: uses pre-computed indicators from DB for quick L1 signals,
    then calls all 4 AI providers IN PARALLEL only for trade signals.
    """
    import asyncio
    import pandas as pd
    from loguru import logger
    from datetime import datetime as dt, timedelta

    logger.info(f"🏆 BATTLE MODE started for {date}")

    TRADE_DURATION = 3
    COOLDOWN = 3
    INITIAL_BALANCE = 10000
    PAYOUT = 0.95  # Real Deriv payout ~95%
    STAKE_PCT = 0.01

    # ── Load candles with pre-computed indicators ──
    result = db.execute(text("""
        SELECT open_time, open, high, low, close,
               rsi_14, ema_9, ema_21, ema_50,
               macd, macd_signal, macd_histogram,
               bollinger_upper, bollinger_middle, bollinger_lower,
               hurst_exponent, hurst_fast, ou_deviation, regime,
               returns, momentum_5, volatility_realized, price_position,
               atr_14
        FROM candles
        WHERE symbol = 'R_100'
          AND DATE(open_time AT TIME ZONE 'America/Bogota') = :date
        ORDER BY open_time ASC
    """), {"date": date}).fetchall()

    if not result or len(result) < 30:
        return {"error": "No hay suficientes datos para esta fecha", "results": []}

    columns = [
        'open_time', 'open', 'high', 'low', 'close',
        'rsi_14', 'ema_9', 'ema_21', 'ema_50',
        'macd', 'macd_signal', 'macd_histogram',
        'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
        'hurst_exponent', 'hurst_fast', 'ou_deviation', 'regime',
        'returns', 'momentum_5', 'volatility_realized', 'price_position',
        'atr_14'
    ]
    rows = [dict(zip(columns, row)) for row in result]
    df = pd.DataFrame(rows)
    numeric_cols = [c for c in columns if c not in ('open_time', 'regime')]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

    total_candles = len(df)
    logger.info(f"🏆 Loaded {total_candles} candles for {date}")

    # ── PHASE 1: Quick L1 signal generation using pre-computed indicators ──
    # Instead of running the full L1Engine (~0.5s/candle), we use the DB indicators directly
    l1_signals = []  # [(candle_idx, signal, confidence, entry_price)]

    for i in range(30, total_candles - TRADE_DURATION):
        row = df.iloc[i]
        rsi = float(row['rsi_14'])
        macd_hist = float(row['macd_histogram'])
        hurst = float(row['hurst_exponent'])
        bb_pos = float(row['price_position'])
        ema_9 = float(row['ema_9'])
        ema_21 = float(row['ema_21'])
        ou_dev = float(row['ou_deviation'])
        close = float(row['close'])

        # Quick composite L1 signal (same logic as Layer1SignalEngine but inline)
        score = 0.0
        reasons = []

        # RSI signal
        if rsi < 35:
            score += 0.25
            reasons.append("RSI_oversold")
        elif rsi > 65:
            score -= 0.25
            reasons.append("RSI_overbought")

        # MACD signal
        if macd_hist > 0:
            score += 0.15
        elif macd_hist < 0:
            score -= 0.15

        # EMA trend
        if ema_9 > ema_21:
            score += 0.15
        elif ema_9 < ema_21:
            score -= 0.15

        # Bollinger position
        if bb_pos < 0.2:
            score += 0.20
        elif bb_pos > 0.8:
            score -= 0.20

        # Hurst (trend strength)
        if hurst > 0.6:
            score *= 1.2  # trend-following amplified
        elif hurst < 0.4:
            score *= 0.7  # mean-reverting dampened

        # O-U deviation mean reversion
        if ou_dev < -1.5:
            score += 0.15
        elif ou_dev > 1.5:
            score -= 0.15

        # Determine signal
        confidence = min(abs(score), 1.0)
        if score > 0.15 and confidence >= 0.2:
            l1_signals.append((i, "CALL", confidence, close))
        elif score < -0.15 and confidence >= 0.2:
            l1_signals.append((i, "PUT", confidence, close))

    logger.info(f"🏆 Phase 1 complete: {len(l1_signals)} L1 trade signals from {total_candles} candles")

    # ── Filter signals respecting cooldown ──
    filtered_signals = []
    next_allowed = 0
    for idx, signal, conf, price in l1_signals:
        if idx >= next_allowed:
            filtered_signals.append((idx, signal, conf, price))
            next_allowed = idx + TRADE_DURATION + COOLDOWN

    # Cap at 20 signals max to keep battle under 2 minutes
    MAX_BATTLE_SIGNALS = 10
    if len(filtered_signals) > MAX_BATTLE_SIGNALS:
        # Take evenly spaced signals
        step = len(filtered_signals) // MAX_BATTLE_SIGNALS
        filtered_signals = filtered_signals[::step][:MAX_BATTLE_SIGNALS]

    logger.info(f"🏆 After cooldown filter: {len(filtered_signals)} actionable signals (max {MAX_BATTLE_SIGNALS})")

    # ── PHASE 2: Call ALL 4 AI providers for each filtered signal ──
    async def call_ai(provider_name, l1_signal_dict, candles_for_ai):
        """Call a single AI provider"""
        try:
            from app.analysis.layer2_groq import Layer2GroqEngine
            from app.prompts.trading_system_prompt import get_system_prompt
            from app.analysis.meta_confidence import get_meta_confidence

            layer2 = Layer2GroqEngine.__new__(Layer2GroqEngine)
            layer2.system_prompt = get_system_prompt()
            layer2.meta_confidence = get_meta_confidence()

            if provider_name == "groq":
                from app.analysis.layer2_groq import get_layer2_engine
                layer2 = get_layer2_engine()
            elif provider_name == "openai":
                from app.services.openai_client import get_openai_engine
                layer2.groq = get_openai_engine()
            elif provider_name == "claude":
                from app.services.claude_client import get_claude_engine
                layer2.groq = get_claude_engine()
            elif provider_name == "gemini":
                from app.services.gemini_client import get_gemini_engine
                layer2.groq = get_gemini_engine()

            ai_result = await asyncio.wait_for(
                layer2.analyze(
                    layer1_signal=l1_signal_dict,
                    candles=candles_for_ai,
                    db=None
                ),
                timeout=8.0  # 8 second max per AI call
            )
            decision = ai_result.get("decision", ai_result.get("final_signal", "HOLD"))
            conf = ai_result.get("confidence", ai_result.get("final_confidence", 0.0))
            return {"decision": decision, "confidence": conf}
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Battle AI timeout ({provider_name})")
            return {"decision": "HOLD", "confidence": 0.0, "error": "timeout"}
        except Exception as e:
            logger.warning(f"⚠️ Battle AI error ({provider_name}): {e}")
            return {"decision": "HOLD", "confidence": 0.0, "error": str(e)}

    # Process each signal
    ai_providers = ["groq", "openai", "claude", "gemini"]
    # Results per strategy
    strategy_trades = {
        "L1_Only": [], "L1_Groq": [], "L1_OpenAI": [], "L1_Claude": [], "L1_Gemini": []
    }
    ai_calls_made = 0

    for sig_num, (candle_idx, l1_signal, l1_conf, entry_price) in enumerate(filtered_signals):
        exit_idx = candle_idx + TRADE_DURATION
        if exit_idx >= total_candles:
            continue
        exit_price = float(df.iloc[exit_idx]['close'])

        # L1_Only always takes the trade
        won = (exit_price > entry_price) if l1_signal == "CALL" else (exit_price < entry_price)
        strategy_trades["L1_Only"].append({
            "direction": l1_signal, "won": won, "confidence": l1_conf,
            "entry_price": entry_price, "exit_price": exit_price
        })

        # Build context for AI
        row = df.iloc[candle_idx]
        last_5 = df.iloc[max(0,candle_idx-4):candle_idx+1]['close'].tolist()
        rising = sum(1 for i in range(1, len(last_5)) if last_5[i] > last_5[i-1])
        falling = sum(1 for i in range(1, len(last_5)) if last_5[i] < last_5[i-1])
        price_direction = "RISING" if rising >= 3 else ("FALLING" if falling >= 3 else "MIXED")

        l1_signal_dict = {
            "final_signal": l1_signal,
            "final_confidence": l1_conf,
            "reasoning": f"RSI={row['rsi_14']:.1f}, MACD_H={row['macd_histogram']:.4f}, Hurst={row['hurst_exponent']:.3f}, BB={row['price_position']:.2f}",
            "hurst_signal": {"hurst": float(row['hurst_exponent'])},
            "rsi_signal": {"rsi": float(row['rsi_14']), "signal": "oversold" if row['rsi_14'] < 35 else "overbought" if row['rsi_14'] > 65 else "neutral"},
            "macd_signal": {"histogram": float(row['macd_histogram']), "signal": "bullish" if row['macd_histogram'] > 0 else "bearish"},
            "bollinger_signal": {"position": float(row['price_position'])},
            "ou_signal": {"deviation": float(row['ou_deviation'])},
            "price_direction": price_direction,
            "direction_aligned": (l1_signal == 'CALL' and price_direction == 'RISING') or (l1_signal == 'PUT' and price_direction == 'FALLING'),
            "rsi_extreme": (l1_signal == 'CALL' and float(row['rsi_14']) > 70) or (l1_signal == 'PUT' and float(row['rsi_14']) < 35),
            "last_5_closes": [round(p, 2) for p in last_5]
        }

        # Candle objects for AI
        class SC:
            def __init__(self, r):
                self.open = float(r['open'])
                self.high = float(r['high'])
                self.low = float(r['low'])
                self.close = float(r['close'])

        cs = max(0, candle_idx - 24)
        candles_for_ai = [SC(df.iloc[j]) for j in range(cs, candle_idx + 1)]

        # Call all 4 AIs in parallel
        logger.info(f"🏆 Signal {sig_num+1}/{len(filtered_signals)}: {l1_signal} @ {entry_price:.2f} — calling 4 AIs...")
        ai_calls_made += 4
        tasks = [call_ai(prov, l1_signal_dict, candles_for_ai) for prov in ai_providers]
        ai_results = await asyncio.gather(*tasks, return_exceptions=True)

        for prov, ai_res in zip(ai_providers, ai_results):
            strategy_name = f"L1_{prov.capitalize()}" if prov != "openai" else "L1_OpenAI"
            if isinstance(ai_res, Exception):
                decision = l1_signal  # fallback to L1
            else:
                decision = ai_res.get("decision", "HOLD")
            
            if decision in ["CALL", "PUT"]:
                trade_won = (exit_price > entry_price) if decision == "CALL" else (exit_price < entry_price)
                strategy_trades[strategy_name].append({
                    "direction": decision, "won": trade_won,
                    "confidence": ai_res.get("confidence", 0) if not isinstance(ai_res, Exception) else 0,
                    "entry_price": entry_price, "exit_price": exit_price
                })

    # ── Format results ──
    icons = {"L1_Only": "📊", "L1_Groq": "🟢", "L1_OpenAI": "🔵", "L1_Claude": "🟣", "L1_Gemini": "🟠"}
    battle_results = []
    
    for name in ["L1_Only", "L1_Groq", "L1_OpenAI", "L1_Claude", "L1_Gemini"]:
        trades = strategy_trades[name]
        wins = sum(1 for t in trades if t["won"])
        losses = len(trades) - wins
        
        # Calculate P&L with compounding
        balance = INITIAL_BALANCE
        max_dd = 0
        peak = INITIAL_BALANCE
        total_pnl = 0
        for t in trades:
            stake = balance * STAKE_PCT
            pnl = stake * PAYOUT if t["won"] else -stake
            balance += pnl
            total_pnl += pnl
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        wr = round((wins / len(trades) * 100), 1) if trades else 0
        battle_results.append({
            "strategy": name,
            "icon": icons[name],
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": wr,
            "pnl": round(total_pnl, 2),
            "final_balance": round(balance, 2),
            "max_drawdown": round(max_dd, 1)
        })

    battle_results.sort(key=lambda x: x["pnl"], reverse=True)

    logger.info(f"🏆 BATTLE complete: {date} | {len(filtered_signals)} signals | {ai_calls_made} AI calls")
    for r in battle_results:
        logger.info(f"   {r['icon']} {r['strategy']}: {r['total_trades']}T, {r['win_rate']}% WR, ${r['pnl']}")

    return {
        "date": date,
        "total_candles": total_candles,
        "l1_signals": len(filtered_signals),
        "ai_calls": ai_calls_made,
        "results": battle_results
    }


# ============================================
# SIMULATION PERSISTENCE (save results to DB)
# ============================================

@router.post("/simulation/start-run")
def start_simulation_run(
    date: str = Query(...),
    strategy: str = Query("L1_Only", description="Strategy name: L1_Only or L1_Groq"),
    db: Session = Depends(get_db)
):
    """Create a new simulation run record and return its ID"""
    result = db.execute(text("""
        INSERT INTO simulation_runs (strategy_name, start_date, end_date, initial_balance, status, started_at)
        VALUES (:strategy, :date, :date, 10000, 'RUNNING', NOW())
        RETURNING id
    """), {"strategy": strategy, "date": date})
    db.commit()
    run_id = result.fetchone()[0]
    
    # Reset the simulation engine for the new date
    global _sim_engine, _sim_engine_date
    _sim_engine = None
    _sim_engine_date = None
    
    return {"run_id": run_id}


@router.post("/simulation/save-trade")
def save_simulation_trade(
    run_id: int = Query(...),
    entry_time: str = Query(...),
    exit_time: str = Query(None),
    direction: str = Query(...),
    entry_price: float = Query(...),
    exit_price: float = Query(None),
    stake: float = Query(120),
    outcome: str = Query(...),
    profit_loss: float = Query(...),
    balance_after: float = Query(...),
    confidence: float = Query(...),
    reasoning: str = Query(""),
    hurst: float = Query(None),
    groq_used: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Save a single simulation trade result"""
    db.execute(text("""
        INSERT INTO simulation_trades 
        (run_id, entry_time, exit_time, direction, entry_price, exit_price, 
         stake, outcome, profit_loss, balance_after, confidence, reasoning)
        VALUES (:run_id, :entry_time, :exit_time, :direction, :entry_price, :exit_price,
                :stake, :outcome, :profit_loss, :balance_after, :confidence, :reasoning)
    """), {
        "run_id": run_id,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stake": stake,
        "outcome": outcome,
        "profit_loss": profit_loss,
        "balance_after": balance_after,
        "confidence": round(confidence, 2),
        "reasoning": f"hurst={hurst} groq={groq_used} {reasoning[:500]}"
    })
    db.commit()
    return {"status": "saved"}


@router.post("/simulation/finish-run")
def finish_simulation_run(
    run_id: int = Query(...),
    total_trades: int = Query(0),
    winning_trades: int = Query(0),
    losing_trades: int = Query(0),
    win_rate: float = Query(0),
    total_pnl: float = Query(0),
    max_drawdown_pct: float = Query(0),
    final_balance: float = Query(10000),
    db: Session = Depends(get_db)
):
    """Finalize a simulation run with summary stats"""
    db.execute(text("""
        UPDATE simulation_runs 
        SET total_trades = :total_trades, winning_trades = :winning_trades,
            losing_trades = :losing_trades, win_rate = :win_rate,
            total_pnl = :total_pnl, max_drawdown_pct = :max_drawdown_pct,
            final_balance = :final_balance, status = 'COMPLETED', completed_at = NOW()
        WHERE id = :run_id
    """), {
        "run_id": run_id, "total_trades": total_trades,
        "winning_trades": winning_trades, "losing_trades": losing_trades,
        "win_rate": win_rate, "total_pnl": total_pnl,
        "max_drawdown_pct": max_drawdown_pct, "final_balance": final_balance
    })
    db.commit()
    return {"status": "completed"}


@router.get("/simulation/run-results")
def get_simulation_results(
    run_id: int = Query(None),
    date: str = Query(None),
    db: Session = Depends(get_db)
):
    """Get simulation trades for analysis"""
    if run_id:
        trades = db.execute(text("""
            SELECT st.*, sr.strategy_name, sr.start_date
            FROM simulation_trades st
            JOIN simulation_runs sr ON st.run_id = sr.id
            WHERE st.run_id = :run_id
            ORDER BY st.entry_time ASC
        """), {"run_id": run_id}).fetchall()
    elif date:
        trades = db.execute(text("""
            SELECT st.*, sr.strategy_name, sr.start_date
            FROM simulation_trades st
            JOIN simulation_runs sr ON st.run_id = sr.id
            WHERE DATE(sr.start_date) = :date
            ORDER BY sr.id DESC, st.entry_time ASC
        """), {"date": date}).fetchall()
    else:
        return {"error": "Provide run_id or date"}
    
    return {
        "trades": [{
            "id": t.id, "run_id": t.run_id, "strategy": t.strategy_name,
            "entry_time": str(t.entry_time), "exit_time": str(t.exit_time),
            "direction": t.direction, "entry_price": float(t.entry_price or 0),
            "exit_price": float(t.exit_price or 0), "outcome": t.outcome,
            "profit_loss": float(t.profit_loss or 0),
            "balance_after": float(t.balance_after or 0),
            "confidence": float(t.confidence or 0),
            "reasoning": t.reasoning
        } for t in trades],
        "total": len(trades)
    }


# ============================================
# ENGINE BATTLE — Run all 4 engines in parallel
# ============================================

_engine_battle_status = {
    "running": False,
    "cancel": False,
    "engines": {},   # engine_name -> {status, progress, total_days, result}
    "winner": None,
    "error": None,
}

ENGINE_LIST = [
    {"name": "bullish_v5", "icon": "🐂", "label": "Ultimate Bull v5"},
    {"name": "bear_reject_v1", "icon": "🔴", "label": "Three Red Crows"},
    {"name": "bull_soldiers_v1", "icon": "🟢", "label": "Three White Soldiers"},
]


def _run_engine_sim(engine_name: str, dates: list, config: dict):
    """Run simulation for a single engine across multiple dates"""
    global _engine_battle_status
    from app.simulation.replay_bot import ReplayBotSimulator
    from app.analysis.engine_registry import get_engine_config
    from loguru import logger

    engine_status = _engine_battle_status["engines"][engine_name]
    engine_status["status"] = "running"

    # Get per-engine hurst config from registry
    engine_cfg = get_engine_config(engine_name) or {}

    db = SessionLocal()
    try:
        balance = config.get("initial_balance", 10000.0)
        peak_balance = balance
        max_dd_pct = 0
        total_trades = 0
        total_wins = 0
        total_losses = 0
        cumulative_pnl = 0
        all_trades = []  # Collect all individual trades

        for i, date_str in enumerate(dates):
            if _engine_battle_status.get("cancel"):
                engine_status["status"] = "cancelled"
                return

            engine_status["progress"] = i
            engine_status["current_date"] = date_str

            try:
                # Build per-engine config from registry (single source of truth)
                defensive = engine_cfg.get("defensive", {})
                day_config = {
                    "stake": config.get("stake", 60.0),
                    "min_confidence": engine_cfg.get("confidence_min", config.get("min_confidence", 0.60)),
                    "max_confidence": engine_cfg.get("confidence_max", config.get("max_confidence", 1.0)),
                    "payout_rate": 0.95,
                    "duration_candles": engine_cfg.get("duration_candles", 5),
                    "initial_balance": balance,
                    "cooldown_candles": defensive.get("cooldown_candles", 3),
                    "use_groq": False,
                    "engine_name": engine_name,
                    "hurst_min": engine_cfg.get("hurst_min", config.get("hurst_min", 0.6)),
                    "hurst_max": engine_cfg.get("hurst_max", config.get("hurst_max", 0.7)),
                    "slope_min": engine_cfg.get("slope_min", 0.0),
                    "slope_lookback": engine_cfg.get("slope_lookback", 20),
                    # Merge ALL defensive filters from registry
                    **{k: v for k, v in defensive.items()},
                }
                simulator = ReplayBotSimulator(config=day_config)
                result = simulator.run(db, date_str)

                if "error" in result:
                    continue

                day_summary = result.get("summary", result)
                day_pnl = day_summary.get("total_pnl", 0)
                day_trades = day_summary.get("total_trades", 0)
                day_wins = day_summary.get("wins", 0)
                day_losses = day_summary.get("losses", 0)

                # Collect individual trades with date tag
                day_trade_list = result.get("trades", [])
                for t in day_trade_list:
                    t["trade_date"] = date_str
                all_trades.extend(day_trade_list)

                balance += day_pnl
                cumulative_pnl += day_pnl
                total_trades += day_trades
                total_wins += day_wins
                total_losses += day_losses

                if balance > peak_balance:
                    peak_balance = balance
                dd = (peak_balance - balance) / peak_balance * 100 if peak_balance > 0 else 0
                if dd > max_dd_pct:
                    max_dd_pct = dd

            except Exception as day_err:
                logger.warning(f"⚔️ Engine {engine_name} day {date_str} error (skipping): {day_err}")
                continue

        overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
        engine_status["status"] = "completed"
        engine_status["progress"] = len(dates)
        engine_status["result"] = {
            "engine": engine_name,
            "total_trades": total_trades,
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": round(overall_wr, 1),
            "total_pnl": round(cumulative_pnl, 2),
            "final_balance": round(balance, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "roi_pct": round(cumulative_pnl / config.get("initial_balance", 10000.0) * 100, 2),
            "_all_trades": all_trades,  # Internal: used by coordinator for DB persistence
        }
        logger.info(f"⚔️ Engine {engine_name} finished: {total_trades} trades, PnL=${cumulative_pnl:.2f}")

    except Exception as e:
        import traceback
        engine_status["status"] = "error"
        engine_status["error"] = str(e)
        logger.error(f"⚔️ Engine {engine_name} failed: {e}\n{traceback.format_exc()}")
    finally:
        db.close()


def _run_engine_battle_coordinator(dates: list, config: dict):
    """Coordinator: launches all 4 engines in parallel and waits for completion"""
    global _engine_battle_status
    import concurrent.futures
    import uuid
    import json
    from loguru import logger

    battle_id = str(uuid.uuid4())[:12]
    _engine_battle_status["battle_id"] = battle_id
    _engine_battle_status["_dates"] = dates
    _engine_battle_status["_config"] = config

    try:
        # Run engines concurrently (up to length of ENGINE_LIST to prevent hanging in queue)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ENGINE_LIST)) as executor:
            futures = {}
            for eng in ENGINE_LIST:
                future = executor.submit(_run_engine_sim, eng["name"], dates, config)
                futures[eng["name"]] = future

            # Wait for all to complete
            concurrent.futures.wait(futures.values())

        # Determine winner
        results = []
        for eng in ENGINE_LIST:
            es = _engine_battle_status["engines"].get(eng["name"], {})
            if es.get("result"):
                r = es["result"]
                r["icon"] = eng["icon"]
                r["label"] = eng["label"]
                results.append(r)

        # Sort by PnL descending
        results.sort(key=lambda x: x["total_pnl"], reverse=True)
        if results:
            _engine_battle_status["winner"] = results[0]["engine"]
        _engine_battle_status["results"] = results
        logger.info(f"⚔️ Battle complete! Winner: {_engine_battle_status.get('winner')}")

        # ===== PERSIST TO DATABASE =====
        try:
            from app.core.database import SessionLocal
            db = SessionLocal()
            for rank, r in enumerate(results, 1):
                db.execute(text("""
                    INSERT INTO engine_battle_results
                    (battle_id, engine_name, rank, total_days, total_trades, wins, losses,
                     win_rate, total_pnl, max_drawdown, final_balance, start_date, end_date, config)
                    VALUES (:battle_id, :engine_name, :rank, :total_days, :total_trades, :wins, :losses,
                            :win_rate, :total_pnl, :max_drawdown, :final_balance, :start_date, :end_date, CAST(:config AS jsonb))
                """), {
                    "battle_id": battle_id,
                    "engine_name": r["engine"],
                    "rank": rank,
                    "total_days": len(dates),
                    "total_trades": r.get("total_trades", 0),
                    "wins": r.get("wins", 0),
                    "losses": r.get("losses", 0),
                    "win_rate": r.get("win_rate", 0),
                    "total_pnl": r.get("total_pnl", 0),
                    "max_drawdown": r.get("max_drawdown_pct", 0),
                    "final_balance": r.get("final_balance", 10000),
                    "start_date": dates[0] if dates else None,
                    "end_date": dates[-1] if dates else None,
                    "config": json.dumps({
                        "confidence": config.get("min_confidence"),
                        "max_confidence": config.get("max_confidence"),
                        "hurst_min": config.get("hurst_min"),
                        "hurst_max": config.get("hurst_max"),
                        "blocked_hours": config.get("blocked_hours", []),
                        "stake": config.get("stake"),
                    }),
                })

                # Save individual trades
                all_trades = r.pop("_all_trades", [])
                for t in all_trades:
                    db.execute(text("""
                        INSERT INTO engine_battle_trades
                        (battle_id, engine_name, trade_date, trade_time, direction, stake,
                         entry_price, exit_price, result, pnl, balance_after, confidence,
                         l1_signal, l1_confidence, reasoning,
                         hurst, rsi_14, ema_9, ema_21, macd_histogram, bb_width)
                        VALUES (:battle_id, :engine_name, :trade_date, :trade_time, :direction, :stake,
                                :entry_price, :exit_price, :result, :pnl, :balance_after, :confidence,
                                :l1_signal, :l1_confidence, :reasoning,
                                :hurst, :rsi_14, :ema_9, :ema_21, :macd_histogram, :bb_width)
                    """), {
                        "battle_id": battle_id,
                        "engine_name": r["engine"],
                        "trade_date": t.get("trade_date"),
                        "trade_time": t.get("time"),
                        "direction": t.get("direction"),
                        "stake": t.get("stake"),
                        "entry_price": t.get("entry_price"),
                        "exit_price": t.get("exit_price"),
                        "result": t.get("result"),
                        "pnl": t.get("pnl"),
                        "balance_after": t.get("balance_after"),
                        "confidence": t.get("confidence"),
                        "l1_signal": t.get("l1_signal"),
                        "l1_confidence": t.get("l1_confidence"),
                        "reasoning": (t.get("reasoning") or "")[:500],
                        "hurst": t.get("hurst"),
                        "rsi_14": t.get("rsi_14"),
                        "ema_9": t.get("ema_9"),
                        "ema_21": t.get("ema_21"),
                        "macd_histogram": t.get("macd_histogram"),
                        "bb_width": t.get("bb_width"),
                    })

            db.commit()
            trade_count = sum(len(r.get("_all_trades", [])) for r in results)
            db.close()
            logger.info(f"💾 Battle {battle_id} saved: {len(results)} engines, trades persisted")
        except Exception as db_err:
            logger.error(f"💾 Failed to save battle results: {db_err}")

    except Exception as e:
        _engine_battle_status["error"] = str(e)
        logger.error(f"⚔️ Battle coordinator error: {e}")
    finally:
        _engine_battle_status["running"] = False


@router.post("/simulation/engine-battle")
def start_engine_battle(
    start_date: str = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(None, description="End date (YYYY-MM-DD)"),
    confidence: float = Query(0.60),
    max_confidence: float = Query(1.0),
    hurst_min: float = Query(0.0),
    hurst_max: float = Query(1.0),
    blocked_hours: str = Query(""),
    db: Session = Depends(get_db),
):
    """Run all 4 analysis engines on the same date range in parallel"""
    global _engine_battle_status

    if _engine_battle_status["running"]:
        return {"status": "already_running"}

    # Build date list
    date_filter = ""
    params = {}
    if start_date:
        date_filter += " AND DATE(open_time AT TIME ZONE 'America/Bogota') >= :start"
        params["start"] = start_date
    if end_date:
        date_filter += " AND DATE(open_time AT TIME ZONE 'America/Bogota') <= :end"
        params["end"] = end_date

    result = db.execute(text(f"""
        SELECT DATE(open_time AT TIME ZONE 'America/Bogota') as d, COUNT(*) as cnt
        FROM candles WHERE symbol = 'R_100' {date_filter}
        GROUP BY d HAVING COUNT(*) >= 100
        ORDER BY d ASC
    """), params).fetchall()

    dates = [str(row.d) for row in result]
    if not dates:
        return {"status": "error", "message": "No hay días con datos suficientes en ese rango"}

    config = {
        "stake": 60.0,
        "min_confidence": confidence,
        "max_confidence": max_confidence,
        "payout_rate": 0.95,
        "duration_candles": engine_cfg.get("duration_candles", 5) if 'engine_cfg' in dir() else 5,
        "initial_balance": 10000.0,
        "cooldown_candles": 1,
        "use_groq": False,
        "hurst_min": hurst_min,
        "hurst_max": hurst_max,
        "blocked_hours": [int(h.strip()) for h in blocked_hours.split(',') if h.strip()] if blocked_hours else [],
    }

    # Init status
    _engine_battle_status = {
        "running": True,
        "cancel": False,
        "total_days": len(dates),
        "engines": {
            eng["name"]: {
                "status": "queued",
                "progress": 0,
                "total_days": len(dates),
                "current_date": None,
                "icon": eng["icon"],
                "label": eng["label"],
                "result": None,
                "error": None,
            } for eng in ENGINE_LIST
        },
        "winner": None,
        "results": [],
        "error": None,
    }

    thread = threading.Thread(target=_run_engine_battle_coordinator, args=(dates, config))
    thread.daemon = True
    thread.start()

    return {"status": "started", "total_days": len(dates), "engines": [e["name"] for e in ENGINE_LIST]}


@router.get("/simulation/engine-battle-status")
def engine_battle_status():
    """Get status of running engine battle"""
    return _engine_battle_status


@router.post("/simulation/engine-battle-retry/{engine_name}")
def engine_battle_retry(engine_name: str):
    """Retry a failed engine within an active battle without stopping others"""
    global _engine_battle_status
    import threading

    if not _engine_battle_status.get("running"):
        return {"status": "error", "message": "No battle is running"}

    engines = _engine_battle_status.get("engines", {})
    if engine_name not in engines:
        return {"status": "error", "message": f"Engine '{engine_name}' not in current battle"}

    eng_status = engines[engine_name]
    if eng_status.get("status") not in ("error", "completed"):
        return {"status": "error", "message": f"Engine '{engine_name}' is still running (status: {eng_status.get('status')})"}

    # Get the dates and config from the current battle
    dates = _engine_battle_status.get("_dates", [])
    config = _engine_battle_status.get("_config", {})

    if not dates:
        return {"status": "error", "message": "Cannot determine dates for retry"}

    # Reset engine status
    total_days = len(dates)
    engines[engine_name] = {
        "status": "running",
        "progress": 0,
        "total_days": total_days,
        "current_date": str(dates[0]) if dates else "",
        "icon": eng_status.get("icon", ""),
        "label": eng_status.get("label", ""),
        "result": None,
        "error": None,
    }

    # Launch in background thread
    thread = threading.Thread(
        target=_run_engine_sim,
        args=(engine_name, dates, config),
        daemon=True
    )
    thread.start()

    logger.info(f"🔄 Retrying engine {engine_name} ({total_days} days)")
    return {"status": "retrying", "engine": engine_name, "total_days": total_days}


@router.post("/simulation/engine-battle-stop")
def engine_battle_stop():
    """Stop a running engine battle"""
    global _engine_battle_status
    if _engine_battle_status["running"]:
        _engine_battle_status["cancel"] = True
        return {"status": "stopping"}
    return {"status": "not_running"}


@router.get("/simulation/engine-battle-history")
def engine_battle_history(
    limit: int = Query(20, description="Number of battles to return"),
    db: Session = Depends(get_db),
):
    """Get past engine battle results for analysis"""
    battles = db.execute(text("""
        SELECT battle_id, engine_name, rank, total_days, total_trades,
               wins, losses, win_rate, total_pnl, max_drawdown,
               final_balance, start_date, end_date, config, created_at
        FROM engine_battle_results
        ORDER BY created_at DESC, rank ASC
        LIMIT :limit
    """), {"limit": limit * 7}).fetchall()  # 7 engines per battle

    if not battles:
        return {"battles": [], "total": 0}

    # Group by battle_id
    grouped = {}
    for b in battles:
        bid = b.battle_id
        if bid not in grouped:
            grouped[bid] = {
                "battle_id": bid,
                "start_date": str(b.start_date),
                "end_date": str(b.end_date),
                "total_days": b.total_days,
                "config": b.config,
                "created_at": str(b.created_at),
                "engines": [],
            }
        grouped[bid]["engines"].append({
            "engine_name": b.engine_name,
            "rank": b.rank,
            "total_trades": b.total_trades,
            "wins": b.wins,
            "losses": b.losses,
            "win_rate": float(b.win_rate) if b.win_rate else 0,
            "total_pnl": float(b.total_pnl) if b.total_pnl else 0,
            "max_drawdown": float(b.max_drawdown) if b.max_drawdown else 0,
            "final_balance": float(b.final_balance) if b.final_balance else 0,
        })

    return {"battles": list(grouped.values()), "total": len(grouped)}


@router.get("/simulation/engine-battle-daily/{battle_id}/{engine_name}")
def engine_battle_daily(
    battle_id: str,
    engine_name: str,
    db: Session = Depends(get_db),
):
    """Get day-by-day breakdown for a specific engine in a battle"""
    rows = db.execute(text("""
        SELECT trade_date,
               COUNT(*) as trades,
               SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) as losses,
               ROUND(SUM(pnl)::numeric, 2) as day_pnl,
               ROUND(AVG(confidence)::numeric, 3) as avg_confidence,
               MAX(balance_after) as end_balance
        FROM engine_battle_trades
        WHERE battle_id = :bid AND engine_name = :eng
        GROUP BY trade_date
        ORDER BY trade_date ASC
    """), {"bid": battle_id, "eng": engine_name}).fetchall()

    days = []
    for r in rows:
        trades = int(r.trades)
        wins = int(r.wins)
        wr = round(wins / trades * 100, 1) if trades > 0 else 0
        days.append({
            "date": str(r.trade_date),
            "trades": trades,
            "wins": wins,
            "losses": int(r.losses),
            "win_rate": wr,
            "pnl": float(r.day_pnl) if r.day_pnl else 0,
            "avg_confidence": float(r.avg_confidence) if r.avg_confidence else 0,
            "end_balance": float(r.end_balance) if r.end_balance else 0,
        })

    return {"battle_id": battle_id, "engine_name": engine_name, "days": days}
