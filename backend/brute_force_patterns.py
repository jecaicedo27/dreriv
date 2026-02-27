"""
Brute Force Candlestick Pattern Scanner for PUT trades.

Tests thousands of pattern variations across 271K+ candles to find
combinations with WR > 55% and high frequency.

Features tested per candle:
- Body type (bearish/bullish/doji)
- Body size relative to ATR
- Upper/lower wick ratios
- Body position within range
- Multi-candle sequences (2-candle, 3-candle patterns)
- Prior trend (N-candle momentum)
- RSI zone at entry
- EMA structure
"""

import pandas as pd
import numpy as np
from itertools import product
import time
import sys

# Direct DB connection
import os
import psycopg2
db_url = os.environ.get("DATABASE_URL", "postgresql://deriv:deriv_password@localhost:5432/deriv_trading")
conn = psycopg2.connect(db_url)

print("Loading candle data...")
t0 = time.time()

query = """
    SELECT open_time, open, high, low, close,
           rsi_14, ema_21, ema_50, macd_histogram, atr_14,
           hurst_fast, bollinger_upper, bollinger_lower, bollinger_middle
    FROM candles WHERE symbol='R_100'
    ORDER BY open_time
"""
df = pd.read_sql(query, conn)
conn.close()

for c in ['open','high','low','close','rsi_14','ema_21','ema_50','macd_histogram','atr_14','hurst_fast','bollinger_upper','bollinger_lower','bollinger_middle']:
    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(float)

print(f"Loaded {len(df):,} candles in {time.time()-t0:.1f}s")
print(f"Date range: {df.iloc[0]['open_time']} to {df.iloc[-1]['open_time']}")

# ===== PRE-COMPUTE ALL CANDLE FEATURES =====
print("Computing candle features...")

o = df['open'].values
h = df['high'].values
l = df['low'].values
c = df['close'].values
atr = df['atr_14'].values
rsi = df['rsi_14'].values
ema21 = df['ema_21'].values
ema50 = df['ema_50'].values
macd = df['macd_histogram'].values

body = np.abs(c - o)
candle_range = h - l + 1e-10
upper_wick = h - np.maximum(o, c)
lower_wick = np.minimum(o, c) - l
is_bearish = (c < o).astype(int)
is_bullish = (c > o).astype(int)

# Relative to ATR
safe_atr = np.where(atr > 0, atr, 1.0)
body_atr = body / safe_atr
upper_wick_atr = upper_wick / safe_atr
lower_wick_atr = lower_wick / safe_atr
range_atr = candle_range / safe_atr

# Body position (0=bottom, 1=top)
body_position = (np.minimum(o, c) - l) / candle_range

# Wick ratios
wick_body_ratio_upper = upper_wick / np.maximum(body, 0.01)
wick_body_ratio_lower = lower_wick / np.maximum(body, 0.01)

# EMA structure
ema_bearish = (ema21 < ema50).astype(int)
price_below_ema21 = (c < ema21).astype(int)

# Future price (5 candles later)
future_5 = np.roll(c, -5)
future_5[-5:] = c[-5:]  # Avoid lookahead leak
went_down_5 = (future_5 < c).astype(int)

# Hour (Colombia)
df['hour'] = (df['open_time'] - pd.Timedelta(hours=5)).dt.hour
hours = df['hour'].values

N = len(df)
print(f"Features computed. Testing patterns...")

# ===== PATTERN FUNCTIONS =====
results = []

def test_pattern(name, mask, min_trades=100):
    """Test a boolean mask as a pattern, reporting WR for PUT."""
    valid = mask & (np.arange(N) >= 50) & (np.arange(N) < N - 5)
    total = valid.sum()
    if total < min_trades:
        return
    wins = (valid & went_down_5).sum()
    wr = wins / total * 100
    daily = total / (N / 1440)  # Approximate trades per day
    # Estimated monthly PnL with $100 stakes
    monthly_pnl = (wins * 0.95 - (total - wins) * 1.0) * 100 / (N / 1440) * 30
    results.append((wr, total, daily, monthly_pnl, name))

# ===== SINGLE CANDLE PATTERNS =====
print("  Testing single candle patterns...")

# Bearish candle variants
test_pattern("1C: Bearish", is_bearish.astype(bool))
test_pattern("1C: Bearish + body>0.5ATR", (is_bearish & (body_atr > 0.5)).astype(bool))
test_pattern("1C: Bearish + body>1.0ATR", (is_bearish & (body_atr > 1.0)).astype(bool))
test_pattern("1C: Bearish + body>1.5ATR", (is_bearish & (body_atr > 1.5)).astype(bool))

# Shooting star (long upper wick, body at bottom)
for wr_min in [2, 3, 4, 5]:
    for bp_max in [0.2, 0.3, 0.4]:
        mask = (wick_body_ratio_upper >= wr_min) & (body_position < bp_max) & is_bearish.astype(bool)
        test_pattern(f"1C: ShootingStar wick>={wr_min}x bp<{bp_max}", mask)

