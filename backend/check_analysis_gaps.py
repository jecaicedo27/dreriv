"""Check AnalysisHistory vs candles density"""
from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()

# Count
r = db.execute(text("SELECT COUNT(*) as cnt FROM analysis_history WHERE DATE(timestamp) = '2026-02-19'")).fetchone()
print(f"AnalysisHistory today: {r.cnt} records")

r2 = db.execute(text("SELECT COUNT(*) as cnt FROM candles WHERE DATE(open_time) = '2026-02-19' AND hurst_exponent IS NOT NULL")).fetchone()
print(f"Candles with Hurst today: {r2.cnt} records")

# Check gaps in AnalysisHistory
rows = db.execute(text("SELECT timestamp FROM analysis_history WHERE DATE(timestamp) = '2026-02-19' ORDER BY timestamp ASC")).fetchall()
if rows:
    print(f"First: {rows[0].timestamp}")
    print(f"Last: {rows[-1].timestamp}")
    
    gaps = []
    for i in range(1, len(rows)):
        diff = (rows[i].timestamp - rows[i-1].timestamp).total_seconds()
        if diff > 300:
            gaps.append((str(rows[i-1].timestamp)[:19], str(rows[i].timestamp)[:19], diff/60))
    
    print(f"\nGaps > 5min: {len(gaps)}")
    for start, end, mins in gaps[:15]:
        print(f"  GAP: {start} -> {end} ({mins:.0f} min)")
else:
    print("No records found")

db.close()
