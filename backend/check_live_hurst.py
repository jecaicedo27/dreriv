
import sys
from sqlalchemy import text
from app.core.database import SessionLocal
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

def check_latest_hurst():
    db = SessionLocal()
    try:
        # Get latest candle
        result = db.execute(text("""
            SELECT open_time, hurst_exponent, ou_deviation, regime 
            FROM candles 
            WHERE symbol = 'R_100' 
            ORDER BY open_time DESC 
            LIMIT 1
        """)).fetchone()
        
        if result:
            logger.info(f"🕯️ Latest Candle: {result.open_time}")
            logger.info(f"📊 Hurst: {result.hurst_exponent}")
            logger.info(f"📉 OU Dev: {result.ou_deviation}")
            logger.info(f"🏷️ Regime: {result.regime}")
            
            if result.hurst_exponent is not None:
                logger.success("✅ Hurst is populated!")
            else:
                logger.error("❌ Hurst is NULL!")
        else:
            logger.warning("⚠️ No candles found")
            
    finally:
        db.close()

if __name__ == "__main__":
    check_latest_hurst()