# Hammer inverted (bearish)
for wr_min in [2, 3]:
    mask = (wick_body_ratio_lower >= wr_min) & (body_position > 0.6) & is_bearish.astype(bool)
    test_pattern(f"1C: InvHammer lower>={wr_min}x", mask)

# Big body bearish
for ba_min in [0.5, 0.8, 1.0, 1.5]:
    for ba_max in [1.5, 2.0, 3.0, 99]:
        mask = is_bearish.astype(bool) & (body_atr >= ba_min) & (body_atr < ba_max)
        test_pattern(f"1C: Bear body {ba_min}-{ba_max}ATR", mask)

# ===== TWO CANDLE PATTERNS =====
print("  Testing 2-candle patterns...")

for i_start in range(1, N):
    pass  # We'll use vectorized approach

# Bearish Engulfing: C1 bullish, C2 bearish, C2 engulfs C1
c1_bull = is_bullish[:-1]
c2_bear = is_bearish[1:]
c2_engulfs = (o[1:] >= c[:-1]) & (c[1:] <= o[:-1])
engulfing = np.zeros(N, dtype=bool)
engulfing[1:] = c1_bull & c2_bear & c2_engulfs
test_pattern("2C: Bearish Engulfing", engulfing)

# Bearish Engulfing + body size filters
for min_body in [0.3, 0.5, 0.8, 1.0]:
    mask = engulfing & (body_atr >= min_body)
    test_pattern(f"2C: Bear Engulf body>={min_body}ATR", mask)

# Two bears in a row
two_bears = np.zeros(N, dtype=bool)
two_bears[1:] = is_bearish[:-1].astype(bool) & is_bearish[1:].astype(bool)
test_pattern("2C: Two Bears", two_bears)

# Two bears stepping down
two_bears_down = np.zeros(N, dtype=bool)
two_bears_down[1:] = is_bearish[:-1].astype(bool) & is_bearish[1:].astype(bool) & (c[1:] < c[:-1])
test_pattern("2C: Two Bears stepping down", two_bears_down)

# Two bears + body similarity
for tol in [0.3, 0.5]:
    avg_b = (body[:-1] + body[1:]) / 2 + 1e-10
    dev = np.abs(body[:-1] - body[1:]) / avg_b
    similar = np.zeros(N, dtype=bool)
    similar[1:] = two_bears_down[1:] & (dev < tol)
    test_pattern(f"2C: Two Bears equal(dev<{tol})", similar)

# Dark Cloud Cover: C1 bullish, C2 opens above C1 high, closes in lower half of C1
dark_cloud = np.zeros(N, dtype=bool)
dark_cloud[1:] = c1_bull & c2_bear & (o[1:] >= h[:-1]) & (c[1:] < (o[:-1] + c[:-1]) / 2)
test_pattern("2C: Dark Cloud Cover", dark_cloud)

# ===== THREE CANDLE PATTERNS =====
print("  Testing 3-candle patterns...")

# Three Red Crows variants
three_bears = np.zeros(N, dtype=bool)
three_bears[2:] = is_bearish[:-2].astype(bool) & is_bearish[1:-1].astype(bool) & is_bearish[2:].astype(bool)
test_pattern("3C: Three Bears", three_bears)

# Three bears stepping down
three_bears_down = np.zeros(N, dtype=bool)
three_bears_down[2:] = three_bears[2:] & (c[1:-1] < c[:-2]) & (c[2:] < c[1:-1])
test_pattern("3C: Three Bears Down", three_bears_down)

# Three bears + body similarity
for tol in [0.2, 0.3, 0.5]:
    avg3 = (body[:-2] + body[1:-1] + body[2:]) / 3 + 1e-10
    d1 = np.abs(body[:-2] - avg3) / avg3
    d2 = np.abs(body[1:-1] - avg3) / avg3
    d3 = np.abs(body[2:] - avg3) / avg3
    max_d = np.maximum(d1, np.maximum(d2, d3))
    similar3 = np.zeros(N, dtype=bool)
    similar3[2:] = three_bears_down[2:] & (max_d < tol)
    test_pattern(f"3C: Red Crows equal(dev<{tol})", similar3)

# Three bears + no gaps
for gap_mult in [0.15, 0.3]:
    gap1 = np.abs(o[1:-1] - c[:-2])
    gap2 = np.abs(o[2:] - c[1:-1])
    gap_ok = (gap1 < safe_atr[2:] * gap_mult) & (gap2 < safe_atr[2:] * gap_mult)
    no_gap = np.zeros(N, dtype=bool)
    no_gap[2:] = three_bears_down[2:] & gap_ok
    test_pattern(f"3C: Bears Down noGap({gap_mult})", no_gap)

