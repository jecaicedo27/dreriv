"""
Genetic Algorithm Optimizer for BULLISH CALL Engine.
"Fuego contra fuego" — finding the optimal CALL combination to beat Deriv.

Evolves a CALL-only engine with:
- Multiple bullish patterns (single candle, 2-candle, 3-candle)
- EMA/RSI/MACD filters
- Hour selection
- Body/wick characteristics
- Momentum and trend filters
"""

import numpy as np
import pandas as pd
import os, psycopg2, time, random

# ===== LOAD DATA =====
db_url = os.environ.get("DATABASE_URL", "postgresql://deriv:deriv_password@localhost:5432/deriv_trading")
conn = psycopg2.connect(db_url)
print("Loading data...")
t0 = time.time()

df = pd.read_sql("""
    SELECT open_time, open, high, low, close,
           rsi_14, ema_21, ema_50, macd_histogram, atr_14, 
           hurst_fast, momentum_5, bollinger_upper, bollinger_lower, bollinger_middle
    FROM candles WHERE symbol='R_100'
    ORDER BY open_time
""", conn)
conn.close()

for c in ['open','high','low','close','rsi_14','ema_21','ema_50','macd_histogram',
          'atr_14','hurst_fast','momentum_5','bollinger_upper','bollinger_lower','bollinger_middle']:
    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(float)

N = len(df)
print(f"Loaded {N:,} candles in {time.time()-t0:.1f}s")

# Pre-compute arrays
o = df['open'].values
h = df['high'].values
l = df['low'].values
c = df['close'].values
rsi = df['rsi_14'].values
ema21 = df['ema_21'].values
ema50 = df['ema_50'].values
macd = df['macd_histogram'].values
atr = df['atr_14'].values
safe_atr = np.where(atr > 0, atr, 1.0)
mom5 = df['momentum_5'].values
bb_upper = df['bollinger_upper'].values
bb_lower = df['bollinger_lower'].values
bb_mid = df['bollinger_middle'].values

body = c - o  # Positive = bullish
abs_body = np.abs(body)
body_atr = abs_body / safe_atr
is_bull = c > o
is_bear = c < o
upper_wick = h - np.maximum(o, c)
lower_wick = np.minimum(o, c) - l
candle_range = h - l

hours = (df['open_time'] - pd.Timedelta(hours=5)).dt.hour.values

# Future outcome: CALL wins if price goes UP
fut5 = np.roll(c, -5); fut5[-5:] = c[-5:]
up5 = fut5 > c

# Price relative to BB
bb_width = (bb_upper - bb_lower) / (bb_mid + 1e-10)
bb_pos = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)  # 0=lower, 1=upper

# EMA momentum
ema_gap = (ema21 - ema50) / safe_atr  # Positive = bullish
price_vs_ema = (c - ema21) / safe_atr  # Positive = above EMA

# RSI momentum
rsi_prev = np.roll(rsi, 1)
rsi_rising = rsi > rsi_prev

# Consecutive candles
bull2 = is_bull & np.roll(is_bull, 1)
bull3 = bull2 & np.roll(is_bull, 2)

# Momentum shift (was bear, now bull)
mom_shift = is_bull & np.roll(is_bear, 1)
mom_shift2 = is_bull & np.roll(is_bear, 1) & np.roll(is_bear, 2)  # Bear-bear-bull reversal

# Hammer (long lower wick, small body, bullish)
hammer = (lower_wick > abs_body * 2) & (upper_wick < abs_body * 0.5) & is_bull

# Engulfing (bull engulfs prev bear)
engulf_bull = is_bull & np.roll(is_bear, 1) & (c > np.roll(o, 1)) & (o < np.roll(c, 1))

# Pin bar (long lower shadow)
pin_bull = (lower_wick > candle_range * 0.6) & (abs_body < candle_range * 0.3)

TOTAL_DAYS = N / 1440
SPLIT_IDX = int(N * 0.5)  # First half vs second half

