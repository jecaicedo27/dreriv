"""
Backfill hurst_fast (Variance Ratio) for all historical candles.
Processes in batches of 1000 candles, calculating VR Hurst for each candle
using the preceding 50 candles as the window.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, text
import pandas as pd
import numpy as np
from app.analysis.hurst import HurstExponent

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://deriv_bot:deriv_bot_2024@localhost:5432/deriv_bot")

engine = create_engine(DATABASE_URL)

BATCH_SIZE = 5000
WINDOW = 50

print("🔄 Backfilling hurst_fast (Variance Ratio) for all candles...")

with engine.connect() as conn:
    # Count total candles needing backfill
    total = conn.execute(text("SELECT COUNT(*) FROM candles WHERE hurst_fast IS NULL")).scalar()
    print(f"📊 {total} candles need hurst_fast backfill")
    
    if total == 0:
        print("✅ All candles already have hurst_fast!")
        sys.exit(0)
    
    # Load ALL close prices ordered by time (we need the full series for rolling window)
    print("📥 Loading all close prices...")
    df = pd.read_sql(
        "SELECT id, open_time, close FROM candles WHERE symbol = 'R_100' ORDER BY open_time ASC",
        conn
    )
    print(f"📊 Loaded {len(df)} candles total")
    
    closes = df['close'].astype(float)
    ids = df['id'].values
    
    # Calculate hurst_fast for each candle using rolling window
    updates = []
    calculated = 0
    
    for i in range(len(df)):
        if i < WINDOW:
            # Not enough data for the window
            continue
        
        window_prices = closes.iloc[i - WINDOW:i + 1]
        try:
            hf = HurstExponent.calculate_fast(window_prices, window=WINDOW)
            if hf is not None and not np.isnan(hf):
                updates.append({"cid": int(ids[i]), "hf": round(float(hf), 6)})
                calculated += 1
        except Exception:
            continue
        
        # Batch update every BATCH_SIZE
        if len(updates) >= BATCH_SIZE:
            conn.execute(
                text("UPDATE candles SET hurst_fast = :hf WHERE id = :cid"),
                updates
            )
            conn.commit()
            print(f"  ✅ Updated {calculated}/{total} candles...")
            updates = []
    
    # Final batch
    if updates:
        conn.execute(
            text("UPDATE candles SET hurst_fast = :hf WHERE id = :cid"),
            updates
        )
        conn.commit()
    
    print(f"✅ Backfill complete! Calculated hurst_fast for {calculated} candles")
