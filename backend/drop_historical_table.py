
import sys
from sqlalchemy import text
from app.core.database import engine
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

def drop_table():
    """Drop historical_candles table"""
    logger.info("🗑️ Dropping historical_candles table...")
    
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS historical_candles CASCADE;"))
        conn.commit()
    
    logger.success("✅ Table dropped.")

if __name__ == "__main__":
    drop_table()