# ===== CHROMOSOME =====
# Gene indices:
# 0: pattern_type (0=any_bull, 1=bull2, 2=bull3, 3=mom_shift, 4=mom_shift2, 5=hammer, 6=engulf, 7=pin_bar)
# 1: rsi_lo, 2: rsi_hi
# 3: require_ema_bull (ema21>ema50), 4: require_ema_bear, 5: require_price_above_ema, 6: require_price_below_ema
# 7: require_macd_pos, 8: require_macd_neg
# 9: require_rsi_rising
# 10: min_body_atr, 11: max_body_atr
# 12: max_wick_ratio
# 13: require_bb_lower_half (bb_pos < 0.5), 14: require_bb_upper_half
# 15: require_mom_positive
# 16-39: hour_mask (24 hours)

N_GENES = 40
GENE_NAMES = ['pattern', 'rsi_lo', 'rsi_hi', 'ema_bull', 'ema_bear', 'price_above', 'price_below',
              'macd_pos', 'macd_neg', 'rsi_rising', 'min_body', 'max_body', 'max_wick',
              'bb_lower', 'bb_upper', 'mom_pos'] + [f'h{i}' for i in range(24)]

PATTERNS = {
    0: ("any_bull", is_bull),
    1: ("bull2", bull2),
    2: ("bull3", bull3),
    3: ("mom_shift", mom_shift),
    4: ("reversal", mom_shift2),
    5: ("hammer", hammer),
    6: ("engulf", engulf_bull),
    7: ("pin_bar", pin_bull),
}

def random_chromosome():
    genes = np.zeros(N_GENES)
    genes[0] = random.randint(0, 7)  # pattern
    genes[1] = random.uniform(15, 55)  # rsi_lo
    genes[2] = random.uniform(45, 85)  # rsi_hi
    genes[3] = random.randint(0, 1)  # ema_bull
    genes[4] = random.randint(0, 1)  # ema_bear
    genes[5] = random.randint(0, 1)  # price_above
    genes[6] = random.randint(0, 1)  # price_below
    genes[7] = random.randint(0, 1)  # macd_pos
    genes[8] = random.randint(0, 1)  # macd_neg
    genes[9] = random.randint(0, 1)  # rsi_rising
    genes[10] = random.uniform(0.05, 0.5)  # min_body
    genes[11] = random.uniform(1.0, 4.0)  # max_body
    genes[12] = random.uniform(0.5, 3.0)  # max_wick
    genes[13] = random.randint(0, 1)  # bb_lower
    genes[14] = random.randint(0, 1)  # bb_upper
    genes[15] = random.randint(0, 1)  # mom_pos
    for i in range(24):
        genes[16 + i] = random.randint(0, 1)
    return genes


def evaluate(chrom, start=0, end=None):
    if end is None: end = N
    
    pat_idx = int(round(chrom[0])) % 8
    rsi_lo, rsi_hi = chrom[1], chrom[2]
    if rsi_hi <= rsi_lo: return 0, 0, -999999
    
    _, pat_mask = PATTERNS[pat_idx]
    
    mask = pat_mask.copy()
    mask[:5] = False
    mask[N-5:] = False
    mask[:start] = False
    mask[end:] = False
    
    # RSI
    mask &= (rsi >= rsi_lo) & (rsi <= rsi_hi)
    
    # EMA filters
    if chrom[3] > 0.5: mask &= (ema21 > ema50)  # ema_bull
    if chrom[4] > 0.5: mask &= (ema21 < ema50)  # ema_bear
    if chrom[5] > 0.5: mask &= (c > ema21)  # price_above
    if chrom[6] > 0.5: mask &= (c < ema21)  # price_below
    
    # MACD
    if chrom[7] > 0.5: mask &= (macd > 0)
    if chrom[8] > 0.5: mask &= (macd < 0)
    
    # RSI rising
    if chrom[9] > 0.5: mask &= rsi_rising
    
    # Body size
    mask &= (body_atr >= chrom[10]) & (body_atr <= chrom[11])
    
    # Wick ratio
    wick_rat = (upper_wick + lower_wick) / np.maximum(abs_body, 0.01)
    mask &= (wick_rat <= chrom[12])
    
    # BB position
    if chrom[13] > 0.5: mask &= (bb_pos < 0.5)  # lower half
    if chrom[14] > 0.5: mask &= (bb_pos > 0.5)  # upper half
    
    # Momentum
    if chrom[15] > 0.5: mask &= (mom5 > 0)
    
    # Hours
    active_hours = [i for i in range(24) if chrom[16+i] > 0.5]
    if len(active_hours) < 24 and len(active_hours) > 0:
        mask &= np.isin(hours, active_hours)
    
    total = mask.sum()
    if total < 80:
        return 0, total, -999999
    
    wins = (mask & up5).sum()
    wr = wins / total * 100
    monthly_pnl = (wins * 0.95 - (total - wins) * 1.0) * 130 / TOTAL_DAYS * 30
    
    return wr, total, monthly_pnl


