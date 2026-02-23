
import sys
import time
import numpy as np
import pandas as pd
from sqlalchemy import text
from app.core.database import SessionLocal, engine
from app.analysis.hurst import HurstExponent
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

def calculate_indicators():
    """
    Calculate Hurst, OU, and Regime for all historical candles
    """
    logger.info("📉 Loading historical candles...")
    
    with engine.connect() as conn:
        query = text("""
            SELECT id, open_time, close 
            FROM historical_candles 
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, conn)
    
    logger.info(f"📊 Loaded {len(df)} candles")
    
    if len(df) < 200:
        logger.error("Not enough data to calculate indicators (need > 200)")
        return

    # Pre-allocate result arrays
    hurst_values = np.full(len(df), None, dtype=object)
    ou_values = np.full(len(df), None, dtype=object)
    regimes = np.full(len(df), None, dtype=object)
    
    # Initialize models
    window = 200
    ou_model = OrnsteinUhlenbeckModel(window=window)
    
    logger.info("🧮 Starting calculations (this may take a while)...")
    start_time = time.time()
    
    # Iterate through candles starting from window size
    # Optimizations: 
    # 1. Use numpy arrays for speed
    # 2. Update DB in batches
    
    prices = df['close'].values
    ids = df['id'].values
    
    updates = []
    
    for i in range(window, len(df)):
        # Get window snippet
        window_prices = prices[i-window:i+1] # Include current
        
        # --- Hurst ---
        # We need a Series for the current Hurst implementation
        price_series = pd.Series(window_prices)
        h_val = HurstExponent.calculate(price_series, window)
        hurst_values[i] = h_val
        
        # --- Regime ---
        regime = 'RANDOM'
        if h_val > 0.6: regime = 'TRENDING'
        elif h_val < 0.4: regime = 'MEAN_REVERSION'
        elif h_val > 0.55: regime = 'WEAK_TRENDING'
        elif h_val < 0.45: regime = 'WEAK_MEAN_REVERSION'
        regimes[i] = regime
        
        # --- OU Deviation ---
        # Re-fit model every step is expensive but necessary for "historical accuracy"
        # To speed up, maybe fit every 10 steps? 
        # For now, let's do every step to be precise.
        ou_dev = 0.0
        if ou_model.fit(pd.Series(window_prices)): # Fit on window
             ou_dev = ou_model.get_deviation(window_prices[-1])
        ou_values[i] = ou_dev
        
        # Prepare update dict
        updates.append({
            'id': int(ids[i]),
            'hurst_exponent': float(h_val),
            'ou_deviation': float(ou_dev) if ou_dev is not None else 0.0,
            'regime': regime
        })
        
        if len(updates) >= 1000:
            _bulk_update(updates)
            updates = []
            
            # Progress log
            if i % 5000 == 0:
                elapsed = time.time() - start_time
                rate = i / elapsed
                remaining = (len(df) - i) / rate
                logger.info(f"Progress: {i}/{len(df)} ({i/len(df):.1%}) - {rate:.1f} candles/sec - ETA: {remaining/60:.1f} min")

    # Final batch
    if updates:
        _bulk_update(updates)
        
    logger.success("✅ Calculations complete!")

def _bulk_update(mappings):
    """Update batch using SQLAlchemy"""
    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE historical_candles 
            SET hurst_exponent = :hurst_exponent, 
                ou_deviation = :ou_deviation, 
                regime = :regime
            WHERE id = :id
        """), mappings)
        db.commit()
    except Exception as e:
        logger.error(f"❌ Batch update failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    calculate_indicators()
