from app.core.database import SessionLocal
from app.models.models import AnalysisHistory
from sqlalchemy import text

def clear_history():
    db = SessionLocal()
    try:
        print("🧹 Clearing AnalysisHistory table...")
        # Use truncate for speed and reset identity if supported, else delete
        try:
            db.execute(text("TRUNCATE TABLE analysis_history RESTART IDENTITY;"))
        except:
            db.query(AnalysisHistory).delete()
            
        db.commit()
        print("✅ AnalysisHistory cleared successfully.")
    except Exception as e:
        print(f"❌ Error clearing history: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    clear_history()
