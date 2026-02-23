
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

def sync_and_calculate():
    """
    Sync missing candles from 'candles' table to 'historical_candles'
    And calculate indicators for any rows with missing data.
    """
    db = SessionLocal()
    try:
        # 1. Check last date in history
        last_hist = db.execute(text("SELECT MAX(open_time) FROM historical_candles")).fetchone()[0]
        if not last_hist:
            logger.info("No history found. Copying all from live...")
            last_hist = '2020-01-01' # Very old date
        
        logger.info(f"📅 Last historical candle: {last_hist}")
        
        # 2. Find new candles in live table
        new_candles = db.execute(text("""
            SELECT open_time, open, high, low, close, volume,
                   rsi_14, ema_9, ema_21, ema_50,
                   macd, macd_signal, macd_histogram,
                   bollinger_upper, bollinger_middle, bollinger_lower,
                   atr_14, returns, momentum_5, volatility_realized, price_position
            FROM candles 
            WHERE open_time > :last_hist
              AND symbol = 'R_100'
            ORDER BY open_time ASC
        """), {'last_hist': last_hist}).fetchall()
        
        if new_candles:
            logger.info(f"📥 Found {len(new_candles)} new candles to sync...")
            
            # Insert into historical_candles
            values = []
            for r in new_candles:
                values.append({
                    'symbol': 'R_100',
                    'timeframe': '1m',
                    'open_time': r.open_time,
                    'close_time': r.open_time + timedelta(minutes=1),
                    'open': r.open, 'high': r.high, 'low': r.low, 'close': r.close, 'volume': r.volume,
                    'rsi_14': r.rsi_14, 'ema_9': r.ema_9, 'ema_21': r.ema_21, 'ema_50': r.ema_50,
                    'macd': r.macd, 'macd_signal': r.macd_signal, 'macd_histogram': r.macd_histogram,
                    'bollinger_upper': r.bollinger_upper, 'bollinger_middle': r.bollinger_middle, 'bollinger_lower': r.bollinger_lower,
                    'atr_14': r.atr_14, 'returns': r.returns, 'momentum_5': r.momentum_5,
                    'volatility_realized': r.volatility_realized, 'price_position': r.price_position
                })
            
            # Batch insert
            batch_size = 1000
            for i in range(0, len(values), batch_size):
                batch = values[i:i+batch_size]
                db.execute(text("""
                    INSERT INTO historical_candles 
                    (symbol, timeframe, open_time, close_time, open, high, low, close, volume,
                     rsi_14, ema_9, ema_21, ema_50, macd, macd_signal, macd_histogram,
                     bollinger_upper, bollinger_middle, bollinger_lower, atr_14,
                     returns, momentum_5, volatility_realized, price_position)
                    VALUES 
                    (:symbol, :timeframe, :open_time, :close_time, :open, :high, :low, :close, :volume,
                     :rsi_14, :ema_9, :ema_21, :ema_50, :macd, :macd_signal, :macd_histogram,
                     :bollinger_upper, :bollinger_middle, :bollinger_lower, :atr_14,
                     :returns, :momentum_5, :volatility_realized, :price_position)
                    ON CONFLICT DO NOTHING
                """), batch)
                db.commit()
            
            logger.success(f"✅ Synced {len(values)} candles")
        else:
            logger.info("✅ No new candles to sync")

        # 3. Calculate indicators for rows with NULL hurst
        logger.info("🔍 Checking for missing indicators...")
        
        # Get count
        missing_count = db.execute(text("SELECT COUNT(*) FROM historical_candles WHERE hurst_exponent IS NULL")).fetchone()[0]
        if missing_count == 0:
            logger.info("✅ All indicators up to date")
            return

        logger.info(f"📉 Calculating indicators for {missing_count} candles...")
        
        # We need context: Find earliest missing date minus 200 candles
        earliest_missing = db.execute(text("SELECT MIN(open_time) FROM historical_candles WHERE hurst_exponent IS NULL")).fetchone()[0]
        start_load = earliest_missing - timedelta(minutes=300)
        
        # Load relevant data
        query = text("""
            SELECT id, open_time, close 
            FROM historical_candles 
            WHERE open_time >= :start_load
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind, params={'start_load': start_load})
        
        logger.info(f"📊 Loaded {len(df)} candles for context")
        
        if len(df) < 200:
             logger.warning("Not enough context data")
             return

        # Initialize models
        window = 200
        ou_model = OrnsteinUhlenbeckModel(window=window)
        prices = df['close'].values
        ids = df['id'].values
        
        updates = []
        
        # Find index where calculation should start (first missing)
        # We can just iterate all loaded, but check if we need to update
        # Actually, simpler to calculate for all in this loaded batch (overlap is small cost)
        
        start_idx = window 
        
        # Improve start_idx finding: 
        # Find the index in df that corresponds to 'earliest_missing'
        # But iterating all is safer to ensure continuity
        
        logger.info("🧮 calculating...")
        
        for i in range(start_idx, len(df)):
            # Only if this ID needs update? 
            # Optimization: check if this row was one of the missing ones? 
            # Or just update anyway. Updating few thousand rows is fast.
            
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
                'id': int(ids[i]),
                'hurst_exponent': float(h_val),
                'ou_deviation': float(ou_dev) if ou_dev is not None else 0.0,
                'regime': regime
            })
            
        # Bulk update
        logger.info(f"💾 Updating {len(updates)} rows...")
        
        # Use batches
        for i in range(0, len(updates), 1000):
            batch = updates[i:i+1000]
            db.execute(text("""
                UPDATE historical_candles 
                SET hurst_exponent = :hurst_exponent, 
                    ou_deviation = :ou_deviation, 
                    regime = :regime
                WHERE id = :id
            """), batch)
            db.commit()
            
        logger.success("✅ Sync compelte")
            
    except Exception as e:
        logger.error(f"❌ Sync failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    sync_and_calculate()
