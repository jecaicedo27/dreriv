from app.core.database import SessionLocal
from app.models.models import BotState, Trade
from sqlalchemy import desc

def report():
    db = SessionLocal()
    try:
        # Bot State
        state = db.query(BotState).first()
        if state:
            print(f"--- DAILY STATUS ---")
            print(f"PnL: ${state.daily_pnl}")
            print(f"Wins: {state.wins_today} | Losses: {state.losses_today}")
            print(f"Balance: ${state.balance}")
        
        # Recent Trades
        trades = db.query(Trade).order_by(desc(Trade.entry_time)).limit(5).all()
        print("\n--- LAST 5 TRADES ANALYSIS ---")
        for t in trades:
            print(f"\n🔹 [{t.entry_time}] {t.contract_type} ({t.direction})")
            print(f"   Result: {t.outcome} (${t.profit_loss})")
            print(f"   Conf: {t.final_confidence} | Groq Used: {t.layer3_groq_used}")
            if t.layer3_groq_reasoning:
                print(f"   🤖 Groq: {t.layer3_groq_reasoning[:150]}...") # Show first 150 chars
            else:
                print(f"   🤖 Groq: N/A")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    report()
