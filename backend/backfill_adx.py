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

print(f"Total candles: {len(rows)}")
if len(rows) == 0:
    print("No candles found!")
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
print("Writing to DB...")
t0 = time.time()

batch = []
for i in range(14, len(ids)):
    a = float(adx.iloc[i])
    p = float(plus_di.iloc[i])
    m = float(minus_di.iloc[i])
    if np.isnan(a) or np.isnan(p) or np.isnan(m):
        continue
    batch.append({"id": ids[i], "adx": round(a, 4), "pdi": round(p, 4), "mdi": round(m, 4)})
    
    if len(batch) >= 5000:
        db.execute(text("""
            UPDATE candles SET adx_14 = u.adx, plus_di = u.pdi, minus_di = u.mdi
            FROM (SELECT unnest(:ids::bigint[]) as id, unnest(:adx::float[]) as adx,
                         unnest(:pdi::float[]) as pdi, unnest(:mdi::float[]) as mdi) u
            WHERE candles.id = u.id
        """), {
            "ids": [b["id"] for b in batch],
            "adx": [b["adx"] for b in batch],
            "pdi": [b["pdi"] for b in batch],
            "mdi": [b["mdi"] for b in batch],
        })
        db.commit()
        elapsed = time.time() - t0
        pct = i / len(ids) * 100
        rate = i / elapsed if elapsed > 0 else 0
        print(f"   ✅ {i}/{len(ids)} ({pct:.1f}%) - {rate:.0f} rows/s")
        batch = []

if batch:
    db.execute(text("""
        UPDATE candles SET adx_14 = u.adx, plus_di = u.pdi, minus_di = u.mdi
        FROM (SELECT unnest(:ids::bigint[]) as id, unnest(:adx::float[]) as adx,
                     unnest(:pdi::float[]) as pdi, unnest(:mdi::float[]) as mdi) u
        WHERE candles.id = u.id
    """), {
        "ids": [b["id"] for b in batch],
        "adx": [b["adx"] for b in batch],
        "pdi": [b["pdi"] for b in batch],
        "mdi": [b["mdi"] for b in batch],
    })
    db.commit()

elapsed = time.time() - t0
print(f"🎉 ADX COMPLETE — {len(ids)} rows in {elapsed:.0f}s")
db.close()
