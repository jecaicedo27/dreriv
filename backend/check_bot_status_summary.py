import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings
from app.models.models import BotState, Trade, GroqDecisionLog
import json

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def check_status():
    db = SessionLocal()
    try:
        # 1. Bot State
        state = db.query(BotState).first()
        print(f"💰 Balance: ${state.balance:.2f}")
        print(f"📅 Daily P&L: ${state.daily_pnl:.2f}")
        print(f"📊 Wins Today: {state.wins_today} | Losses Today: {state.losses_today}")
        
        if state.cooldown_until:
             print(f"❄️ COOLDOWN UNTIL: {state.cooldown_until} (Reason: {state.cooldown_reason})")
        else:
             print("✅ Status: ACTIVE (No Cooldown)")

        # 2. Last 5 Trades
        print("\n📜 Last 5 Trades:")
        trades = db.query(Trade).order_by(Trade.entry_time.desc()).limit(5).all()
        for t in trades:
            pnl_str = f"${t.profit_loss:.2f}" if t.profit_loss is not None else "PENDING"
            print(f"   [{t.entry_time.strftime('%H:%M:%S')}] {t.direction} -> {t.outcome} ({pnl_str})")

        # 3. Last Groq Decision
        print("\n🧠 Last AI Decision:")
        log = db.query(GroqDecisionLog).order_by(GroqDecisionLog.created_at.desc()).first()
        if log:
            print(f"   [{log.created_at.strftime('%H:%M:%S')}] {log.decision} (Conf: {log.confidence:.2f})")
            try:
                reasoning = json.loads(log.reasoning)
                summary = reasoning.get('step6_decision_rationale') or \
                          reasoning.get('step6_final_decision_rationale') or \
                          "No summary"
                print(f"   📝 Summary: {summary[:150]}...")
            except:
                print("   📝 Summary: Parse Error")
        else:
            print("   No AI logs found.")

    finally:
        db.close()

if __name__ == "__main__":
    check_status()
