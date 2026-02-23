
import sys
import time
import numpy as np
import pandas as pd
from sqlalchemy import text
from app.core.database import SessionLocal
from app.analysis.hurst import HurstExponent
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from loguru import logger

# Suppress O-U logs
logger.remove()
# Only errors to stderr
logger.add(sys.stderr, format="<level>{message}</level>", level="ERROR")

def backfill_recent_v2():
    db = SessionLocal()
    try:
        print("📥 Loading candles...")
        query = text("""
            SELECT id, open_time, close 
            FROM candles 
            WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind)
        
        recent_mask = df['open_time'] >= '2026-02-18'
        if not recent_mask.any():
            print("No recent data.")
            return
            
        start_index = df[recent_mask].index[0]
        print(f"🚀 Backfilling from index {start_index} ({df.iloc[start_index]['open_time']})...")
        
        # Get missing IDs properly
        missing_ids = set(row[0] for row in db.execute(text("SELECT id FROM candles WHERE hurst_exponent IS NULL")).fetchall())
        
        window = 200
        ou_model = OrnsteinUhlenbeckModel(window=window)
        prices = df['close'].values
        ids = df['id'].values
        
        updates = []
        batch_size = 2000
        processed = 0
        
        start_time = time.time()
        
        # Iterate over recent indices
        for i in range(start_index, len(df)):
            current_id = int(ids[i])
            if current_id not in missing_ids:
                continue
            
            if i < window:
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
            try:
                # O-U might log warnings internally, but we suppressed logger level to ERROR
                if ou_model.fit(price_series):
                    ou_dev = ou_model.get_deviation(window_prices[-1])
            except:
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
                print(f"✅ Committed {processed} rows ({(time.time() - start_time):.1f}s)")
                
        if updates:
            _bulk_update(db, updates)
            print(f"✅ Final commit: {len(updates)} rows.")
            
        print("🎉 Done.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
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
        print(f"❌ Batch error: {e}")
        db.rollback()

if __name__ == "__main__":
    backfill_recent_v2()
