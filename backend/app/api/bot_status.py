"""
API Routes for Bot Status and Trading Data
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone

from app.core.database import get_db
from app.core.config import get_settings
from app.models.models import BotState, Trade, Candle

settings = get_settings()

router = APIRouter()

# Module-level active engines list (avoids Pydantic Settings restriction)
_active_engines = [settings.ENGINE_NAME]
_latest_engine_decisions = {}  # Updated by bot.py each tick


@router.get("/status")
async def get_bot_status(db: Session = Depends(get_db)):
    """
    Get current bot status and state
    """
    try:
        bot_state = db.query(BotState).filter(BotState.id == 1).first()
        
        if not bot_state:
            # Return default values if no state exists yet
            return {
                "status": "initializing",
                "symbol": "R_100",
                "balance": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "pending_trades": 0,
                "win_rate": 0,
                "daily_pnl": 0.0,
                "is_trading": True,
                "current_price": 0.0,
                "last_updated": None
            }
        
        # Get trade statistics
        total_trades = db.query(Trade).count()
        winning_trades = db.query(Trade).filter(Trade.outcome == "WIN").count()
        losing_trades = db.query(Trade).filter(Trade.outcome == "LOSS").count()
        pending_trades = db.query(Trade).filter(Trade.outcome == "PENDING").count()
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Get latest candle for current price
        latest_candle = db.query(Candle).order_by(Candle.open_time.desc()).first()
        current_price = latest_candle.close if latest_candle else 0
        
        # Get latest candle age for health monitoring
        candle_age_seconds = None
        candle_is_stale = True
        if latest_candle and latest_candle.open_time:
            candle_age_seconds = int((datetime.now(timezone.utc) - latest_candle.open_time.replace(tzinfo=timezone.utc)).total_seconds())
            candle_is_stale = candle_age_seconds > 600  # 10 minutes
        
        response = {
            "status": "running",
            "symbol": "R_100",
            "balance": float(bot_state.balance),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "pending_trades": pending_trades,
            "win_rate": round(win_rate, 2),
            "daily_pnl": float(bot_state.daily_pnl) if bot_state.daily_pnl else 0.0,
            "is_trading": bool(bot_state.is_trading_enabled),
            "current_price": float(current_price) if current_price else 0.0,
            "trades_today": bot_state.trades_today,
            "wins_today": bot_state.wins_today,
            "losses_today": bot_state.losses_today,
            "last_updated": bot_state.updated_at.isoformat() if bot_state.updated_at else None,
            "account_type": settings.DERIV_ACCOUNT_TYPE.upper(),
            "engine_name": settings.ENGINE_NAME,
            "active_engines": _active_engines,
            "cooldown_until": bot_state.cooldown_until.isoformat() if bot_state.cooldown_until else None,
            "cooldown_reason": bot_state.cooldown_reason,
            
            # Risk management info
            "risk": {
                "peak_balance": float(bot_state.peak_balance) if bot_state.peak_balance else float(bot_state.balance),
                "drawdown_pct": round(float(bot_state.current_drawdown_pct), 1) if bot_state.current_drawdown_pct else 0.0,
                "max_drawdown_limit": settings.MAX_DRAWDOWN_PCT,
                "is_blocked": float(bot_state.current_drawdown_pct or 0) >= settings.MAX_DRAWDOWN_PCT,
                "consecutive_losses": bot_state.losses_consecutive or 0,
                "cooldown_active": bot_state.cooldown_until > datetime.now(timezone.utc) if bot_state.cooldown_until else False
            },
            
            # Candle data health
            "candle_health": {
                "latest_candle_time": latest_candle.open_time.isoformat() if latest_candle and latest_candle.open_time else None,
                "age_seconds": candle_age_seconds,
                "age_minutes": round(candle_age_seconds / 60, 1) if candle_age_seconds else None,
                "is_stale": candle_is_stale,
            }
        }

        # Fetch latest Layer 2 analysis
        from app.models.models import GroqDecisionLog
        latest_l2 = db.query(GroqDecisionLog).order_by(GroqDecisionLog.created_at.desc()).first()
        
        if latest_l2:
            import json
            try:
                reasoning_json = json.loads(latest_l2.reasoning) if latest_l2.reasoning else {}
                # Extract summary from reasoning chain (try step 6 or 7)
                summary = reasoning_json.get('step6_decision_rationale') or \
                          reasoning_json.get('step6_final_decision_rationale') or \
                          reasoning_json.get('step7_confidence_justification') or \
                          'No summary available'
            except:
                summary = "Reasoning parsing failed"

            response["layer2"] = {
                "active": True,
                "decision": latest_l2.decision,
                "confidence": float(latest_l2.confidence) if latest_l2.confidence else 0.0,
                "reasoning": summary,
                "meta_score": float(latest_l2.meta_confidence_score) if latest_l2.meta_confidence_score else 0.5,
                "last_run": latest_l2.created_at.isoformat()
            }
        else:
            response["layer2"] = {
                "active": False,
                "decision": "WAITING",
                "confidence": 0.0,
                "reasoning": "Waiting for first analysis...",
                "meta_score": 0.5,
                "last_run": None
            }
            
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching bot status: {str(e)}")


@router.post("/reset-risk")
async def reset_risk_state(db: Session = Depends(get_db)):
    """
    Reset risk management state:
    - Peak balance → current balance (clears drawdown)
    - Consecutive losses → 0
    - Cooldown cleared
    - Daily PnL → 0
    """
    try:
        bot_state = db.query(BotState).filter(BotState.id == 1).first()
        if not bot_state:
            raise HTTPException(status_code=404, detail="Bot state not found")
        
        old_drawdown = float(bot_state.current_drawdown_pct or 0)
        old_peak = float(bot_state.peak_balance or 0)
        
        bot_state.peak_balance = bot_state.balance
        bot_state.current_drawdown_pct = 0.0
        bot_state.losses_consecutive = 0
        bot_state.cooldown_until = None
        bot_state.cooldown_reason = None
        bot_state.daily_pnl = 0
        bot_state.trades_today = 0
        bot_state.wins_today = 0
        bot_state.losses_today = 0
        db.commit()
        
        return {
            "status": "ok",
            "message": "Risk state reset successfully",
            "old_peak": old_peak,
            "new_peak": float(bot_state.balance),
            "old_drawdown": round(old_drawdown, 1),
            "new_drawdown": 0.0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resetting risk state: {str(e)}")


@router.get("/engine")
async def get_engine_info():
    """Get current engine and available engines"""
    from app.analysis.engine_registry import _ENGINES
    return {
        "current": settings.ENGINE_NAME,
        "available": list(_ENGINES.keys()),
        "active_engines": _active_engines,
    }


@router.post("/engine/{engine_name}")
async def switch_engine(engine_name: str, db: Session = Depends(get_db)):
    """Switch the live bot's engine at runtime and persist to DB"""
    from app.analysis.engine_registry import _ENGINES, get_engine
    from sqlalchemy import text
    
    if engine_name not in _ENGINES:
        raise HTTPException(status_code=400, detail=f"Unknown engine: {engine_name}. Available: {list(_ENGINES.keys())}")
    
    # Update in memory
    settings.ENGINE_NAME = engine_name
    
    # Persist to DB
    db.execute(text("""
        INSERT INTO bot_settings (key, value, updated_at) 
        VALUES ('engine_name', :engine, NOW())
        ON CONFLICT (key) DO UPDATE SET value = :engine, updated_at = NOW()
    """), {"engine": engine_name})
    db.commit()
    
    return {
        "status": "ok",
        "engine": engine_name,
        "message": f"Engine switched to {engine_name}. Saved to DB."
    }


