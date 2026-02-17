"""
Decision Tracker: L1 vs Groq comparison system

Records every L1 signal alongside Groq's final decision,
then resolves hypothetical outcomes after the contract duration.
"""

from datetime import datetime, timezone, timedelta
from loguru import logger
from sqlalchemy.orm import Session

from app.models.models import DecisionComparison, Candle


def save_decision(
    db: Session,
    entry_price: float,
    l1_signal: str,
    l1_confidence: float,
    groq_signal: str,
    groq_confidence: float,
    duration: int = 300
):
    """Save a L1 vs Groq decision for later outcome comparison"""
    try:
        comparison = DecisionComparison(
            entry_price=entry_price,
            duration=duration,
            l1_signal=l1_signal,
            l1_confidence=l1_confidence,
            groq_signal=groq_signal,
            groq_confidence=groq_confidence,
            resolve_at=datetime.now(timezone.utc) + timedelta(seconds=duration + 60)
        )
        db.add(comparison)
        db.commit()
        logger.info(f"📊 Decision tracked: L1={l1_signal}({l1_confidence:.0%}) vs Groq={groq_signal}({groq_confidence:.0%}) @ {entry_price:.2f}")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Failed to save decision comparison: {e}")


def resolve_pending(db: Session):
    """Resolve unresolved decisions that have passed their duration"""
    try:
        now = datetime.now(timezone.utc)
        pending = db.query(DecisionComparison).filter(
            DecisionComparison.resolved == False,
            DecisionComparison.resolve_at <= now
        ).all()
        
        if not pending:
            return
        
        resolved_count = 0
        for decision in pending:
            # Find the candle closest to created_at + duration
            target_time = decision.created_at + timedelta(seconds=decision.duration)
            
            # Get closest candle after the target time
            exit_candle = db.query(Candle).filter(
                Candle.open_time >= target_time
            ).order_by(Candle.open_time.asc()).first()
            
            if not exit_candle:
                continue  # Candle not yet available
            
            exit_price = float(exit_candle.close)
            entry_price = float(decision.entry_price)
            price_change = exit_price - entry_price
            
            # Determine L1 hypothetical outcome
            if decision.l1_signal == 'CALL':
                l1_won = price_change > 0
            elif decision.l1_signal == 'PUT':
                l1_won = price_change < 0
            else:
                l1_won = False
            
            # Determine Groq result
            if decision.groq_signal == 'HOLD':
                groq_result = 'SKIPPED'
            elif decision.groq_signal == 'CALL':
                groq_result = 'WIN' if price_change > 0 else 'LOSS'
            elif decision.groq_signal == 'PUT':
                groq_result = 'WIN' if price_change < 0 else 'LOSS'
            else:
                groq_result = 'SKIPPED'
            
            # Update the record
            decision.exit_price = exit_price
            decision.price_change = price_change
            decision.l1_hypothetical = 'WIN' if l1_won else 'LOSS'
            decision.groq_result = groq_result
            decision.resolved = True
            resolved_count += 1
            
            logger.info(
                f"🔍 Decision resolved: L1={decision.l1_signal}→{'WIN' if l1_won else 'LOSS'} | "
                f"Groq={decision.groq_signal}→{groq_result} | "
                f"Δprice={price_change:+.2f}"
            )
        
        if resolved_count > 0:
            db.commit()
            logger.info(f"✅ Resolved {resolved_count} decision comparisons")
    
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error resolving decisions: {e}")


def get_scorecard(db: Session) -> dict:
    """Get L1 vs Groq performance scorecard"""
    try:
        # Get ALL decisions for the table (last 30)
        all_decisions = db.query(DecisionComparison).order_by(
            DecisionComparison.created_at.desc()
        ).limit(30).all()
        
        # Separate resolved for stats
        resolved = [d for d in all_decisions if d.resolved]
        
        total = len(resolved)
        l1_wins = sum(1 for d in resolved if d.l1_hypothetical == 'WIN')
        l1_losses = sum(1 for d in resolved if d.l1_hypothetical == 'LOSS')
        
        groq_wins = sum(1 for d in resolved if d.groq_result == 'WIN')
        groq_losses = sum(1 for d in resolved if d.groq_result == 'LOSS')
        groq_skipped = sum(1 for d in resolved if d.groq_result == 'SKIPPED')
        
        groq_saved = sum(1 for d in resolved 
                        if d.groq_result == 'SKIPPED' and d.l1_hypothetical == 'LOSS')
        groq_missed = sum(1 for d in resolved 
                         if d.groq_result == 'SKIPPED' and d.l1_hypothetical == 'WIN')
        
        groq_traded = groq_wins + groq_losses
        
        # Build table with ALL decisions (pending show as null results)
        decisions_list = [{
            "time": d.created_at.isoformat() if d.created_at else None,
            "entry_price": float(d.entry_price) if d.entry_price else 0,
            "exit_price": float(d.exit_price) if d.exit_price else 0,
            "price_change": float(d.price_change) if d.price_change else 0,
            "l1_signal": d.l1_signal,
            "l1_confidence": float(d.l1_confidence) if d.l1_confidence else 0,
            "l1_hypothetical": d.l1_hypothetical if d.resolved else None,
            "groq_signal": d.groq_signal,
            "groq_confidence": float(d.groq_confidence) if d.groq_confidence else 0,
            "groq_result": d.groq_result if d.resolved else None,
            "resolved": d.resolved
        } for d in all_decisions]
        
        return {
            "total_decisions": total,
            "total_tracked": len(all_decisions),
            "l1_wins": l1_wins,
            "l1_losses": l1_losses,
            "l1_win_rate": round(l1_wins / total * 100, 1) if total else 0,
            "groq_wins": groq_wins,
            "groq_losses": groq_losses,
            "groq_skipped": groq_skipped,
            "groq_win_rate": round(groq_wins / groq_traded * 100, 1) if groq_traded else 0,
            "groq_saved": groq_saved,
            "groq_missed": groq_missed,
            "decisions": decisions_list
        }
    except Exception as e:
        logger.error(f"❌ Error getting scorecard: {e}")
        return {"error": str(e)}

