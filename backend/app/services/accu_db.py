"""
Database persistence for Accumulator bot trades.
Uses the same PostgreSQL instance as the Rise/Fall bot.
"""
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy import text
from loguru import logger

from app.core.database import SessionLocal


def save_accu_trade(trade_data: dict) -> Optional[int]:
    """
    Save a completed ACCU trade to the database.
    
    Args:
        trade_data: dict with keys matching accu_trades columns
    
    Returns:
        trade ID or None on error
    """
    db = SessionLocal()
    try:
        result = db.execute(text("""
            INSERT INTO accu_trades (
                symbol, deriv_contract_id,
                entry_time, entry_price, stake, growth_rate, take_profit,
                exit_time, exit_price, profit_loss, outcome, duration_seconds,
                volatility_score, signal, reasoning
            ) VALUES (
                :symbol, :deriv_contract_id,
                :entry_time, :entry_price, :stake, :growth_rate, :take_profit,
                :exit_time, :exit_price, :profit_loss, :outcome, :duration_seconds,
                :volatility_score, :signal, :reasoning
            ) RETURNING id
        """), {
            "symbol": trade_data.get("symbol", "BOOM1000"),
            "deriv_contract_id": trade_data.get("deriv_contract_id"),
            "entry_time": trade_data.get("entry_time", datetime.utcnow()),
            "entry_price": trade_data.get("entry_price"),
            "stake": trade_data.get("stake", 10.0),
            "growth_rate": trade_data.get("growth_rate", 0.03),
            "take_profit": trade_data.get("take_profit"),
            "exit_time": trade_data.get("exit_time"),
            "exit_price": trade_data.get("exit_price"),
            "profit_loss": trade_data.get("profit_loss", 0),
            "outcome": trade_data.get("outcome", "LOSS"),
            "duration_seconds": trade_data.get("duration_seconds"),
            "volatility_score": trade_data.get("volatility_score"),
            "signal": trade_data.get("signal"),
            "reasoning": trade_data.get("reasoning"),
        })
        db.commit()
        trade_id = result.fetchone()[0]
        logger.info(f"💾 ACCU trade saved to DB — ID: {trade_id}, outcome: {trade_data.get('outcome')}, P&L: ${trade_data.get('profit_loss', 0):.2f}")
        return trade_id
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Failed to save ACCU trade to DB: {e}")
        return None
    finally:
        db.close()


def get_accu_trades(limit: int = 50) -> List[Dict]:
    """Get recent ACCU trades from the database."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT id, symbol, deriv_contract_id,
                   entry_time, entry_price, stake, growth_rate, take_profit,
                   exit_time, exit_price, profit_loss, outcome, duration_seconds,
                   volatility_score, signal, reasoning, created_at
            FROM accu_trades
            ORDER BY entry_time DESC
            LIMIT :limit
        """), {"limit": limit})
        
        trades = []
        for row in result.fetchall():
            trades.append({
                "id": row[0],
                "symbol": row[1],
                "deriv_contract_id": row[2],
                "time": row[3].strftime("%H:%M:%S") if row[3] else None,
                "entry_time": row[3].isoformat() if row[3] else None,
                "entry_price": float(row[4]) if row[4] else None,
                "stake": float(row[5]) if row[5] else 0,
                "growth_rate": float(row[6]) if row[6] else 0.03,
                "take_profit": float(row[7]) if row[7] else None,
                "exit_time": row[8].isoformat() if row[8] else None,
                "exit_price": float(row[9]) if row[9] else None,
                "pnl": float(row[10]) if row[10] else 0,
                "outcome": row[11],
                "duration": row[12],
                "volatility_score": float(row[13]) if row[13] else None,
                "signal": row[14],
                "reasoning": row[15],
            })
        return trades
    except Exception as e:
        logger.error(f"❌ Failed to fetch ACCU trades: {e}")
        return []
    finally:
        db.close()


def get_accu_session_stats() -> Dict:
    """Get aggregate stats for the current day's ACCU trades."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT 
                COUNT(*) as total_trades,
                COALESCE(SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END), 0) as wins,
                COALESCE(SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END), 0) as losses,
                COALESCE(SUM(profit_loss), 0) as total_pnl
            FROM accu_trades
            WHERE entry_time >= CURRENT_DATE
        """))
        row = result.fetchone()
        total = row[0] or 0
        wins = row[1] or 0
        return {
            "total_trades": total,
            "wins": wins,
            "losses": row[2] or 0,
            "session_pnl": float(row[3] or 0),
            "win_rate": round(100 * wins / total, 1) if total > 0 else 0,
        }
    except Exception as e:
        logger.error(f"❌ Failed to get ACCU session stats: {e}")
        return {"total_trades": 0, "wins": 0, "losses": 0, "session_pnl": 0, "win_rate": 0}
    finally:
        db.close()