# ===== MULTI-ENGINE PARALLEL SYSTEM =====

@router.get("/engines/active")
async def get_active_engines(db: Session = Depends(get_db)):
    """Get list of active engines running in parallel"""
    import json as _json
    from sqlalchemy import text
    from app.analysis.engine_registry import _ENGINES
    
    row = db.execute(text("SELECT value FROM bot_settings WHERE key = 'active_engines'")).fetchone()
    if row:
        active = _json.loads(row[0])
    else:
        active = [settings.ENGINE_NAME]
    
    # Ensure all active engines still exist
    active = [e for e in active if e in _ENGINES]
    if not active:
        active = [settings.ENGINE_NAME]
    
    # Update in-memory
    global _active_engines
    _active_engines = active
    
    return {
        "active_engines": active,
        "available": [
            {"name": name, "description": cfg.get("description", name), "version": cfg.get("version", "?")}
            for name, cfg in _ENGINES.items()
        ]
    }


@router.post("/engines/toggle/{engine_name}")
async def toggle_engine(engine_name: str, db: Session = Depends(get_db)):
    """Toggle an engine on/off in the parallel engine list"""
    import json as _json
    from sqlalchemy import text
    from app.analysis.engine_registry import _ENGINES
    
    if engine_name not in _ENGINES:
        raise HTTPException(status_code=400, detail=f"Unknown engine: {engine_name}")
    
    # Load current active list
    row = db.execute(text("SELECT value FROM bot_settings WHERE key = 'active_engines'")).fetchone()
    if row:
        active = _json.loads(row[0])
    else:
        active = [settings.ENGINE_NAME]
    
    # Toggle
    if engine_name in active:
        if len(active) <= 1:
            raise HTTPException(status_code=400, detail="Cannot disable last engine — at least one must be active")
        active.remove(engine_name)
        action = "disabled"
    else:
        active.append(engine_name)
        action = "enabled"
    
    # Persist
    active_json = _json.dumps(active)
    db.execute(text("""
        INSERT INTO bot_settings (key, value, updated_at)
        VALUES ('active_engines', :val, NOW())
        ON CONFLICT (key) DO UPDATE SET value = :val, updated_at = NOW()
    """), {"val": active_json})
    db.commit()
    
    # Update in-memory
    global _active_engines
    _active_engines = active
    settings.ENGINE_NAME = active[0]  # Primary engine = first active
    
    return {
        "status": "ok",
        "action": action,
        "engine": engine_name,
        "active_engines": active,
        "message": f"Engine {engine_name} {action}. Active: {active}"
    }

