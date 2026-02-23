"""
Comprehensive Indicator Backfill
Recalculates ALL indicators (RSI, EMA, MACD, BB, ATR, Hurst, OU, etc.)
for all candles missing ANY indicator.

Strategy:
1. Load ALL OHLCV data from candles table (vectorized)
2. Run TechnicalIndicators.calculate_all() on full DataFrame (pandas vectorized = fast)
3. Run HurstExponent per-row in rolling window (slower but necessary)
4. Bulk UPDATE all indicator columns back to DB
"""
import sys
import time
import numpy as np
import pandas as pd
from sqlalchemy import text
from app.core.database import SessionLocal
from app.analysis.indicators import TechnicalIndicators
from app.analysis.hurst import HurstExponent
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from loguru import logger

# Suppress verbose logs
logger.remove()
logger.add(sys.stderr, format="{message}", level="ERROR")

HURST_WINDOW = 200

def backfill_all():
    db = SessionLocal()
    try:
        print("📥 Loading ALL candles...")
        t0 = time.time()
        
        query = text("""
            SELECT id, open_time, open, high, low, close, volume
            FROM candles 
            WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind)
        print(f"📊 Loaded {len(df)} candles in {time.time()-t0:.1f}s")
        
        if df.empty:
            print("No candles found.")
            return
        
        # ============================================================
        # STEP 1: Vectorized standard indicators (RSI, EMA, MACD, BB, ATR)
        # This is FAST — pandas vectorized operations on full DataFrame
        # ============================================================
        print("🧮 Step 1: Calculating standard indicators (vectorized)...")
        t1 = time.time()
        
        df_indicators = TechnicalIndicators.calculate_all(df.copy())
        print(f"   ✅ Done in {time.time()-t1:.1f}s")
        
        # ============================================================
        # STEP 2: Rolling Hurst + OU (per-row, slower)
        # Only calculate for rows that need it
        # ============================================================
        print("🧮 Step 2: Calculating Hurst + OU (rolling window)...")
        t2 = time.time()
        
        prices = df['close'].values
        hurst_values = np.full(len(df), np.nan)
        ou_values = np.full(len(df), 0.0)
        regime_values = [''] * len(df)
        
        ou_model = OrnsteinUhlenbeckModel(window=HURST_WINDOW)
        
        processed = 0
        for i in range(HURST_WINDOW, len(df)):
            window_prices = prices[i-HURST_WINDOW:i+1]
            price_series = pd.Series(window_prices)
            
            # Hurst
            h_val = HurstExponent.calculate(price_series, HURST_WINDOW)
            hurst_values[i] = float(h_val)
            
            # Regime
            if h_val > 0.6:
                regime_values[i] = 'TRENDING'
            elif h_val < 0.4:
                regime_values[i] = 'MEAN_REVERSION'
            elif h_val > 0.55:
                regime_values[i] = 'WEAK_TRENDING'
            elif h_val < 0.45:
                regime_values[i] = 'WEAK_MEAN_REVERSION'
            else:
                regime_values[i] = 'RANDOM'
            
            # OU
            try:
                if ou_model.fit(price_series):
                    ou_dev = ou_model.get_deviation(window_prices[-1])
                    ou_values[i] = float(ou_dev) if ou_dev is not None else 0.0
            except:
                pass
            
            processed += 1
            if processed % 10000 == 0:
                elapsed = time.time() - t2
                rate = processed / elapsed
                remaining = (len(df) - HURST_WINDOW - processed) / rate if rate > 0 else 0
                print(f"   Progress: {processed}/{len(df)-HURST_WINDOW} ({processed/(len(df)-HURST_WINDOW)*100:.1f}%) - {rate:.0f}/s - ETA: {remaining/60:.1f}min")
        
        print(f"   ✅ Done in {time.time()-t2:.1f}s")
        
        # ============================================================
        # STEP 3: Merge results and bulk update DB
        # ============================================================
        print("💾 Step 3: Updating database...")
        t3 = time.time()
        
        # Build update DataFrame
        update_df = pd.DataFrame({
            'id': df['id'],
            'rsi_14': df_indicators.get('rsi_14', pd.Series(dtype=float)),
            'ema_9': df_indicators.get('ema_9', pd.Series(dtype=float)),
            'ema_21': df_indicators.get('ema_21', pd.Series(dtype=float)),
            'ema_50': df_indicators.get('ema_50', pd.Series(dtype=float)),
            'macd': df_indicators.get('macd', pd.Series(dtype=float)),
            'macd_signal': df_indicators.get('macd_signal', pd.Series(dtype=float)),
            'macd_histogram': df_indicators.get('macd_histogram', pd.Series(dtype=float)),
            'bollinger_upper': df_indicators.get('bollinger_upper', pd.Series(dtype=float)),
            'bollinger_middle': df_indicators.get('bollinger_middle', pd.Series(dtype=float)),
            'bollinger_lower': df_indicators.get('bollinger_lower', pd.Series(dtype=float)),
            'atr_14': df_indicators.get('atr_14', pd.Series(dtype=float)),
            'returns': df_indicators.get('returns', pd.Series(dtype=float)),
            'momentum_5': df_indicators.get('momentum_5', pd.Series(dtype=float)),
            'volatility_realized': df_indicators.get('volatility_realized', pd.Series(dtype=float)),
            'price_position': df_indicators.get('price_position', pd.Series(dtype=float)),
            'hurst_exponent': hurst_values,
            'ou_deviation': ou_values,
            'regime': regime_values,
        })
        
        # Replace NaN with None for SQL
        update_df = update_df.where(update_df.notna(), None)
        # Replace empty regime strings
        update_df['regime'] = update_df['regime'].replace('', None)
        
        # Batch update in chunks of 2000
        batch_size = 2000
        total_batches = (len(update_df) + batch_size - 1) // batch_size
        
        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(update_df))
            batch = update_df.iloc[start:end]
            
            records = batch.to_dict('records')
            
            # Clean records — convert numpy types to Python native
            clean_records = []
            for rec in records:
                clean = {}
                for k, v in rec.items():
                    if isinstance(v, (np.integer,)):
                        clean[k] = int(v)
                    elif isinstance(v, (np.floating,)):
                        clean[k] = float(v) if not np.isnan(v) else None
                    elif v is pd.NaT or v is np.nan:
                        clean[k] = None
                    else:
                        clean[k] = v
                clean_records.append(clean)
            
            try:
                db.execute(text("""
                    UPDATE candles SET
                        rsi_14 = :rsi_14,
                        ema_9 = :ema_9,
                        ema_21 = :ema_21,
                        ema_50 = :ema_50,
                        macd = :macd,
                        macd_signal = :macd_signal,
                        macd_histogram = :macd_histogram,
                        bollinger_upper = :bollinger_upper,
                        bollinger_middle = :bollinger_middle,
                        bollinger_lower = :bollinger_lower,
                        atr_14 = :atr_14,
                        returns = :returns,
                        momentum_5 = :momentum_5,
                        volatility_realized = :volatility_realized,
                        price_position = :price_position,
                        hurst_exponent = :hurst_exponent,
                        ou_deviation = :ou_deviation,
                        regime = :regime
                    WHERE id = :id
                """), clean_records)
                db.commit()
            except Exception as e:
                print(f"   ❌ Batch {batch_idx+1} error: {e}")
                db.rollback()
                continue
            
            if (batch_idx + 1) % 10 == 0 or batch_idx == total_batches - 1:
                print(f"   💾 Committed batch {batch_idx+1}/{total_batches} ({end}/{len(update_df)} rows)")
        
        print(f"   ✅ DB update done in {time.time()-t3:.1f}s")
        
        # ============================================================
        # SUMMARY
        # ============================================================
        total_time = time.time() - t0
        print(f"\n🎉 Complete backfill finished in {total_time:.1f}s ({total_time/60:.1f} min)")
        print(f"   📊 Processed: {len(df)} candles")
        print(f"   🧮 Indicators: RSI, EMA(9/21/50), MACD, BB, ATR, Hurst, OU, Regime")
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    backfill_all()
