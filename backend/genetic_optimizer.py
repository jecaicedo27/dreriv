"""
Genetic Algorithm Optimizer for Red Crows PUT Engine.

Evolves parameters:
- N_CROWS: 3 or 4 consecutive bearish candles
- BODY_TOLERANCE: max deviation between body sizes (0.1-0.8)
- MAX_WICK_RATIO: max total wick vs body (0.3-2.0)
- MAX_GAP: max gap as fraction of ATR (0.05-0.5)
- MIN_BODY_ATR: min body size as ATR fraction (0.1-0.5)
- MAX_BODY_ATR: max body size as ATR fraction (1.0-3.0)
- RSI_LO, RSI_HI: optimal RSI zone
- HOUR_MASK: 24 bits, which hours to trade
- REQUIRE_MACD_NEG: bool
- REQUIRE_EMA_BEAR: bool
- REQUIRE_PRICE_BELOW_EMA: bool
- MIN_CONFIDENCE: confidence threshold

Fitness = monthly PnL with Kelly sizing
"""

import numpy as np
import pandas as pd
import os, psycopg2, time, random, json

# ===== LOAD DATA =====
db_url = os.environ.get("DATABASE_URL", "postgresql://deriv:deriv_password@localhost:5432/deriv_trading")
conn = psycopg2.connect(db_url)
print("Loading data...")
t0 = time.time()

df = pd.read_sql("""
    SELECT open_time, open, high, low, close,
           rsi_14, ema_21, ema_50, macd_histogram, atr_14, hurst_fast
    FROM candles WHERE symbol='R_100'
    ORDER BY open_time
""", conn)
conn.close()

for c in ['open','high','low','close','rsi_14','ema_21','ema_50','macd_histogram','atr_14','hurst_fast']:
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

body = np.abs(c - o)
body_atr = body / safe_atr
is_bear = c < o
upper_wick = h - np.maximum(o, c)
lower_wick = np.minimum(o, c) - l

hours = (df['open_time'] - pd.Timedelta(hours=5)).dt.hour.values

# Future outcome
fut5 = np.roll(c, -5); fut5[-5:] = c[-5:]
down5 = fut5 < c  # PUT wins

TOTAL_DAYS = N / 1440

# ===== CHROMOSOME STRUCTURE =====
# [n_crows(0), body_tol(1), wick_max(2), gap_max(3), min_body(4), max_body(5),
#  rsi_lo(6), rsi_hi(7), require_macd(8), require_ema_bear(9), require_pb_ema(10),
#  h0..h23 (11-34)]

GENE_NAMES = ['n_crows', 'body_tol', 'wick_max', 'gap_max', 'min_body', 'max_body',
              'rsi_lo', 'rsi_hi', 'require_macd', 'require_ema_bear', 'require_pb_ema'] + \
             [f'h{i}' for i in range(24)]

GENE_RANGES = {
    'n_crows': (3, 5),        # 3 or 4 crows
    'body_tol': (0.10, 0.80),
    'wick_max': (0.3, 2.5),
    'gap_max': (0.05, 0.50),
    'min_body': (0.05, 0.50),
    'max_body': (1.0, 3.5),
    'rsi_lo': (15, 50),
    'rsi_hi': (40, 80),
    'require_macd': (0, 1),
    'require_ema_bear': (0, 1),
    'require_pb_ema': (0, 1),
}
for i in range(24):
    GENE_RANGES[f'h{i}'] = (0, 1)  # 0=blocked, 1=allowed

N_GENES = len(GENE_NAMES)


def random_chromosome():
    genes = []
    for name in GENE_NAMES:
        lo, hi = GENE_RANGES[name]
        if name in ('n_crows', 'require_macd', 'require_ema_bear', 'require_pb_ema') or name.startswith('h'):
            genes.append(random.randint(int(lo), int(hi)))
        else:
            genes.append(random.uniform(lo, hi))
    return np.array(genes)


