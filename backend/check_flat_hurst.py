"""Check for flat Hurst lines in today's data"""
import pandas as pd
from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()

query = text("""
    SELECT 
        open_time,
        open_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota' as bogota_time,
        hurst_exponent,
        regime
    FROM candles
    WHERE symbol = 'R_100' 
      AND DATE(open_time) = '2026-02-19'
    ORDER BY open_time ASC
""")
rows = db.execute(query).fetchall()

print(f"Total candles today: {len(rows)}")
print()

prev_h = None
flat_start = None
flat_count = 0
flat_regions = []

for r in rows:
    h = float(r.hurst_exponent) if r.hurst_exponent is not None else None
    bt = str(r.bogota_time)[:19]
    regime = r.regime or 'NULL'
    
    if h is not None and prev_h is not None and abs(h - prev_h) < 0.0001:
        flat_count += 1
        if flat_start is None:
            flat_start = bt
    else:
        if flat_count > 3:
            flat_regions.append((flat_start, bt, flat_count, prev_h))
        flat_count = 0
        flat_start = None
    
    prev_h = h

# Final flat region
if flat_count > 3 and flat_start:
    flat_regions.append((flat_start, bt, flat_count, prev_h))

print(f"Found {len(flat_regions)} flat regions:")
print(f"{'Start':<22} {'End':<22} {'Length':>6} {'Value':>8}")
print("-" * 62)
for start, end, count, val in flat_regions:
    print(f"🔴 {start:<20} {end:<20} {count:>6} {val:>8.4f}")

# Also check NULL gaps
null_ranges = []
in_null = False
null_start = None
null_count_val = 0

for r in rows:
    bt = str(r.bogota_time)[:19]
    if r.hurst_exponent is None:
        if not in_null:
            null_start = bt
            in_null = True
        null_count_val += 1
    else:
        if in_null and null_count_val > 3:
            null_ranges.append((null_start, bt, null_count_val))
        in_null = False
        null_count_val = 0

if in_null and null_count_val > 3:
    null_ranges.append((null_start, bt, null_count_val))

print(f"\nFound {len(null_ranges)} NULL gaps:")
for start, end, count in null_ranges:
    print(f"⚫ {start} to {end} ({count} candles)")

# Show sample around flat areas  
print("\n--- Sample around first flat region ---")
if flat_regions:
    # Find candles near the first flat region
    target = flat_regions[0][0][:16]  # First flat start
    for r in rows:
        bt = str(r.bogota_time)[:19]
        if bt[:13] >= target[:13]:
            h = float(r.hurst_exponent) if r.hurst_exponent is not None else None
            print(f"  {bt}  H={h}")
            # Print 20 around it
            break

db.close()