def crossover(p1, p2):
    point = random.randint(1, N_GENES - 1)
    return np.concatenate([p1[:point], p2[point:]])

def mutate(chrom, rate=0.15):
    child = chrom.copy()
    for i in range(N_GENES):
        if random.random() < rate:
            if i == 0: child[i] = random.randint(0, 7)
            elif i in (1,): child[i] = child[i] + random.gauss(0, 5); child[i] = max(10, min(60, child[i]))
            elif i in (2,): child[i] = child[i] + random.gauss(0, 5); child[i] = max(40, min(90, child[i]))
            elif i in (3,4,5,6,7,8,9,13,14,15): child[i] = random.randint(0, 1)
            elif i == 10: child[i] = child[i] + random.gauss(0, 0.1); child[i] = max(0.01, min(0.8, child[i]))
            elif i == 11: child[i] = child[i] + random.gauss(0, 0.3); child[i] = max(0.8, min(5.0, child[i]))
            elif i == 12: child[i] = child[i] + random.gauss(0, 0.3); child[i] = max(0.3, min(4.0, child[i]))
            elif i >= 16: child[i] = random.randint(0, 1)
    return child


# ===== GA =====
POP_SIZE = 150
GENERATIONS = 80
ELITE = 15
TOURN = 5

print(f"\n{'='*80}")
print(f"GENETIC ALGORITHM — BULLISH CALL OPTIMIZER")
print(f"Population={POP_SIZE}, Generations={GENERATIONS}")
print(f"{'='*80}")

pop = [random_chromosome() for _ in range(POP_SIZE)]

best_ever = None
best_fitness = -999999

for gen in range(GENERATIONS):
    fitness = []
    for ch in pop:
        wr, trades, pnl = evaluate(ch)
        # Fitness: PnL BUT penalize instability
        wr1, t1, p1 = evaluate(ch, 0, SPLIT_IDX)
        wr2, t2, p2 = evaluate(ch, SPLIT_IDX, N)
        
        # Stability bonus: reward if both halves are profitable
        stability = 0
        if p1 > 0 and p2 > 0:
            stability = min(p1, p2) * 0.5  # Bonus for both halves positive
        elif p1 < 0 or p2 < 0:
            stability = -abs(p1 - p2) * 0.3  # Penalty for instability
        
        total_fitness = pnl + stability
        fitness.append((wr, trades, pnl, ch, total_fitness, wr1, wr2, p1, p2))
    
    fitness.sort(key=lambda x: x[4], reverse=True)
    
    if fitness[0][4] > best_fitness:
        best_fitness = fitness[0][4]
        best_ever = fitness[0]
    
    if gen % 10 == 0 or gen == GENERATIONS - 1:
        top = fitness[0]
        pat_name = PATTERNS[int(round(top[3][0])) % 8][0]
        print(f"  Gen {gen:3d}: PnL=${top[2]:+.0f} WR={top[0]:.1f}% T={top[1]} "
              f"Pat={pat_name} H1:{top[5]:.1f}%/${top[7]:+.0f} H2:{top[6]:.1f}%/${top[8]:+.0f}")
    
    # Selection
    new_pop = [f[3].copy() for f in fitness[:ELITE]]
    while len(new_pop) < POP_SIZE:
        t1 = max(random.sample(fitness, TOURN), key=lambda x: x[4])
        t2 = max(random.sample(fitness, TOURN), key=lambda x: x[4])
        child = crossover(t1[3], t2[3])
        child = mutate(child)
        new_pop.append(child)
    pop = new_pop

