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


@router.get("/candles")
async def get_candles(limit: int = 200, db: Session = Depends(get_db)):
    """
    Get recent candles for charting
    """
    try:
        # Get latest candles (descending order)
        candles = db.query(Candle).order_by(Candle.open_time.desc()).limit(limit).all()
        
        # Reverse to chronological order for chart
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
async def get_analysis_history(limit: int = 300, db: Session = Depends(get_db)):
    """
    Get historical analysis data for chart indicators overlay
    Returns last N analysis records for visualization
    """
    try:
        from app.models.models import AnalysisHistory
        
        records = db.query(AnalysisHistory)\
            .order_by(AnalysisHistory.timestamp.desc())\
            .limit(limit)\
            .all()
        
        # Reverse to chronological order and format for chart
        return [{
            "time": int(r.timestamp.timestamp()),
            "hurst": float(r.hurst_value) if r.hurst_value else 0.5,
            "hurst_regime": r.hurst_regime,
            "ou_deviation": float(r.ou_deviation) if r.ou_deviation else 0,
            "ou_signal": r.ou_signal,
            "signal": r.final_signal,
            "confidence": float(r.final_confidence) if r.final_confidence else 0,
            "duration": r.duration,
            "price": float(r.current_price) if r.current_price else 0
        } for r in reversed(records)]
        
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
                "groq_used": bool(trade.layer3_groq_used) if trade.layer3_groq_used is not None else False
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
