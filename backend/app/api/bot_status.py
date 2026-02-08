"""
API Routes for Bot Status and Trading Data
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime, timedelta

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
            "account_type": settings.DERIV_ACCOUNT_TYPE.upper()
        }

        # Fetch latest Layer 2 analysis
        from app.models.models import GroqDecisionLog
        latest_l2 = db.query(GroqDecisionLog).order_by(GroqDecisionLog.created_at.desc()).first()
        
        if latest_l2:
            import json
            try:
                reasoning_json = json.loads(latest_l2.reasoning) if latest_l2.reasoning else {}
                # Extract summary from reasoning chain (usually step 6 or 7)
                summary = reasoning_json.get('step6_final_decision_rationale', 'No summary available')
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
                "pnl": float(trade.profit_loss) if trade.profit_loss is not None else 0.0
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