# ===== RESULTS =====
print(f"\n{'='*80}")
print(f"TOP 10 CHROMOSOMES")
print(f"{'='*80}")

# Re-evaluate final pop
fitness = []
for ch in pop:
    wr, trades, pnl = evaluate(ch)
    wr1, t1, p1 = evaluate(ch, 0, SPLIT_IDX)
    wr2, t2, p2 = evaluate(ch, SPLIT_IDX, N)
    stability = min(p1, p2) * 0.5 if (p1 > 0 and p2 > 0) else -abs(p1-p2)*0.3
    fitness.append((wr, trades, pnl, ch, pnl+stability, wr1, wr2, p1, p2))
fitness.sort(key=lambda x: x[4], reverse=True)

for i, (wr, trades, pnl, ch, fit, wr1, wr2, p1, p2) in enumerate(fitness[:10]):
    pat = PATTERNS[int(round(ch[0])) % 8][0]
    bl = [j for j in range(24) if ch[16+j] <= 0.5]
    stable = '✅' if (p1>0 and p2>0 and abs(wr1-wr2)<5) else '⚠️' if (p1>0 and p2>0) else '❌'
    
    filters = []
    if ch[3]>0.5: filters.append('emaBull')
    if ch[4]>0.5: filters.append('emaBear')
    if ch[5]>0.5: filters.append('prAbove')
    if ch[6]>0.5: filters.append('prBelow')
    if ch[7]>0.5: filters.append('macd+')
    if ch[8]>0.5: filters.append('macd-')
    if ch[9]>0.5: filters.append('rsiUp')
    if ch[13]>0.5: filters.append('bbLow')
    if ch[14]>0.5: filters.append('bbHi')
    if ch[15]>0.5: filters.append('mom+')
    
    print(f"  #{i+1} {stable} WR={wr:.1f}% T={trades} PnL=${pnl:+,.0f} Pat={pat:10s} "
          f"RSI={ch[1]:.0f}-{ch[2]:.0f} Filt={'+'.join(filters)} "
          f"H1={wr1:.1f}%/${p1:+.0f} H2={wr2:.1f}%/${p2:+.0f}")

# Print best chromosome details
print(f"\n{'='*80}")
print(f"BEST CHROMOSOME DETAILS")
print(f"{'='*80}")
top = fitness[0]
ch = top[3]
pat_idx = int(round(ch[0])) % 8
print(f"Pattern: {PATTERNS[pat_idx][0]}")
print(f"RSI: {ch[1]:.0f} - {ch[2]:.0f}")
print(f"EMA bull={ch[3]>0.5} | EMA bear={ch[4]>0.5}")
print(f"Price above EMA={ch[5]>0.5} | Price below EMA={ch[6]>0.5}")
print(f"MACD pos={ch[7]>0.5} | MACD neg={ch[8]>0.5}")
print(f"RSI rising={ch[9]>0.5}")
print(f"Body ATR: {ch[10]:.2f} - {ch[11]:.2f}")
print(f"Max wick ratio: {ch[12]:.2f}")
print(f"BB lower half={ch[13]>0.5} | BB upper half={ch[14]>0.5}")
print(f"Momentum positive={ch[15]>0.5}")
blocked = [i for i in range(24) if ch[16+i] <= 0.5]
allowed = [i for i in range(24) if ch[16+i] > 0.5]
print(f"Blocked hours: {blocked}")
print(f"Allowed hours: {allowed}")
print(f"\nWin Rate: {top[0]:.1f}%")
print(f"Trades: {top[1]} ({top[1]/TOTAL_DAYS:.1f}/day)")
print(f"Monthly PnL: ${top[2]:+,.0f}")
print(f"Half 1: WR={top[5]:.1f}% PnL=${top[7]:+,.0f}")
print(f"Half 2: WR={top[6]:.1f}% PnL=${top[8]:+,.0f}")

print(f"\nDone in {time.time()-t0:.0f}s")
