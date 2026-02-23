"""
Two-Pass Indicator Backfill (Optimized)

Pass 1 (FAST - seconds): Update ALL rows with standard indicators
  - RSI, EMA(9/21/50), MACD, BB, ATR, momentum, etc.
  - Uses vectorized pandas operations = instant
  - Commits immediately so simulations work right away

Pass 2 (SLOW - background): Calculate Hurst/OU only for NULL rows
  - Skips rows that already have valid Hurst
  - ~178k rows at ~22/s = ~2.2 hours
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

# Suppress all loguru
logger.remove()
logger.add(sys.stderr, format="{message}", level="CRITICAL")


def pass1_standard_indicators():
    """Fast pass: vectorized standard indicators for ALL candles"""
    db = SessionLocal()
    try:
        print("=" * 60)
        print("PASS 1: Standard Indicators (vectorized)")
        print("=" * 60)
        
        t0 = time.time()
        print("📥 Loading all OHLCV data...")
        
        query = text("""
            SELECT id, open_time, open, high, low, close, volume
            FROM candles 
            WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind)
        print(f"📊 Loaded {len(df)} candles in {time.time()-t0:.1f}s")
        
        # Calculate all standard indicators at once (vectorized)
        print("🧮 Calculating standard indicators...")
        t1 = time.time()
        df_calc = TechnicalIndicators.calculate_all(df.copy())
        print(f"   ✅ Calculated in {time.time()-t1:.1f}s")
        
        # Build update records
        print("💾 Updating database...")
        t2 = time.time()
        
        # Only update indicator columns (not OHLCV which is already correct)
        indicator_cols = [
            'rsi_14', 'ema_9', 'ema_21', 'ema_50',
            'macd', 'macd_signal', 'macd_histogram',
            'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
            'atr_14', 'returns', 'momentum_5',
            'volatility_realized', 'price_position',
            'log_returns', 'volume_delta'
        ]
        
        batch_size = 5000
        total_batches = (len(df_calc) + batch_size - 1) // batch_size
        
        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(df_calc))
            
            records = []
            for i in range(start, end):
                rec = {'id': int(df_calc.iloc[i]['id'])}
                for col in indicator_cols:
                    val = df_calc.iloc[i].get(col)
                    if pd.isna(val):
                        rec[col] = None
                    elif isinstance(val, (np.integer,)):
                        rec[col] = int(val)
                    elif isinstance(val, (np.floating,)):
                        rec[col] = float(val)
                    else:
                        rec[col] = val
                records.append(rec)
            
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
                        log_returns = :log_returns,
                        volume_delta = :volume_delta
                    WHERE id = :id
                """), records)
                db.commit()
            except Exception as e:
                print(f"   ❌ Batch {batch_idx+1} error: {e}")
                db.rollback()
            
            if (batch_idx + 1) % 10 == 0 or batch_idx == total_batches - 1:
                print(f"   💾 Batch {batch_idx+1}/{total_batches} ({end}/{len(df_calc)})")
        
        print(f"   ✅ Standard indicators updated in {time.time()-t2:.1f}s")
        print(f"🎉 PASS 1 COMPLETE — Total: {time.time()-t0:.1f}s")
        print()
        
    except Exception as e:
        print(f"❌ Pass 1 error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def pass2_hurst_ou():
    """Slow pass: Hurst + OU only for NULL rows"""
    db = SessionLocal()
    try:
        print("=" * 60)
        print("PASS 2: Hurst + OU (rolling window, NULL rows only)")
        print("=" * 60)
        
        t0 = time.time()
        
        # Load all close prices for context
        print("📥 Loading close prices...")
        query = text("""
            SELECT id, open_time, close 
            FROM candles 
            WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind)
        
        # Get missing IDs
        missing_ids = set(
            row[0] for row in 
            db.execute(text("SELECT id FROM candles WHERE hurst_exponent IS NULL")).fetchall()
        )
        
        total_missing = len(missing_ids)
        print(f"📊 Total candles: {len(df)}, Missing Hurst: {total_missing}")
        
        if total_missing == 0:
            print("✅ All candles already have Hurst!")
            return
        
        window = 200
        ou_model = OrnsteinUhlenbeckModel(window=window)
        prices = df['close'].values
        ids = df['id'].values
        
        updates = []
        batch_size = 2000
        processed = 0
        
        for i in range(window, len(df)):
            current_id = int(ids[i])
            
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
            try:
                if ou_model.fit(price_series):
                    ou_dev = ou_model.get_deviation(window_prices[-1])
                    ou_dev = float(ou_dev) if ou_dev is not None else 0.0
            except:
                pass
            
            updates.append({
                'id': current_id,
                'hurst_exponent': float(h_val),
                'ou_deviation': ou_dev,
                'regime': regime
            })
            
            if len(updates) >= batch_size:
                _bulk_update(db, updates)
                processed += len(updates)
                updates = []
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = (total_missing - processed) / rate if rate > 0 else 0
                print(f"   ✅ {processed}/{total_missing} ({processed/total_missing*100:.1f}%) - {rate:.0f}/s - ETA: {remaining/60:.1f}min")
        
        if updates:
            _bulk_update(db, updates)
            processed += len(updates)
        
        print(f"🎉 PASS 2 COMPLETE — {processed} rows in {(time.time()-t0)/60:.1f} min")
        
    except Exception as e:
        print(f"❌ Pass 2 error: {e}")
        import traceback
        traceback.print_exc()
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
        print(f"   ❌ Batch error: {e}")
        db.rollback()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--pass2-only':
        pass2_hurst_ou()
    else:
        # Run Pass 1 (fast), then Pass 2 (slow)
        pass1_standard_indicators()
        pass2_hurst_ou()
