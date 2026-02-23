"""
Backfill missing indicators for all historical candles.
Handles: log_returns, momentum_10, volume_delta, momentum_5, price_position, garch_volatility_forecast
"""
import os, sys
sys.path.insert(0, '/app')

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://deriv_bot:deriv_bot_2024@postgres:5432/deriv_bot')
engine = create_engine(DATABASE_URL)
BATCH = 5000

def backfill_simple_indicators():
    """Backfill log_returns, momentum_10, volume_delta, momentum_5, price_position using SQL + pandas"""
    print("=" * 60)
    print("📊 PHASE 1: Simple indicators (log_returns, momentum_10, volume_delta, momentum_5, price_position)")
    print("=" * 60)
    
    with engine.connect() as conn:
        # Load all candles ordered by time
        print("📥 Loading candles...")
        df = pd.read_sql("""
            SELECT id, open_time, open, high, low, close, volume,
                   log_returns, momentum_10, volume_delta, momentum_5, price_position
            FROM candles WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """, conn)
        print(f"   Loaded {len(df):,} candles")
        
        # Calculate missing indicators
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        volume = df['volume'].astype(float)
        
        # log_returns = ln(close / prev_close)
        calc_log_returns = np.log(close / close.shift(1))
        # momentum_10 = close - close_10_ago
        calc_momentum_10 = close - close.shift(10)
        # momentum_5 = close - close_5_ago
        calc_momentum_5 = close - close.shift(5)
        # volume_delta = volume - prev_volume
        calc_volume_delta = volume - volume.shift(1)
        # price_position = (close - low) / (high - low)
        calc_price_position = (close - low) / (high - low + 1e-10)
        
        updates = []
        calculated = 0
        
        for i in range(len(df)):
            needs_update = False
            row_update = {"cid": int(df['id'].iloc[i])}
            
            # log_returns
            if pd.isna(df['log_returns'].iloc[i]) and not pd.isna(calc_log_returns.iloc[i]):
                row_update["lr"] = round(float(calc_log_returns.iloc[i]), 8)
                needs_update = True
            
            # momentum_10
            if pd.isna(df['momentum_10'].iloc[i]) and not pd.isna(calc_momentum_10.iloc[i]):
                row_update["m10"] = round(float(calc_momentum_10.iloc[i]), 8)
                needs_update = True
            
            # momentum_5
            if pd.isna(df['momentum_5'].iloc[i]) and not pd.isna(calc_momentum_5.iloc[i]):
                row_update["m5"] = round(float(calc_momentum_5.iloc[i]), 8)
                needs_update = True
            
            # volume_delta
            if pd.isna(df['volume_delta'].iloc[i]) and not pd.isna(calc_volume_delta.iloc[i]):
                row_update["vd"] = round(float(calc_volume_delta.iloc[i]), 4)
                needs_update = True
            
            # price_position
            if pd.isna(df['price_position'].iloc[i]) and not pd.isna(calc_price_position.iloc[i]):
                row_update["pp"] = round(float(calc_price_position.iloc[i]), 8)
                needs_update = True
            
            if needs_update:
                updates.append(row_update)
                calculated += 1
            
            if len(updates) >= BATCH:
                _flush_simple(conn, updates)
                print(f"   ✅ Progress: {calculated:,} rows updated ({i+1:,}/{len(df):,})")
                updates = []
        
        if updates:
            _flush_simple(conn, updates)
        
        print(f"\n✅ Phase 1 complete: {calculated:,} rows updated")


def _flush_simple(conn, updates):
    """Batch update simple indicators"""
    for u in updates:
        sets = []
        params = {"cid": u["cid"]}
        if "lr" in u:
            sets.append("log_returns = :lr")
            params["lr"] = u["lr"]
        if "m10" in u:
            sets.append("momentum_10 = :m10")
            params["m10"] = u["m10"]
        if "m5" in u:
            sets.append("momentum_5 = :m5")
            params["m5"] = u["m5"]
        if "vd" in u:
            sets.append("volume_delta = :vd")
            params["vd"] = u["vd"]
        if "pp" in u:
            sets.append("price_position = :pp")
            params["pp"] = u["pp"]
        if sets:
            conn.execute(text(f"UPDATE candles SET {', '.join(sets)} WHERE id = :cid"), params)
    conn.commit()


def backfill_garch():
    """Backfill garch_volatility_forecast using rolling GARCH(1,1)"""
    print("\n" + "=" * 60)
    print("📊 PHASE 2: GARCH volatility forecast")
    print("=" * 60)
    
    from arch import arch_model
    
    GARCH_WINDOW = 100
    
    with engine.connect() as conn:
        # Check how many need backfilling
        null_count = conn.execute(text(
            "SELECT COUNT(*) FROM candles WHERE garch_volatility_forecast IS NULL"
        )).scalar()
        print(f"   Need to calculate: {null_count:,} candles")
        
        if null_count == 0:
            print("   Nothing to do!")
            return
        
        # Load all candles
        print("📥 Loading candles...")
        df = pd.read_sql("""
            SELECT id, open_time, close, returns, garch_volatility_forecast
            FROM candles WHERE symbol = 'R_100'
            ORDER BY open_time ASC
        """, conn)
        print(f"   Loaded {len(df):,} candles")
        
        # Calculate returns if missing
        close = df['close'].astype(float)
        returns = close.pct_change()
        
        updates = []
        calculated = 0
        errors = 0
        
        # Process in chunks - fit GARCH every 50 candles to avoid refitting for each one
        FIT_INTERVAL = 50
        last_forecast_values = None
        
        for i in range(GARCH_WINDOW, len(df)):
            if not pd.isna(df['garch_volatility_forecast'].iloc[i]):
                continue  # Already has value
            
            # Fit GARCH every FIT_INTERVAL candles (or on first one)
            if last_forecast_values is None or (calculated % FIT_INTERVAL == 0):
                window_returns = returns.iloc[max(0, i-GARCH_WINDOW):i].dropna()
                
                if len(window_returns) < 50:
                    continue
                
                try:
                    returns_pct = window_returns * 100
                    model = arch_model(returns_pct, vol='Garch', p=1, q=1, rescale=False)
                    fitted = model.fit(disp='off', show_warning=False)
                    forecast = fitted.forecast(horizon=5)
                    variance = forecast.variance.values[-1, :]
                    last_forecast_values = np.sqrt(variance)
                except Exception:
                    errors += 1
                    continue
            
            if last_forecast_values is not None:
                garch_val = round(float(np.mean(last_forecast_values)), 8)
                updates.append({"cid": int(df['id'].iloc[i]), "gv": garch_val})
                calculated += 1
            
            if len(updates) >= BATCH:
                for u in updates:
                    conn.execute(text(
                        "UPDATE candles SET garch_volatility_forecast = :gv WHERE id = :cid"
                    ), u)
                conn.commit()
                print(f"   ✅ GARCH progress: {calculated:,} calculated, {errors} errors ({i+1:,}/{len(df):,})")
                updates = []
        
        if updates:
            for u in updates:
                conn.execute(text(
                    "UPDATE candles SET garch_volatility_forecast = :gv WHERE id = :cid"
                ), u)
            conn.commit()
        
        print(f"\n✅ Phase 2 complete: {calculated:,} GARCH values calculated ({errors} errors)")


if __name__ == "__main__":
    print("🚀 Starting indicator backfill...")
    print()
    backfill_simple_indicators()
    backfill_garch()
    print("\n🎉 All backfill complete!")
