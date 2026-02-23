"""
Fast Standard Indicator Backfill via SQL Temp Table

Strategy:
1. Load all OHLCV data from candles
2. Calculate indicators in pandas (vectorized = instant)  
3. Write results to PostgreSQL temp table via to_sql (fast bulk insert)
4. Single SQL UPDATE ... FROM temp table (fast native PostgreSQL)
5. Drop temp table

This avoids slow Python loops for DB updates entirely.
"""
import sys
import time
import numpy as np
import pandas as pd
from sqlalchemy import text
from app.core.database import SessionLocal, engine
from app.analysis.indicators import TechnicalIndicators
from loguru import logger

logger.remove()
logger.add(sys.stderr, format="{message}", level="CRITICAL")


def fast_backfill():
    db = SessionLocal()
    try:
        t0 = time.time()
        
        # ============================================================
        # Step 1: Load OHLCV
        # ============================================================
        print("📥 Loading candles...")
        query = text("""
            SELECT id, open_time, open, high, low, close, volume
            FROM candles WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind)
        print(f"   Loaded {len(df)} candles in {time.time()-t0:.1f}s")
        
        # ============================================================
        # Step 2: Calculate indicators (vectorized)
        # ============================================================
        print("🧮 Calculating indicators...")
        t1 = time.time()
        df_calc = TechnicalIndicators.calculate_all(df.copy())
        print(f"   Done in {time.time()-t1:.1f}s")
        
        # ============================================================
        # Step 3: Write to temp table
        # ============================================================
        print("💾 Writing to temp table...")
        t2 = time.time()
        
        # Select only the columns we need for the update
        update_cols = [
            'id', 'rsi_14', 'ema_9', 'ema_21', 'ema_50',
            'macd', 'macd_signal', 'macd_histogram',
            'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
            'atr_14', 'returns', 'momentum_5',
            'volatility_realized', 'price_position'
        ]
        
        # Build the temp dataframe
        temp_df = df_calc[update_cols].copy()
        
        # Convert all numeric types to native Python float
        for col in update_cols[1:]:  # Skip 'id'
            temp_df[col] = pd.to_numeric(temp_df[col], errors='coerce')
        
        # Drop temp table if exists
        db.execute(text("DROP TABLE IF EXISTS temp_indicators"))
        db.commit()
        
        # Write to temp table using pandas (uses COPY internally = very fast)
        temp_df.to_sql('temp_indicators', engine, if_exists='replace', index=False, method='multi', chunksize=10000)
        print(f"   Written {len(temp_df)} rows in {time.time()-t2:.1f}s")
        
        # ============================================================
        # Step 4: Bulk UPDATE via SQL JOIN
        # ============================================================
        print("🔄 Executing bulk UPDATE...")
        t3 = time.time()
        
        result = db.execute(text("""
            UPDATE candles c SET
                rsi_14 = t.rsi_14,
                ema_9 = t.ema_9,
                ema_21 = t.ema_21,
                ema_50 = t.ema_50,
                macd = t.macd,
                macd_signal = t.macd_signal,
                macd_histogram = t.macd_histogram,
                bollinger_upper = t.bollinger_upper,
                bollinger_middle = t.bollinger_middle,
                bollinger_lower = t.bollinger_lower,
                atr_14 = t.atr_14,
                returns = t.returns,
                momentum_5 = t.momentum_5,
                volatility_realized = t.volatility_realized,
                price_position = t.price_position
            FROM temp_indicators t
            WHERE c.id = t.id
        """))
        db.commit()
        print(f"   ✅ Updated {result.rowcount} rows in {time.time()-t3:.1f}s")
        
        # ============================================================
        # Step 5: Cleanup
        # ============================================================
        db.execute(text("DROP TABLE IF EXISTS temp_indicators"))
        db.commit()
        
        total = time.time() - t0
        print(f"\n🎉 COMPLETE in {total:.1f}s ({total/60:.1f} min)")
        print(f"   Indicators: RSI, EMA(9/21/50), MACD, BB, ATR, momentum, volatility, price_position")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    fast_backfill()
