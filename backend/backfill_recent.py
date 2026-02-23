
import sys
import time
import numpy as np
import pandas as pd
from sqlalchemy import text
from datetime import timedelta
from app.core.database import SessionLocal, engine
from app.analysis.hurst import HurstExponent
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

def backfill_recent():
    """
    Backfill indicators for RECENT candles (last 2 days).
    Loading full history for context but only updating recent rows.
    """
    db = SessionLocal()
    try:
        logger.info("📥 Loading all candles for context...")
        # Load all close prices for window calculation
        query = text("""
            SELECT id, open_time, close 
            FROM candles 
            WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind)
        logger.info(f"📊 Loaded {len(df)} candles")
        
        # Determine start index for recent data (last 2 days = ~2880 candles)
        # Or just filter by date > '2026-02-18'
        recent_mask = df['open_time'] >= '2026-02-18'
        
        # But we need index integer
        try:
            start_index = df[recent_mask].index[0]
        except IndexError:
            logger.info("No recent data found.")
            return

        logger.info(f"🚀 Starting backfill from index {start_index} ({df.iloc[start_index]['open_time']})...")
        
        # Identify missing IDs in this range
        recent_ids = tuple(df.iloc[start_index:]['id'].values.tolist())
        if not recent_ids:
            logger.info("No recent rows.")
            return

        # Query which ones are actually missing (to skip done ones)
        # Using IN clause might be slow for 3000 ids? No, it's fine.
        # Construct large IN clause or temporary table?
        # Actually easier to just query ALL missing IDs and filter in python
        missing_ids = set(row[0] for row in db.execute(text("SELECT id FROM candles WHERE hurst_exponent IS NULL")).fetchall())
        
        # Initialize models
        window = 200
        ou_model = OrnsteinUhlenbeckModel(window=window)
        prices = df['close'].values
        ids = df['id'].values
        
        updates = []
        batch_size = 500
        
        processed = 0
        total_recent = len(df) - start_index
        
        for i in range(start_index, len(df)):
            current_id = int(ids[i])
            
            # Skip if already calculated
            if current_id not in missing_ids:
                continue
            
            # Ensure we have enough history for window
            if i < window:
                continue
                
            window_prices = prices[i-window:i+1] # window+1 length?
            # HurstExponent.calculate uses series.
            # O-U uses prices.
            
            # Hurst
            price_series = pd.Series(window_prices)
            h_val = HurstExponent.calculate(price_series, window)
            
            # Regime
            regime = 'RANDOM'
            if h_val > 0.6: regime = 'TRENDING'
            elif h_val < 0.4: regime = 'MEAN_REVERSION'
            elif h_val > 0.55: regime = 'WEAK_TRENDING'
            elif h_val < 0.45: regime = 'WEAK_MEAN_REVERSION'
            
            # OU
            ou_dev = 0.0
            try:
                if ou_model.fit(price_series):
                    ou_dev = ou_model.get_deviation(window_prices[-1])
            except Exception:
                pass
            
            updates.append({
                'id': current_id,
                'hurst_exponent': float(h_val),
                'ou_deviation': float(ou_dev) if ou_dev is not None else 0.0,
                'regime': regime
            })
            
            if len(updates) >= batch_size:
                _bulk_update(db, updates)
                processed += len(updates)
                updates = []
                logger.info(f"Updated {processed} recent candles...")
                
        # Final batch
        if updates:
            _bulk_update(db, updates)
            logger.info(f"Updated final {len(updates)} candles.")
            
        logger.success("✅ Recent Backfill complete!")
            
    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}")
        db.rollback()
    finally:
        db.close()

def _bulk_update(db, mappings):
    try:
        db.execute(text("""
            UPDATE candles 
            SET hurst_exponent = :hurst_exponent, 
                ou_deviation = :ou_deviation, 
                regime = :regime
            WHERE id = :id
        """), mappings)
        db.commit()
    except Exception as e:
        logger.error(f"❌ Batch update failed: {e}")
        db.rollback()

if __name__ == "__main__":
    backfill_recent()
