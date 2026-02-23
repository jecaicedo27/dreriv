"""Check Hurst values in a specific time range"""
from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()

# 17:46-18:25 Bogota = 22:46-23:25 UTC on 2026-02-19
rows = db.execute(text("""
    SELECT 
        open_time,
        open_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota' as bogota,
        hurst_exponent,
        ou_deviation,
        regime
    FROM candles
    WHERE symbol = 'R_100'
      AND open_time >= '2026-02-19 22:46:00+00'
      AND open_time <= '2026-02-19 23:30:00+00'
    ORDER BY open_time ASC
""")).fetchall()

print(f"Candles in range: {len(rows)}")
print(f"{'Bogota':<22} {'Hurst':>8} {'OU':>8} {'Regime':<15}")
print("-" * 58)

prev = None
for r in rows:
    h = float(r.hurst_exponent) if r.hurst_exponent else None
    bt = str(r.bogota)[:19]
    ou = float(r.ou_deviation) if r.ou_deviation else 0
    regime = r.regime or 'NULL'
    
    marker = ""
    if prev is not None and h is not None and abs(h - prev) < 0.0001:
        marker = " ← SAME"
    
    h_str = f"{h:>8.4f}" if h is not None else "    NULL"
    print(f"{bt}  {h_str}  {ou:>8.2f}  {regime:<15}{marker}")
    prev = h

# Also check what the endpoint returns for this range
print("\n--- Endpoint query (with LEFT JOIN) ---")
rows2 = db.execute(text("""
    SELECT 
        c.open_time,
        c.open_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota' as bogota,
        c.hurst_exponent,
        a.final_signal, a.final_confidence
    FROM candles c
    LEFT JOIN analysis_history a 
        ON a.timestamp >= c.open_time 
        AND a.timestamp < c.open_time + interval '1 minute'
    WHERE c.symbol = 'R_100'
      AND c.open_time >= '2026-02-19 22:46:00+00'
      AND c.open_time <= '2026-02-19 23:30:00+00'
    ORDER BY c.open_time ASC
""")).fetchall()

print(f"\nJOIN result rows: {len(rows2)} (should be {len(rows)} if no duplicates)")
dup_count = len(rows2) - len(rows)
if dup_count > 0:
    print(f"⚠️  {dup_count} DUPLICATE rows from LEFT JOIN!")

db.close()
