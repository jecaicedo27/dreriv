"""
Recalculate Hurst per-candle for a specific time range.
Fixes batch-stamped values from the incorrect bulk update.
"""
import pandas as pd
import numpy as np
from sqlalchemy import text
from app.core.database import SessionLocal
from app.analysis.hurst import HurstExponent
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel

db = SessionLocal()

# Get ALL candles (need 200 before the target range for window)
print("📥 Loading candles...")
all_candles = db.execute(text("""
    SELECT id, open_time, close
    FROM candles
    WHERE symbol = 'R_100'
    ORDER BY open_time ASC
""")).fetchall()

print(f"   Loaded {len(all_candles)} candles")

# Build price array
ids = [r.id for r in all_candles]
times = [r.open_time for r in all_candles]
prices = np.array([float(r.close) for r in all_candles])

# Find candles that need recalculation (all of today that might be batch-stamped)
# Recalc everything from today
updates = []
window = 200

print("🧮 Recalculating Hurst per-candle...")
for i in range(window, len(prices)):
    # Only process today's candles
    if times[i].date().isoformat() != '2026-02-19':
        continue
    
    price_window = pd.Series(prices[i-window:i+1])
    
    # Hurst
    hurst_val = HurstExponent.calculate(price_window, window=window)
    hurst_info = HurstExponent.interpret(hurst_val)
    
    # O-U
    ou_model = OrnsteinUhlenbeckModel(window=window)
    ou_dev = 0.0
    if ou_model.fit(price_window):
        ou_dev = ou_model.get_deviation(prices[i])
    
    updates.append({
        'id': ids[i],
        'hurst': float(hurst_val),
        'ou_dev': float(ou_dev),
        'regime': hurst_info.get('regime', 'RANDOM')
    })

print(f"   Calculated {len(updates)} candles")

# Batch update
print("💾 Writing to database...")
for batch_start in range(0, len(updates), 500):
    batch = updates[batch_start:batch_start+500]
    for u in batch:
        db.execute(text("""
            UPDATE candles 
            SET hurst_exponent = :hurst,
                ou_deviation = :ou_dev,
                regime = :regime
            WHERE id = :id
        """), u)
    db.commit()
    print(f"   ✅ Updated {min(batch_start+500, len(updates))}/{len(updates)}")

# Verify
print("\n📊 Verification (sample every 5 min):")
rows = db.execute(text("""
    SELECT 
        open_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota' as bogota,
        hurst_exponent, ou_deviation
    FROM candles
    WHERE symbol = 'R_100'
      AND open_time >= '2026-02-19 22:40:00+00'
      AND open_time <= '2026-02-19 23:20:00+00'
    ORDER BY open_time ASC
""")).fetchall()
for i, r in enumerate(rows):
    if i % 5 == 0:
        h = f'{float(r.hurst_exponent):.4f}' if r.hurst_exponent else 'NULL'
        ou = f'{float(r.ou_deviation):>7.2f}' if r.ou_deviation else '   NULL'
        print(f"  {str(r.bogota)[:19]}  H={h}  OU={ou}")

db.close()
print("\n🎉 Done!")
