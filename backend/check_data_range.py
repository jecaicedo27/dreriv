
from sqlalchemy import create_engine, text
from app.core.config import get_settings

try:
    engine = create_engine(get_settings().DATABASE_URL)
    with engine.connect() as conn:
        # Count total
        count = conn.execute(text("SELECT COUNT(*) FROM historical_candles")).fetchone()[0]
        
        # Get Min/Max time
        times = conn.execute(text("SELECT MIN(open_time), MAX(open_time) FROM historical_candles")).fetchone()
        min_time = times[0]
        max_time = times[1]
        
        print(f"📊 Total Candles: {count:,}")
        print(f"📅 Range: {min_time} -> {max_time}")
        
except Exception as e:
    print(f"Error checking data: {e}")