def evaluate(chrom):
    """Evaluate a chromosome — return (wr, trades, monthly_pnl)."""
    nc = int(round(chrom[0]))  # number of crows
    body_tol = chrom[1]
    wick_max = chrom[2]
    gap_max = chrom[3]
    min_body = chrom[4]
    max_body = chrom[5]
    rsi_lo = chrom[6]
    rsi_hi = chrom[7]
    req_macd = chrom[8] > 0.5
    req_ema_bear = chrom[9] > 0.5
    req_pb_ema = chrom[10] > 0.5
    hour_mask = set()
    for i in range(24):
        if chrom[11 + i] > 0.5:
            hour_mask.add(i)

    if rsi_hi <= rsi_lo:
        return 0, 0, -999999

    # Build signal mask vectorized
    # Start with all True for valid range
    valid = np.ones(N, dtype=bool)
    valid[:nc] = False  # Need nc candles lookback
    valid[N-5:] = False  # Need 5 candles future

    # All nc candles must be bearish
    for k in range(nc):
        idx = nc - 1 - k  # 0 = latest, nc-1 = oldest
        valid &= is_bear[np.arange(N) - idx] if (nc-1-k) == 0 else np.roll(is_bear, idx)

    # Actually let me do it properly with shifted arrays
    valid = (np.arange(N) >= nc) & (np.arange(N) < N - 5)

    # Check all nc candles are bearish and stepping down
    for k in range(nc):
        shift = nc - 1 - k  # shift=0 is current, shift=nc-1 is oldest
        valid &= np.roll(is_bear, -0)[np.arange(N) - shift] if shift == 0 else True

    # Simpler vectorized approach
    mask = np.ones(N, dtype=bool)
    mask[:nc] = False
    mask[N-5:] = False

    # All nc candles must be bearish
    for k in range(nc):
        shifted = np.roll(is_bear, k)
        mask &= shifted
    # Fix boundary
    mask[:nc] = False

    # Stepping down: each close lower than previous
    for k in range(1, nc):
        c_curr = np.roll(c, k-1)      # close of candle at position k-1 from end
        c_prev = np.roll(c, k)        # close of candle at position k from end
        mask &= (c_curr < c_prev)
    mask[:nc] = False

    # Body checks
    bodies = [np.roll(body, k) for k in range(nc)]
    bodies_atr = [np.roll(body_atr, k) for k in range(nc)]

    # Min/max body
    for k in range(nc):
        mask &= (bodies_atr[k] >= min_body)
        mask &= (bodies_atr[k] <= max_body)

    # Body similarity
    avg_body_arr = sum(bodies) / nc + 1e-10
    for k in range(nc):
        dev = np.abs(bodies[k] - avg_body_arr) / avg_body_arr
        mask &= (dev <= body_tol)

    # Wick check
    for k in range(nc):
        uw = np.roll(upper_wick, k)
        lw = np.roll(lower_wick, k)
        wb = (uw + lw) / np.maximum(bodies[k], 0.01)
        mask &= (wb <= wick_max)

    # Gap check (between consecutive candles)
    for k in range(1, nc):
        gap = np.abs(np.roll(o, k-1) - np.roll(c, k))  # open of newer vs close of older
        mask &= (gap <= safe_atr * gap_max)

    mask[:nc] = False

    # Hour filter
    if len(hour_mask) < 24:
        hour_ok = np.isin(hours, list(hour_mask))
        mask &= hour_ok

    # RSI filter
    mask &= (rsi >= rsi_lo) & (rsi <= rsi_hi)

    # Indicator filters
    if req_macd:
        mask &= (macd < 0)
    if req_ema_bear:
        mask &= (ema21 < ema50)
    if req_pb_ema:
        mask &= (c < ema21)

    # Count results
    total = mask.sum()
    if total < 50:  # Need meaningful sample
        return 0, total, -999999

    wins = (mask & down5).sum()
    wr = wins / total * 100

    # Fitness = monthly PnL (with payout 0.95, stake $130)
    monthly_pnl = (wins * 0.95 - (total - wins) * 1.0) * 130 / TOTAL_DAYS * 30

    return wr, total, monthly_pnl


def crossover(parent1, parent2):
    """Single-point crossover."""
    point = random.randint(1, N_GENES - 1)
    child = np.concatenate([parent1[:point], parent2[point:]])
    return child


def mutate(chrom, rate=0.15):
    """Mutate genes with given probability."""
    child = chrom.copy()
    for i, name in enumerate(GENE_NAMES):
        if random.random() < rate:
            lo, hi = GENE_RANGES[name]
            if name in ('n_crows', 'require_macd', 'require_ema_bear', 'require_pb_ema') or name.startswith('h'):
                child[i] = random.randint(int(lo), int(hi))
            else:
                # Gaussian perturbation
                child[i] = child[i] + random.gauss(0, (hi - lo) * 0.2)
                child[i] = max(lo, min(hi, child[i]))
    return child