# Three bears + small wicks
for wick_max in [0.5, 1.0]:
    wt1 = (upper_wick[:-2] + lower_wick[:-2]) / np.maximum(body[:-2], 0.01)
    wt2 = (upper_wick[1:-1] + lower_wick[1:-1]) / np.maximum(body[1:-1], 0.01)
    wt3 = (upper_wick[2:] + lower_wick[2:]) / np.maximum(body[2:], 0.01)
    small_w = (wt1 < wick_max) & (wt2 < wick_max) & (wt3 < wick_max)
    sw = np.zeros(N, dtype=bool)
    sw[2:] = three_bears_down[2:] & small_w
    test_pattern(f"3C: Bears Down smallWick(<{wick_max})", sw)

# Evening Star: C1 bullish big, C2 small body (star), C3 bearish big
evening_star = np.zeros(N, dtype=bool)
evening_star[2:] = (
    is_bullish[:-2].astype(bool) &  # C1 bullish
    (body_atr[1:-1] < 0.3) &  # C2 small body (star)
    is_bearish[2:].astype(bool) &  # C3 bearish
    (body_atr[2:] > 0.5) &  # C3 meaningful body
    (c[2:] < (o[:-2] + c[:-2]) / 2)  # C3 closes in lower half of C1
)
test_pattern("3C: Evening Star", evening_star)

# ===== PATTERN + INDICATOR COMBOS =====
print("  Testing pattern + indicator combinations...")

# Best base patterns with RSI filters
base_patterns = {
    "3C: Three Bears Down": three_bears_down,
    "2C: Bearish Engulfing": engulfing,
    "2C: Two Bears Down": two_bears_down,
}

for pname, pmask in base_patterns.items():
    for rsi_lo, rsi_hi in [(25,55),(30,60),(35,65),(40,70),(25,70)]:
        mask = pmask & (rsi >= rsi_lo) & (rsi < rsi_hi)
        test_pattern(f"{pname} + RSI {rsi_lo}-{rsi_hi}", mask)
    
    # With EMA bearish
    mask = pmask & ema_bearish.astype(bool)
    test_pattern(f"{pname} + EMA bearish", mask)
    
    # With EMA bullish (contrarian)
    mask = pmask & (~ema_bearish.astype(bool))
    test_pattern(f"{pname} + EMA bullish", mask)
    
    # With MACD negative
    mask = pmask & (macd < 0)
    test_pattern(f"{pname} + MACD neg", mask)
    
    # With specific body size ranges
    for bmin, bmax in [(0.3, 1.5), (0.5, 2.0), (0.3, 1.0)]:
        mask = pmask & (body_atr >= bmin) & (body_atr < bmax)
        test_pattern(f"{pname} + body {bmin}-{bmax}ATR", mask)

# ===== MULTI-PATTERN COMBOS WITH HOUR FILTERS =====
print("  Testing hour-filtered patterns...")

good_hours = np.isin(hours, [1, 2, 3, 10, 14, 15, 16, 21])
bad_hours = np.isin(hours, [5, 8, 9, 18, 23])

for pname, pmask in base_patterns.items():
    mask = pmask & good_hours
    test_pattern(f"{pname} + good hours", mask)
    
    mask = pmask & (~bad_hours)
    test_pattern(f"{pname} + !bad hours", mask)

# ===== ADVANCED: Momentum + Pattern =====
print("  Testing momentum context patterns...")

# N-candle momentum before pattern
for lookback in [3, 5, 10]:
    momentum = np.zeros(N)
    momentum[lookback:] = c[lookback:] - c[:-lookback]
    
    # Pattern after uptrend (reversal signal)
    up = momentum > 0
    for pname, pmask in base_patterns.items():
        mask = pmask & up
        test_pattern(f"{pname} + {lookback}bar uptrend", mask, min_trades=50)
    
    # Pattern in downtrend (continuation)
    down = momentum < 0
    for pname, pmask in base_patterns.items():
        mask = pmask & down
        test_pattern(f"{pname} + {lookback}bar downtrend", mask, min_trades=50)

# ===== SORT AND DISPLAY =====
results.sort(key=lambda x: x[0], reverse=True)

print(f"\n{'='*100}")
print(f"BRUTE FORCE RESULTS — {len(results)} patterns tested")
print(f"{'='*100}")
print(f"{'WR':>6s} {'Trades':>7s} {'Daily':>6s} {'$/Month':>9s}  Pattern")
print(f"{'-'*100}")

# Show top 40 patterns
for wr, total, daily, monthly, name in results[:40]:
    flag = '🔥' if wr >= 55 else '  '
    print(f"{flag}{wr:5.1f}% {total:7d} {daily:6.1f} ${monthly:+8.0f}  {name}")

# ===== TOP PROFITABLE =====
print(f"\n{'='*100}")
print(f"TOP 15 BY ESTIMATED MONTHLY PnL (WR > 53%)")
print(f"{'='*100}")
profitable = [r for r in results if r[0] > 53]
profitable.sort(key=lambda x: x[3], reverse=True)
for wr, total, daily, monthly, name in profitable[:15]:
    print(f"  {wr:5.1f}% {total:7d} trades  {daily:6.1f}/day  ${monthly:+9.0f}/mo  {name}")

print(f"\nTotal time: {time.time()-t0:.0f}s")
