
import sys
from sqlalchemy import text
from app.core.database import SessionLocal
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

def check_today():
    db = SessionLocal()
    try:
        # Check today (UTC)
        date_str = '2026-02-19'
        
        query = text("""
            SELECT count(*) as total,
                   count(hurst_exponent) as with_hurst,
                   count(*) - count(hurst_exponent) as missing
            FROM candles 
            WHERE symbol = 'R_100' 
              AND DATE(open_time) = :date
        """)
        
        result = db.execute(query, {"date": date_str}).fetchone()
        
        logger.info(f"📅 Date: {date_str}")
        logger.info(f"🕯️ Total Candles: {result.total}")
        logger.info(f"✅ With Hurst: {result.with_hurst}")
        logger.info(f"❌ Missing Hurst: {result.missing}")
        
    finally:
        db.close()

if __name__ == "__main__":
    check_today()