# ===== GENETIC ALGORITHM =====
POP_SIZE = 100
GENERATIONS = 50
ELITE_SIZE = 10
TOURNAMENT_SIZE = 5

print(f"\n{'='*80}")
print(f"GENETIC ALGORITHM — Population={POP_SIZE}, Generations={GENERATIONS}")
print(f"{'='*80}")

# Initialize population
population = [random_chromosome() for _ in range(POP_SIZE)]

# Seed with known good parameters (Three Red Crows v3)
seed = random_chromosome()
seed[0] = 3  # 3 crows
seed[1] = 0.30  # body_tol
seed[2] = 1.0   # wick_max
seed[3] = 0.15  # gap_max
seed[4] = 0.20  # min_body
seed[5] = 2.0   # max_body
seed[6] = 25     # rsi_lo
seed[7] = 55     # rsi_hi
seed[8] = 0      # macd
seed[9] = 0      # ema bear
seed[10] = 1     # price below ema
# Good hours on, bad hours off
good = {0,1,2,3,4,6,10,11,14,15,16,17,19,20,21}
for i in range(24):
    seed[11+i] = 1 if i in good else 0
population[0] = seed

# Also seed a 4-crow variant
seed4 = seed.copy()
seed4[0] = 4
population[1] = seed4

best_ever = None
best_fitness = -999999

for gen in range(GENERATIONS):
    # Evaluate
    fitness = []
    for chrom in population:
        wr, trades, pnl = evaluate(chrom)
        fitness.append((wr, trades, pnl, chrom))

    # Sort by PnL (fitness)
    fitness.sort(key=lambda x: x[2], reverse=True)

    # Track best
    if fitness[0][2] > best_fitness:
        best_fitness = fitness[0][2]
        best_ever = fitness[0]

    if gen % 5 == 0 or gen == GENERATIONS - 1:
        top = fitness[0]
        nc = int(round(top[3][0]))
        print(f"  Gen {gen:3d}: Best PnL=${top[2]:+.0f}  WR={top[0]:.1f}%  Trades={top[1]}  Crows={nc}")

    # Selection: tournament
    new_pop = []

    # Elitism: keep top ELITE_SIZE
    for i in range(ELITE_SIZE):
        new_pop.append(fitness[i][3].copy())

    # Fill rest with crossover + mutation
    while len(new_pop) < POP_SIZE:
        # Tournament selection
        t1 = max(random.sample(fitness, TOURNAMENT_SIZE), key=lambda x: x[2])
        t2 = max(random.sample(fitness, TOURNAMENT_SIZE), key=lambda x: x[2])

        child = crossover(t1[3], t2[3])
        child = mutate(child)
        new_pop.append(child)

    population = new_pop

# ===== RESULTS =====
print(f"\n{'='*80}")
print(f"BEST CHROMOSOME FOUND")
print(f"{'='*80}")

best = best_ever
chrom = best[3]
print(f"Win Rate: {best[0]:.1f}%")
print(f"Total Trades: {best[1]}")
print(f"Monthly PnL: ${best[2]:+,.0f}")
print(f"Daily Trades: {best[1] / TOTAL_DAYS:.1f}")
print()

nc = int(round(chrom[0]))
print(f"N_CROWS = {nc}")
print(f"BODY_TOLERANCE = {chrom[1]:.2f}")
print(f"MAX_WICK_RATIO = {chrom[2]:.2f}")
print(f"MAX_GAP = {chrom[3]:.2f}")
print(f"MIN_BODY_ATR = {chrom[4]:.2f}")
print(f"MAX_BODY_ATR = {chrom[5]:.2f}")
print(f"RSI_LO = {chrom[6]:.0f}")
print(f"RSI_HI = {chrom[7]:.0f}")
print(f"REQUIRE_MACD_NEG = {chrom[8] > 0.5}")
print(f"REQUIRE_EMA_BEAR = {chrom[9] > 0.5}")
print(f"REQUIRE_PRICE_BELOW_EMA = {chrom[10] > 0.5}")

blocked = [i for i in range(24) if chrom[11+i] <= 0.5]
allowed = [i for i in range(24) if chrom[11+i] > 0.5]
print(f"BLOCKED_HOURS = {blocked}")
print(f"ALLOWED_HOURS = {allowed}")

# Show top 5 chromosomes
print(f"\n{'='*80}")
print(f"TOP 5 CHROMOSOMES")
print(f"{'='*80}")
# Re-evaluate all
fitness = []
for chrom in population:
    wr, trades, pnl = evaluate(chrom)
    fitness.append((wr, trades, pnl, chrom))