@router.get("/engines/decisions")
async def get_engine_decisions():
    """Get latest decisions from all active engines (updated each tick by bot.py)"""
    from app.analysis.engine_registry import _ENGINES
    return {
        "active_engines": _active_engines,
        "decisions": _latest_engine_decisions,
        "available": {
            name: {"description": cfg.get("description", name), "version": cfg.get("version", "?")}
            for name, cfg in _ENGINES.items()
        }
    }

@router.get("/candles-with-indicators")
async def get_candles_with_indicators(start_date: str = None, end_date: str = None, db: Session = Depends(get_db)):
    """Get candles with EMA/BB/RSI indicators for chart overlays."""
    try:
        from sqlalchemy import text
        if not start_date or not end_date:
            return []
        rows = db.execute(text("""
            SELECT open_time, close,
                   ema_21, ema_50, bollinger_upper, bollinger_lower, rsi_14
            FROM candles
            WHERE symbol = 'R_100'
              AND open_time >= CAST(:start_date AS timestamp)
              AND open_time < (CAST(:end_date AS timestamp) + interval '1 day')
            ORDER BY open_time ASC
        """), {"start_date": start_date, "end_date": end_date}).fetchall()
        return [
            {
                "time": int(r.open_time.timestamp()),
                "ema_21": float(r.ema_21) if r.ema_21 else None,
                "ema_50": float(r.ema_50) if r.ema_50 else None,
                "bollinger_upper": float(r.bollinger_upper) if r.bollinger_upper else None,
                "bollinger_lower": float(r.bollinger_lower) if r.bollinger_lower else None,
                "rsi_14": float(r.rsi_14) if r.rsi_14 else None,
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/candles")
async def get_candles(limit: int = 200, start_date: str = None, end_date: str = None, db: Session = Depends(get_db)):
    """
    Get candles for charting. Supports date range filtering.
    start_date/end_date format: YYYY-MM-DD
    """
    try:
        from sqlalchemy import text
        
        if start_date and end_date:
            # Date range mode
            candles_rows = db.execute(text("""
                SELECT open_time, open, high, low, close, volume
                FROM candles
                WHERE symbol = 'R_100'
                  AND open_time >= CAST(:start_date AS timestamp)
                  AND open_time < (CAST(:end_date AS timestamp) + interval '1 day')
                ORDER BY open_time ASC
            """), {"start_date": start_date, "end_date": end_date}).fetchall()
            return [
                {
                    "time": int(r.open_time.timestamp()),
                    "open": float(r.open),
                    "high": float(r.high),
                    "low": float(r.low),
                    "close": float(r.close),
                    "volume": int(r.volume) if r.volume else 0
                }
                for r in candles_rows
            ]
        else:
            # Default: latest N candles
            candles = db.query(Candle).order_by(Candle.open_time.desc()).limit(limit).all()
            candles.reverse()
            return [
                {
                    "time": int(candle.open_time.timestamp()),
                    "open": float(candle.open),
                    "high": float(candle.high),
                    "low": float(candle.low),
                    "close": float(candle.close),
                    "volume": int(candle.volume) if candle.volume else 0
                }
                for candle in candles
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching candles: {str(e)}")


@router.get("/historical-candles")
async def get_historical_candles(limit: int = 500, db: Session = Depends(get_db)):
    """
    Get historical candles for backtesting simulation chart
    """
    try:
        from sqlalchemy import text
        
        # Query historical_candles table directly
        query = text("""
            SELECT open_time, open, high, low, close, volume
            FROM historical_candles
            ORDER BY open_time DESC
            LIMIT :limit
        """)
        
        result = db.execute(query, {"limit": limit})
        candles = result.fetchall()
        
        # Reverse to chronological order and format
        candles_list = [
            {
                "time": int(row[0].timestamp()),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(row[5]) if row[5] else 0
            }
            for row in reversed(candles)
        ]
        
        return candles_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching historical candles: {str(e)}")


@router.get("/analysis-history")
async def get_analysis_history(limit: int = 300, start_date: str = None, end_date: str = None, db: Session = Depends(get_db)):
    """
    Get historical analysis data for chart indicators overlay.
    Hurst/OU from candles (per-minute, smooth), signals from AnalysisHistory.
    Uses forward-fill so NULL candles inherit the last known Hurst value.
    Supports date range filtering via start_date/end_date (YYYY-MM-DD).
    """
    try:
        from sqlalchemy import text
        
        if start_date and end_date:
            # Date range mode
            rows = db.execute(text("""
                SELECT 
                    c.open_time, c.close, 
                    c.hurst_exponent, c.hurst_fast, c.regime, c.ou_deviation,
                    a.ou_signal, a.final_signal, a.final_confidence, a.duration
                FROM candles c
                LEFT JOIN analysis_history a 
                    ON a.timestamp >= c.open_time 
                    AND a.timestamp < c.open_time + interval '1 minute'
                WHERE c.symbol = 'R_100'
                  AND c.open_time >= CAST(:start_date AS timestamp)
                  AND c.open_time < (CAST(:end_date AS timestamp) + interval '1 day')
                ORDER BY c.open_time ASC
            """), {"start_date": start_date, "end_date": end_date}).fetchall()
        else:
            # Default: latest N candles
            rows = db.execute(text("""
                SELECT 
                    c.open_time, c.close, 
                    c.hurst_exponent, c.hurst_fast, c.regime, c.ou_deviation,
                    a.ou_signal, a.final_signal, a.final_confidence, a.duration
                FROM candles c
                LEFT JOIN analysis_history a 
                    ON a.timestamp >= c.open_time 
                    AND a.timestamp < c.open_time + interval '1 minute'
                WHERE c.symbol = 'R_100'
                ORDER BY c.open_time DESC
                LIMIT :limit
            """), {"limit": limit}).fetchall()
        
        # Forward-fill: carry last known values through NULL gaps
        # For date range mode, rows are already ASC. For default mode, rows are DESC.
        result = []
        last_hurst = 0.5
        last_hurst_fast = 0.5
        last_regime = "UNKNOWN"
        last_ou = 0.0
        
        # Determine iteration order: default mode is DESC so reverse it; date range is already ASC
        ordered_rows = reversed(rows) if not (start_date and end_date) else rows
        
        for r in ordered_rows:
            if r.hurst_exponent is not None:
                last_hurst = round(float(r.hurst_exponent), 4)
                last_regime = r.regime or "UNKNOWN"
            if r.hurst_fast is not None:
                last_hurst_fast = round(float(r.hurst_fast), 4)
            if r.ou_deviation is not None:
                last_ou = round(float(r.ou_deviation), 2)
            
            result.append({
                "time": int(r.open_time.timestamp()),
                "hurst": last_hurst,
                "hurst_fast": last_hurst_fast,
                "hurst_regime": last_regime,
                "ou_deviation": last_ou,
                "ou_signal": r.ou_signal or "HOLD",
                "signal": r.final_signal or "HOLD",
                "confidence": float(r.final_confidence) if r.final_confidence else 0,
                "duration": r.duration or 60,
                "price": float(r.close) if r.close else 0
            })
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching analysis history: {str(e)}")




@router.get("/trades")
async def get_recent_trades(limit: int = 20, db: Session = Depends(get_db)):
    """
    Get recent trades
    """
    try:
        trades = db.query(Trade).order_by(Trade.entry_time.desc()).limit(limit).all()
        
        return [
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "entry_price": float(trade.entry_price),
                "exit_price": float(trade.exit_price) if trade.exit_price else None,
                "stake": float(trade.stake),
                "payout": float(trade.stake + trade.profit_loss) if trade.profit_loss is not None else 0.0,
                "outcome": trade.outcome,
                "duration_seconds": trade.duration_seconds,
                "entry_time": trade.entry_time.isoformat(),
                "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                "confidence": float(trade.final_confidence) if trade.final_confidence is not None else 0.0,
                "pnl": float(trade.profit_loss) if trade.profit_loss is not None else 0.0,
                "hurst": float(trade.hurst_at_entry) if trade.hurst_at_entry is not None else None,
                "groq_used": bool(trade.layer3_groq_used) if trade.layer3_groq_used is not None else False,
                "engine_name": trade.engine_name or "—"
            }
            for trade in trades
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching trades: {str(e)}")


@router.get("/stats")
async def get_trading_stats(db: Session = Depends(get_db)):
    """
    Get detailed trading statistics
    """
    try:
        # Get trades from last 24 hours
        yesterday = datetime.utcnow() - timedelta(days=1)
        recent_trades = db.query(Trade).filter(Trade.entry_time >= yesterday).all()
        
        if not recent_trades:
            return {
                "period": "24h",
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "avg_pnl": 0,
                "total_pnl": 0,
                "best_trade": 0,
                "worst_trade": 0
            }
        
        winning = [t for t in recent_trades if t.outcome == "WIN"]
        losing = [t for t in recent_trades if t.outcome == "LOSS"]
        
        total_pnl = sum(float(t.profit_loss) for t in recent_trades if t.profit_loss is not None)
        avg_pnl = total_pnl / len(recent_trades) if recent_trades else 0
        
        pnls = [float(t.profit_loss) for t in recent_trades if t.profit_loss is not None]
        best_trade = max(pnls) if pnls else 0
        worst_trade = min(pnls) if pnls else 0
        
        return {
            "period": "24h",
            "total_trades": len(recent_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(len(winning) / len(recent_trades) * 100, 2) if recent_trades else 0,
            "avg_pnl": round(avg_pnl, 2),
            "total_pnl": round(total_pnl, 2),
            "best_trade": round(best_trade, 2),
            "worst_trade": round(worst_trade, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stats: {str(e)}")
