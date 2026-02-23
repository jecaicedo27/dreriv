"""
Backfill hurst_fast + GARCH for all candles with NULL values.

hurst_fast: Uses HurstExponent.calculate_fast(window=50) — faster than full Hurst
GARCH: Uses arch library for volatility forecasting — computationally expensive

Run inside docker: docker exec -d deriv-backend python3 backfill_hurst_garch.py
"""
import sys
import time
import numpy as np
import pandas as pd
from sqlalchemy import text
from app.core.database import SessionLocal
from app.analysis.hurst import HurstExponent
from loguru import logger

# Suppress loguru
logger.remove()
logger.add(sys.stderr, format="{message}", level="CRITICAL")


def backfill_hurst_fast():
    """Backfill hurst_fast for NULL rows using window=50"""
    db = SessionLocal()
    try:
        print("=" * 60)
        print("BACKFILL: hurst_fast (window=50)")
        print("=" * 60)
        
        t0 = time.time()
        
        # Load all close prices
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
            db.execute(text("SELECT id FROM candles WHERE hurst_fast IS NULL")).fetchall()
        )
        
        total_missing = len(missing_ids)
        print(f"📊 Total candles: {len(df)}, Missing hurst_fast: {total_missing}")
        
        if total_missing == 0:
            print("✅ All candles already have hurst_fast!")
            return
        
        window = 50  # hurst_fast uses smaller window
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
            
            # Calculate hurst_fast
            try:
                h_fast = HurstExponent.calculate_fast(price_series, window)
                h_fast = float(h_fast) if h_fast is not None and not np.isnan(h_fast) else None
            except:
                h_fast = None
            
            if h_fast is not None:
                updates.append({
                    'id': current_id,
                    'hurst_fast': h_fast
                })
            
            if len(updates) >= batch_size:
                _bulk_update_hurst_fast(db, updates)
                processed += len(updates)
                updates = []
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = (total_missing - processed) / rate if rate > 0 else 0
                print(f"   ✅ {processed}/{total_missing} ({processed/total_missing*100:.1f}%) - {rate:.0f}/s - ETA: {remaining/60:.1f}min")
        
        if updates:
            _bulk_update_hurst_fast(db, updates)
            processed += len(updates)
        
        print(f"🎉 hurst_fast COMPLETE — {processed} rows in {(time.time()-t0)/60:.1f} min")
        
    except Exception as e:
        print(f"❌ hurst_fast error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def backfill_garch():
    """Backfill GARCH volatility forecast for NULL rows"""
    db = SessionLocal()
    try:
        print()
        print("=" * 60)
        print("BACKFILL: GARCH volatility forecast")
        print("=" * 60)
        
        t0 = time.time()
        
        # Load all close prices + returns
        print("📥 Loading price data...")
        query = text("""
            SELECT id, open_time, close, returns
            FROM candles 
            WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """)
        df = pd.read_sql(query, db.bind)
        
        # Get missing IDs
        missing_ids = set(
            row[0] for row in 
            db.execute(text("SELECT id FROM candles WHERE garch_volatility_forecast IS NULL")).fetchall()
        )
        
        total_missing = len(missing_ids)
        print(f"📊 Total candles: {len(df)}, Missing GARCH: {total_missing}")
        
        if total_missing == 0:
            print("✅ All candles already have GARCH!")
            return
        
        # GARCH needs arch library
        try:
            from arch import arch_model
        except ImportError:
            print("❌ arch library not installed. Install with: pip install arch")
            return
        
        window = 200
        prices = df['close'].values
        ids = df['id'].values
        returns_col = df['returns'].values
        
        updates = []
        batch_size = 1000
        processed = 0
        errors = 0
        
        for i in range(window, len(df)):
            current_id = int(ids[i])
            
            if current_id not in missing_ids:
                continue
            
            # Use returns for GARCH
            window_returns = returns_col[i-window:i]
            
            # Skip if returns have NaN
            if np.any(np.isnan(window_returns)):
                continue
            
            try:
                # Scale returns for GARCH stability
                scaled = window_returns * 100
                model = arch_model(scaled, vol='GARCH', p=1, q=1, dist='normal', rescale=False)
                result = model.fit(disp='off', show_warning=False)
                forecast = result.forecast(horizon=1)
                vol_forecast = float(forecast.variance.values[-1, 0]) / 10000  # Unscale
                vol_forecast = max(0, min(vol_forecast, 1.0))  # Clamp
                
                updates.append({
                    'id': current_id,
                    'garch_volatility_forecast': vol_forecast
                })
            except:
                errors += 1
                continue
            
            if len(updates) >= batch_size:
                _bulk_update_garch(db, updates)
                processed += len(updates)
                updates = []
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = (total_missing - processed) / rate if rate > 0 else 0
                print(f"   ✅ {processed}/{total_missing} ({processed/total_missing*100:.1f}%) - {rate:.0f}/s - ETA: {remaining/60:.1f}min (errors: {errors})")
        
        if updates:
            _bulk_update_garch(db, updates)
            processed += len(updates)
        
        print(f"🎉 GARCH COMPLETE — {processed} rows in {(time.time()-t0)/60:.1f} min (errors: {errors})")
        
    except Exception as e:
        print(f"❌ GARCH error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def _bulk_update_hurst_fast(db, mappings):
    try:
        db.execute(text("""
            UPDATE candles SET hurst_fast = :hurst_fast WHERE id = :id
        """), mappings)
        db.commit()
    except Exception as e:
        print(f"   ❌ Batch error: {e}")
        db.rollback()


def _bulk_update_garch(db, mappings):
    try:
        db.execute(text("""
            UPDATE candles SET garch_volatility_forecast = :garch_volatility_forecast WHERE id = :id
        """), mappings)
        db.commit()
    except Exception as e:
        print(f"   ❌ Batch error: {e}")
        db.rollback()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--garch-only':
        backfill_garch()
    elif len(sys.argv) > 1 and sys.argv[1] == '--hurst-only':
        backfill_hurst_fast()
    else:
        # Run both: hurst_fast first (faster), then GARCH (slower)
        backfill_hurst_fast()
        backfill_garch()
