import pandas as pd
import numpy as np
from sqlalchemy import text
from app.core.database import SessionLocal
import time

db = SessionLocal()
print("BACKFILL: ADX (14-period)")
print("=" * 60)

print("Loading candles...")
rows = db.execute(text(
    "SELECT id, high, low, close FROM candles WHERE symbol = 'R_100' ORDER BY open_time ASC"
)).fetchall()

n = len(rows)
print(f"Total candles: {n}")
if n == 0:
    db.close()
    exit()

ids = [r.id for r in rows]
highs = pd.Series([float(r.high) for r in rows])
lows = pd.Series([float(r.low) for r in rows])
closes = pd.Series([float(r.close) for r in rows])

high_low = highs - lows
high_close = np.abs(highs - closes.shift())
low_close = np.abs(lows - closes.shift())
tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

up_move = highs - highs.shift(1)
down_move = lows.shift(1) - lows
plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

atr_smooth = tr.ewm(alpha=1/14, adjust=False).mean()
plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/14, adjust=False).mean() / (atr_smooth + 1e-10)
minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/14, adjust=False).mean() / (atr_smooth + 1e-10)
dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
adx = dx.ewm(alpha=1/14, adjust=False).mean()

print(f"ADX computed. Sample: ADX={float(adx.iloc[-1]):.2f}, +DI={float(plus_di.iloc[-1]):.2f}, -DI={float(minus_di.iloc[-1]):.2f}")
print("Writing to DB in batches...")
t0 = time.time()

batch_size = 2000
updated = 0
for start in range(14, n, batch_size):
    end = min(start + batch_size, n)
    # Build VALUES list for batch update
    values = []
    params = {}
    for j, i in enumerate(range(start, end)):
        a = float(adx.iloc[i])
        p = float(plus_di.iloc[i])
        m = float(minus_di.iloc[i])
        if np.isnan(a) or np.isnan(p) or np.isnan(m):
            continue
        params[f"id_{j}"] = ids[i]
        params[f"a_{j}"] = round(a, 4)
        params[f"p_{j}"] = round(p, 4)
        params[f"m_{j}"] = round(m, 4)
        values.append(f"(:id_{j}, :a_{j}, :p_{j}, :m_{j})")
    
    if not values:
        continue
    
    sql = f"""
        UPDATE candles SET adx_14 = v.adx, plus_di = v.pdi, minus_di = v.mdi
        FROM (VALUES {', '.join(values)}) AS v(id, adx, pdi, mdi)
        WHERE candles.id = v.id
    """
    db.execute(text(sql), params)
    db.commit()
    updated += len(values)
    
    elapsed = time.time() - t0
    pct = end / n * 100
    rate = updated / elapsed if elapsed > 0 else 0
    print(f"   ✅ {end}/{n} ({pct:.1f}%) - {rate:.0f} rows/s - {updated} updated")

elapsed = time.time() - t0
print(f"🎉 ADX COMPLETE — {updated} rows in {elapsed:.0f}s")
db.close()
