
from app.core.database import SessionLocal
from sqlalchemy import text

def clear_simulation():
    db = SessionLocal()
    try:
        print("🧹 Clearing HistoricalCandles table (Simulation Data)...")
        # Use truncate for speed and reset identity if supported, else delete
        try:
            db.execute(text("TRUNCATE TABLE historical_candles RESTART IDENTITY;"))
        except:
            # Fallback if table name is different or truncate fails
            db.execute(text("DELETE FROM historical_candles;"))
            
        db.commit()
        print("✅ Simulation Data cleared successfully.")
    except Exception as e:
        print(f"❌ Error clearing data: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    clear_simulation()