fitness.sort(key=lambda x: x[2], reverse=True)

for i, (wr, trades, pnl, ch) in enumerate(fitness[:5]):
    nc = int(round(ch[0]))
    bl = [j for j in range(24) if ch[11+j] <= 0.5]
    print(f"  #{i+1}: WR={wr:.1f}% Trades={trades} PnL=${pnl:+,.0f} Crows={nc} "
          f"BodyTol={ch[1]:.2f} Wick={ch[2]:.2f} RSI={ch[6]:.0f}-{ch[7]:.0f} "
          f"MACD={'Y' if ch[8]>0.5 else 'N'} EMA={'Y' if ch[9]>0.5 else 'N'} "
          f"PbEMA={'Y' if ch[10]>0.5 else 'N'} Blocked={bl}")

# ===== SPLIT VALIDATION =====
print(f"\n{'='*80}")
print(f"SPLIT VALIDATION (Jan vs Feb)")
print(f"{'='*80}")

# Approximate split: first 60% = Jan, last 40% = Feb
split_idx = int(N * 0.55)

for label, ch in [("Best#1", fitness[0][3]), ("Best#2", fitness[1][3]), ("Best#3", fitness[2][3])]:
    # January
    jan_mask = np.zeros(N, dtype=bool)
    feb_mask = np.zeros(N, dtype=bool)

    wr_all, trades_all, pnl_all = evaluate(ch)

    # Rough split by index
    nc = int(round(ch[0]))
    body_tol = ch[1]; wick_max = ch[2]; gap_max_v = ch[3]
    min_body_v = ch[4]; max_body_v = ch[5]
    rsi_lo = ch[6]; rsi_hi = ch[7]
    req_macd = ch[8] > 0.5; req_ema_bear = ch[9] > 0.5; req_pb_ema = ch[10] > 0.5
    hour_mask = set(i for i in range(24) if ch[11+i] > 0.5)

    # Build mask same as evaluate
    mask = np.ones(N, dtype=bool)
    mask[:nc] = False; mask[N-5:] = False
    for k in range(nc):
        mask &= np.roll(is_bear, k)
    mask[:nc] = False
    for k in range(1, nc):
        mask &= (np.roll(c, k-1) < np.roll(c, k))
    mask[:nc] = False
    bodies_list = [np.roll(body, k) for k in range(nc)]
    bodies_atr_list = [np.roll(body_atr, k) for k in range(nc)]
    for k in range(nc):
        mask &= (bodies_atr_list[k] >= min_body_v) & (bodies_atr_list[k] <= max_body_v)
    avg_b = sum(bodies_list)/nc + 1e-10
    for k in range(nc):
        mask &= (np.abs(bodies_list[k]-avg_b)/avg_b <= body_tol)
    for k in range(nc):
        uw = np.roll(upper_wick, k); lw = np.roll(lower_wick, k)
        mask &= ((uw+lw)/np.maximum(bodies_list[k],0.01) <= wick_max)
    for k in range(1, nc):
        mask &= (np.abs(np.roll(o,k-1)-np.roll(c,k)) <= safe_atr*gap_max_v)
    mask[:nc] = False
    if len(hour_mask)<24: mask &= np.isin(hours, list(hour_mask))
    mask &= (rsi>=rsi_lo) & (rsi<=rsi_hi)
    if req_macd: mask &= (macd<0)
    if req_ema_bear: mask &= (ema21<ema50)
    if req_pb_ema: mask &= (c<ema21)

    jan_m = mask & (np.arange(N) < split_idx)
    feb_m = mask & (np.arange(N) >= split_idx)

    j_total = jan_m.sum(); j_wins = (jan_m & down5).sum()
    f_total = feb_m.sum(); f_wins = (feb_m & down5).sum()

    j_wr = j_wins/j_total*100 if j_total > 0 else 0
    f_wr = f_wins/f_total*100 if f_total > 0 else 0

    print(f"  {label}: ALL={wr_all:.1f}% ({trades_all}t)  JAN={j_wr:.1f}% ({j_total}t)  FEB={f_wr:.1f}% ({f_total}t)  {'✅ STABLE' if abs(j_wr-f_wr)<5 else '⚠️ UNSTABLE'}")

print(f"\nTotal time: {time.time()-t0:.0f}s")
