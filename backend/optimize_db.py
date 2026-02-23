
import sys
from sqlalchemy import text
from app.core.database import engine
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

def optimize_db():
    logger.info("🔧 Optimizing database...")
    
    # Use raw connection for index/vacuum
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        logger.info("creating index...")
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_candles_date_bogota ON candles ((DATE(open_time AT TIME ZONE 'America/Bogota')));"))
        
        logger.info("Vacuuming...")
        conn.execute(text("VACUUM ANALYZE candles;"))
        
    logger.success("✅ Database optimized.")

if __name__ == "__main__":
    optimize_db()
