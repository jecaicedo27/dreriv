import pandas as pd
import numpy as np
from sqlalchemy import text
from app.core.database import SessionLocal
import time

db = SessionLocal()
print("BACKFILL: StochRSI (14-period RSI, 14-period stoch, 3-period smooth)")
print("=" * 60)

print("Loading candles...")
rows = db.execute(text(
    "SELECT id, rsi_14 FROM candles WHERE symbol = 'R_100' AND rsi_14 IS NOT NULL ORDER BY open_time ASC"
)).fetchall()

n = len(rows)
print(f"Candles with RSI: {n}")
if n == 0:
    db.close()
    exit()

ids = [r.id for r in rows]
rsi = pd.Series([float(r.rsi_14) for r in rows])

# StochRSI = (RSI - RSI_min_14) / (RSI_max_14 - RSI_min_14) * 100
# Then smooth with 3-period SMA (K line)
rsi_min = rsi.rolling(window=14).min()
rsi_max = rsi.rolling(window=14).max()
stoch_rsi_raw = ((rsi - rsi_min) / (rsi_max - rsi_min + 1e-10)) * 100
stoch_rsi = stoch_rsi_raw.rolling(window=3).mean()  # Smoothed K line

valid = ~stoch_rsi.isna()
print(f"Valid StochRSI values: {valid.sum()}")
print(f"Sample: last={stoch_rsi.iloc[-1]:.2f}, mean={stoch_rsi[valid].mean():.2f}")

print("Writing to DB in batches...")
t0 = time.time()

batch_size = 2000
updated = 0
for start in range(16, n, batch_size):
    end = min(start + batch_size, n)
    values = []
    params = {}
    for j, i in enumerate(range(start, end)):
        v = float(stoch_rsi.iloc[i])
        if np.isnan(v):
            continue
        params[f"id_{j}"] = ids[i]
        params[f"v_{j}"] = round(v, 4)
        values.append(f"(:id_{j}, :v_{j})")
    
    if not values:
        continue
    
    sql = f"""
        UPDATE candles SET stoch_rsi = v.val
        FROM (VALUES {', '.join(values)}) AS v(id, val)
        WHERE candles.id = v.id
    """
    db.execute(text(sql), params)
    db.commit()
    updated += len(values)
    
    if updated % 20000 < batch_size:
        elapsed = time.time() - t0
        pct = end / n * 100
        rate = updated / elapsed if elapsed > 0 else 0
        print(f"   {end}/{n} ({pct:.1f}%) - {rate:.0f} rows/s")

elapsed = time.time() - t0
print(f"StochRSI COMPLETE - {updated} rows in {elapsed:.0f}s")
db.close()
