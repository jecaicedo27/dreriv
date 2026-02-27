"""Count how many candles pass each gate of Malicia engine"""
from app.core.database import SessionLocal
from sqlalchemy import text
import pandas as pd
import numpy as np

db = SessionLocal()
rows = db.execute(text("""
    SELECT open, high, low, close, open_time, 
           ema_9, ema_21, ema_50, rsi_14, atr_14,
           macd_histogram, bollinger_upper, bollinger_lower, bollinger_middle,
           momentum_5, hurst_exponent, hurst_fast
    FROM candles 
    WHERE open_time >= '2026-02-26' AND open_time < '2026-02-27'
    ORDER BY open_time
""")).fetchall()
db.close()

cols = ['open','high','low','close','open_time','ema_9','ema_21','ema_50','rsi_14','atr_14',
        'macd_histogram','bollinger_upper','bollinger_lower','bollinger_middle',
        'momentum_5','hurst_exponent','hurst_fast']
df = pd.DataFrame(rows, columns=cols)
for c in cols:
    if c != 'open_time':
        df[c] = pd.to_numeric(df[c], errors='coerce')

print(f"Total candles: {len(df)}")

# Count gates
total = len(df)
g1_bull = 0  # bullish candle
g2_body = 0  # body in range
g3_ema = 0   # triple EMA
g4_above = 0 # price above EMA9
g5_streak = 0 # green streak
g6_rsi = 0   # RSI range
g7_hurst = 0 # hurst trending
all_pass = 0

for i in range(3, len(df)):
    c = df.iloc[i]
    o1, c1 = float(c['open']), float(c['close'])
    if c1 <= o1: continue
    g1_bull += 1
    
    atr = float(c['atr_14'] or 1)
    if atr <= 0: atr = 1
    body = c1 - o1
    body_atr = body / atr
    if body_atr < 0.10 or body_atr > 5.0: continue
    g2_body += 1
    
    e9 = float(c['ema_9'] or 0)
    e21 = float(c['ema_21'] or 0)
    e50 = float(c['ema_50'] or 0)
    if not (e9 > 0 and e21 > 0 and e50 > 0): continue
    if not (e9 > e21 > e50): continue
    g3_ema += 1
    
    if c1 < e9: continue
    g4_above += 1
    
    # green streak
    green = 0
    for j in range(2, min(8, i+1)):
        prev = df.iloc[i-j]
        if float(prev['close']) > float(prev['open']):
            green += 1
        else:
            break
    if green < 2: continue
    g5_streak += 1
    
    rsi = float(c['rsi_14'] or 50)
    if rsi < 35 or rsi > 78: continue
    g6_rsi += 1
    
    hf = float(c['hurst_fast'] or 0)
    hs = float(c['hurst_exponent'] or 0)
    hv = hf if hf > 0 else hs
    if hv == 0: hv = 0.5
    if hv < 0.53: continue
    g7_hurst += 1
    all_pass += 1

print(f"\n=== GATE FUNNEL (Feb 26) ===")
print(f"Total candles:        {total:>5}")
print(f"G1 Bullish candle:    {g1_bull:>5} ({g1_bull/total*100:.1f}%)")
print(f"G2 Body in range:     {g2_body:>5} ({g2_body/total*100:.1f}%)")
print(f"G3 EMA9>21>50:        {g3_ema:>5} ({g3_ema/total*100:.1f}%) ← triple alignment")
print(f"G4 Price > EMA9:      {g4_above:>5} ({g4_above/total*100:.1f}%)")
print(f"G5 2+ green streak:   {g5_streak:>5} ({g5_streak/total*100:.1f}%)")
print(f"G6 RSI 35-78:         {g6_rsi:>5} ({g6_rsi/total*100:.1f}%)")
print(f"G7 Hurst > 0.53:      {g7_hurst:>5} ({g7_hurst/total*100:.1f}%)")
print(f"ALL PASS (signals):   {all_pass:>5} ({all_pass/total*100:.1f}%)")
print(f"\nBiggest filter: ", end="")
drops = [
    ("G1→G2", g1_bull - g2_body),
    ("G2→G3 (EMA)", g2_body - g3_ema),
    ("G3→G4", g3_ema - g4_above),
    ("G4→G5 (streak)", g4_above - g5_streak),
    ("G5→G6 (RSI)", g5_streak - g6_rsi),
    ("G6→G7 (Hurst)", g6_rsi - g7_hurst),
]
drops.sort(key=lambda x: -x[1])
for name, drop in drops:
    print(f"\n  {name}: -{drop} candles dropped")
