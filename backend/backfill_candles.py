
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

def backfill_candles():
    """
    Backfill indicators for 'candles' table.
    Targeting rows where hurst_exponent is NULL.
    """
    db = SessionLocal()
    try:
        # Check count of missing
        missing_count = db.execute(text("SELECT COUNT(*) FROM candles WHERE hurst_exponent IS NULL")).fetchone()[0]
        if missing_count == 0:
            logger.info("✅ All candles have indicators.")
            return

        logger.info(f"📉 Found {missing_count} candles needing indicators...")
        
        # We need to process in chunks to handle memory for 250k+ rows
        # But for context we need continuous data.
        # Loading all 250k timestamps/close is small (approx 4MB).
        
        logger.info("📥 Loading all candles...")
        query = text("""
            SELECT id, open_time, close 
            FROM candles 
            WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind)
        logger.info(f"📊 Loaded {len(df)} candles")
        
        # Create a boolean mask of what needs update
        # We can query IDs of missing rows to filter our loop
        missing_ids = set(row[0] for row in db.execute(text("SELECT id FROM candles WHERE hurst_exponent IS NULL")).fetchall())
        
        # Initialize models
        window = 200
        ou_model = OrnsteinUhlenbeckModel(window=window)
        prices = df['close'].values
        ids = df['id'].values
        
        updates = []
        batch_size = 1000
        processed = 0
        start_time = time.time()
        
        logger.info("🧮 Starting calculation loop...")
        
        # We start from window size
        for i in range(window, len(df)):
            current_id = int(ids[i])
            
            # Skip if already calculated
            if current_id not in missing_ids:
                continue
                
            window_prices = prices[i-window:i+1]
            price_series = pd.Series(window_prices)
            
            # Hurst
            h_val = HurstExponent.calculate(price_series, window)
            
            # Regime
            regime = 'RANDOM'
            if h_val > 0.6: regime = 'TRENDING'
            elif h_val < 0.4: regime = 'MEAN_REVERSION'
            elif h_val > 0.55: regime = 'WEAK_TRENDING'
            elif h_val < 0.45: regime = 'WEAK_MEAN_REVERSION'
            
            # OU
            ou_dev = 0.0
            if ou_model.fit(price_series):
                 ou_dev = ou_model.get_deviation(window_prices[-1])
            
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
                
                # Log progress
                elapsed = time.time() - start_time
                rate = processed / elapsed
                remaining = (missing_count - processed) / rate if rate > 0 else 0
                logger.info(f"Progress: {processed}/{missing_count} ({processed/missing_count:.1%}) - {rate:.1f} candles/sec - ETA: {remaining/60:.1f} min")
                
        # Final batch
        if updates:
            _bulk_update(db, updates)
            
        logger.success("✅ Backfill complete!")
            
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
    backfill_candles()
