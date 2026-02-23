"""Backfill log_returns & volume_delta for all R_100 candles."""
import pandas as pd, numpy as np, time
from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()
print("BACKFILL: log_returns & volume_delta")

rows = db.execute(text(
    "SELECT id, close, volume FROM candles WHERE symbol='R_100' ORDER BY open_time ASC"
)).fetchall()
n = len(rows)
print(f"Total: {n}")

ids = [r.id for r in rows]
closes = pd.Series([float(r.close) for r in rows])
vols = pd.Series([float(r.volume) for r in rows])

lr = np.log(closes / closes.shift(1))
vd = vols - vols.shift(1)

t0 = time.time()
bs = 2500
up = 0
for s in range(1, n, bs):
    e = min(s + bs, n)
    vals, p = [], {}
    for j, i in enumerate(range(s, e)):
        a, b = float(lr.iloc[i]), float(vd.iloc[i])
        if np.isnan(a) or np.isnan(b): continue
        p[f"i{j}"], p[f"l{j}"], p[f"v{j}"] = ids[i], round(a, 8), round(b, 2)
        vals.append(f"(:i{j},:l{j},:v{j})")
    if not vals: continue
    db.execute(text(f"UPDATE candles SET log_returns=v.l,volume_delta=v.v FROM (VALUES {','.join(vals)}) AS v(i,l,v) WHERE candles.id=v.i"), p)
    db.commit()
    up += len(vals)
    if up % 25000 < bs:
        print(f"  {e}/{n} ({e*100/n:.1f}%) {up/(time.time()-t0):.0f}r/s")

print(f"DONE: {up} rows in {time.time()-t0:.0f}s")
db.close()
