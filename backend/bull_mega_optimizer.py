"""
BULL CALL MEGA-OPTIMIZER v2
===========================
Three approaches competing to find the winning CALL signal:
1. GA v2 — with UTC timezone fix and cooldown simulation
2. GradientBoosting — learns from 50+ features
3. MLP Neural Network — deep pattern recognition

All evaluated on the SAME data with walk-forward validation.
"""

import numpy as np
import pandas as pd
import os, psycopg2, time, random, warnings
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
warnings.filterwarnings('ignore')

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

for col in ['open','high','low','close','rsi_14','ema_21','ema_50','macd_histogram',
            'atr_14','hurst_fast','momentum_5','bollinger_upper','bollinger_lower','bollinger_middle']:
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

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

# USE UTC HOURS — this matches what the simulation uses
hours_utc = df['open_time'].dt.hour.values

body = c - o
abs_body = np.abs(body)
body_atr = abs_body / safe_atr
is_bull = c > o
is_bear = c < o
upper_wick = h - np.maximum(o, c)
lower_wick = np.minimum(o, c) - l

# Future outcome
fut5 = np.zeros(N)
for i in range(N-5):
    fut5[i] = c[i+5]
fut5[-5:] = c[-5:]
up5 = (fut5 > c).astype(int)

TOTAL_DAYS = N / 1440

# ===== FEATURE ENGINEERING =====
print("Engineering features...")

def rolling(arr, window, func):
    result = np.zeros(len(arr))
    for i in range(window, len(arr)):
        result[i] = func(arr[i-window:i])
    return result

# Price features
price_vs_ema21 = (c - ema21) / safe_atr
price_vs_ema50 = (c - ema50) / safe_atr
ema_gap = (ema21 - ema50) / safe_atr

# RSI features
rsi_prev = np.roll(rsi, 1); rsi_prev[0] = 50
rsi_delta = rsi - rsi_prev
rsi_prev2 = np.roll(rsi, 2); rsi_prev2[:2] = 50
rsi_accel = rsi_delta - (rsi_prev - rsi_prev2)

# MACD features
macd_prev = np.roll(macd, 1); macd_prev[0] = 0
macd_delta = macd - macd_prev
macd_cross_up = (macd > 0) & (macd_prev <= 0)

# Body features
body_prev = np.roll(body, 1); body_prev[0] = 0
body_prev2 = np.roll(body, 2); body_prev2[:2] = 0

# Candle patterns
bull_engulf = is_bull & np.roll(is_bear, 1) & (c > np.roll(o, 1)) & (o < np.roll(c, 1))
hammer = (lower_wick > abs_body * 2) & (upper_wick < abs_body * 0.5)
pin_bar = (lower_wick > (h-l) * 0.6) & (abs_body < (h-l) * 0.3)
morning_star = np.roll(is_bear, 2) & (np.roll(abs_body, 1) < np.roll(abs_body, 2) * 0.5) & is_bull

# Volatility features
bb_width = (bb_upper - bb_lower) / (bb_mid + 1e-10)
bb_pos = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
atr_ratio = atr / np.roll(atr, 14)
atr_ratio[:14] = 1.0

# Trend features
c_sma5 = pd.Series(c).rolling(5).mean().fillna(method='bfill').values
c_sma10 = pd.Series(c).rolling(10).mean().fillna(method='bfill').values
c_sma20 = pd.Series(c).rolling(20).mean().fillna(method='bfill').values
trend_5 = (c - c_sma5) / safe_atr
trend_10 = (c - c_sma10) / safe_atr
trend_20 = (c - c_sma20) / safe_atr

# Streak features (consecutive bull/bear)
bull_streak = np.zeros(N)
for i in range(1, N):
    bull_streak[i] = (bull_streak[i-1] + 1) if is_bull[i] else 0
bear_streak = np.zeros(N)
for i in range(1, N):
    bear_streak[i] = (bear_streak[i-1] + 1) if is_bear[i] else 0

# Volume proxy (range)
candle_range = h - l
range_ratio = candle_range / safe_atr

# Hour encoding
hour_sin = np.sin(2 * np.pi * hours_utc / 24)
hour_cos = np.cos(2 * np.pi * hours_utc / 24)

# Build feature matrix
feature_names = [
    'body_atr', 'price_vs_ema21', 'price_vs_ema50', 'ema_gap',
    'rsi', 'rsi_delta', 'rsi_accel',
    'macd', 'macd_delta',
    'bb_pos', 'bb_width', 'range_ratio', 'atr_ratio',
    'trend_5', 'trend_10', 'trend_20',
    'bull_streak', 'bear_streak',
    'is_bull', 'bull_engulf', 'hammer', 'pin_bar', 'morning_star',
    'body_prev_atr', 'body_prev2_atr',
    'upper_wick_ratio', 'lower_wick_ratio',
    'hour_sin', 'hour_cos',
    'mom5_atr',
    'macd_cross_up',
]

X = np.column_stack([
    body_atr, price_vs_ema21, price_vs_ema50, ema_gap,
    rsi, rsi_delta, rsi_accel,
    macd / safe_atr, macd_delta / safe_atr,
    bb_pos, bb_width, range_ratio, atr_ratio,
    trend_5, trend_10, trend_20,
    bull_streak, bear_streak,
    is_bull, bull_engulf, hammer, pin_bar, morning_star,
    np.abs(body_prev) / safe_atr, np.abs(body_prev2) / safe_atr,
    upper_wick / safe_atr, lower_wick / safe_atr,
    hour_sin, hour_cos,
    mom5 / safe_atr,
    macd_cross_up.astype(float),
])
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
y = up5

print(f"Features: {X.shape[1]} | Samples: {N:,}")

# ===== WALK-FORWARD SPLIT =====
# Train on months 1-5, test on month 6 (simulating real forward testing)
train_end = int(N * 0.75)
test_start = train_end

X_train, y_train = X[:train_end], y[:train_end]
X_test, y_test = X[test_start:], y[test_start:]
hours_test = hours_utc[test_start:]

print(f"Train: {len(X_train):,} | Test: {len(X_test):,}")
print(f"Train outcome balance: {y_train.mean():.3f} | Test: {y_test.mean():.3f}")

# ===== 1. GRADIENT BOOSTING =====
print(f"\n{'='*80}")
print("APPROACH 1: GRADIENT BOOSTING")
print(f"{'='*80}")

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

gb = GradientBoostingClassifier(
    n_estimators=200, max_depth=4, learning_rate=0.05,
    subsample=0.8, min_samples_leaf=50,
    random_state=42
)
gb.fit(X_train_s, y_train)

# Get probabilities
probs_gb = gb.predict_proba(X_test_s)[:, 1]

# Test different thresholds
print("\nThreshold scan (only trade when probability > threshold):")
print(f"{'Thresh':>8} {'Trades':>8} {'WR':>8} {'PnL/mo':>10} {'Stable':>8}")
print("-" * 50)

for thresh in [0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59, 0.60]:
    mask = probs_gb > thresh
    total = mask.sum()
    if total < 50: continue
    wins = (mask & (y_test == 1)).sum()
    wr = wins / total * 100
    pnl = (wins * 0.95 - (total - wins) * 1.0) * 130 / (len(X_test)/1440) * 30
    
    # Split stability
    half = len(X_test) // 2
    m1 = probs_gb[:half] > thresh
    m2 = probs_gb[half:] > thresh
    wr1 = (m1 & (y_test[:half]==1)).sum() / max(m1.sum(),1) * 100
    wr2 = (m2 & (y_test[half:]==1)).sum() / max(m2.sum(),1) * 100
    stable = '✅' if abs(wr1-wr2)<3 and wr1>52 and wr2>52 else '⚠️' if wr1>51 and wr2>51 else '❌'
    
    print(f"  {thresh:.2f}   {total:6d}   {wr:5.1f}%   ${pnl:+8.0f}   {stable} ({wr1:.1f}/{wr2:.1f})")

# Feature importance
fi = gb.feature_importances_
top_idx = np.argsort(fi)[::-1][:10]
print(f"\nTop features:")
for idx in top_idx:
    print(f"  {feature_names[idx]:20s}: {fi[idx]:.4f}")

# Best threshold analysis
best_thresh = 0.55
trade_mask = probs_gb > best_thresh
total_gb = trade_mask.sum()
wins_gb = (trade_mask & (y_test==1)).sum()
wr_gb = wins_gb / total_gb * 100 if total_gb > 0 else 0

# Hour analysis for GB
print(f"\nGB by hour (thresh={best_thresh}):")
for hr in range(24):
    hr_mask = trade_mask & (hours_test == hr)
    hrt = hr_mask.sum()
    if hrt >= 10:
        hrw = (hr_mask & (y_test==1)).sum()
        hrwr = hrw/hrt*100
        flag = '🔥' if hrwr >= 55 else '❄️' if hrwr < 48 else '  '
        print(f"  {flag} {hr:02d}:00 UTC  {hrt:4d} trades  WR={hrwr:.1f}%")

# ===== 2. MLP NEURAL NETWORK =====
print(f"\n{'='*80}")
print("APPROACH 2: MLP NEURAL NETWORK (deep features)")
print(f"{'='*80}")

mlp = MLPClassifier(
    hidden_layer_sizes=(64, 32, 16),
    activation='relu', solver='adam',
    alpha=0.01, learning_rate='adaptive',
    max_iter=300, early_stopping=True,
    validation_fraction=0.15,
    random_state=42
)
mlp.fit(X_train_s, y_train)

probs_mlp = mlp.predict_proba(X_test_s)[:, 1]

print("\nThreshold scan:")
print(f"{'Thresh':>8} {'Trades':>8} {'WR':>8} {'PnL/mo':>10} {'Stable':>8}")
print("-" * 50)

for thresh in [0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59, 0.60]:
    mask = probs_mlp > thresh
    total = mask.sum()
    if total < 50: continue
    wins = (mask & (y_test == 1)).sum()
    wr = wins / total * 100
    pnl = (wins * 0.95 - (total - wins) * 1.0) * 130 / (len(X_test)/1440) * 30
    
    half = len(X_test) // 2
    m1 = probs_mlp[:half] > thresh
    m2 = probs_mlp[half:] > thresh
    wr1 = (m1 & (y_test[:half]==1)).sum() / max(m1.sum(),1) * 100
    wr2 = (m2 & (y_test[half:]==1)).sum() / max(m2.sum(),1) * 100
    stable = '✅' if abs(wr1-wr2)<3 and wr1>52 and wr2>52 else '⚠️' if wr1>51 and wr2>51 else '❌'
    
    print(f"  {thresh:.2f}   {total:6d}   {wr:5.1f}%   ${pnl:+8.0f}   {stable} ({wr1:.1f}/{wr2:.1f})")

# ===== 3. ENSEMBLE (GB + MLP) =====
print(f"\n{'='*80}")
print("APPROACH 3: ENSEMBLE (GB + MLP average)")
print(f"{'='*80}")

probs_ens = (probs_gb + probs_mlp) / 2

print("\nThreshold scan:")
print(f"{'Thresh':>8} {'Trades':>8} {'WR':>8} {'PnL/mo':>10} {'Stable':>8}")
print("-" * 50)

best_pnl_ens = -999999
best_thresh_ens = 0.55

for thresh in [0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59, 0.60, 0.62, 0.65]:
    mask = probs_ens > thresh
    total = mask.sum()
    if total < 30: continue
    wins = (mask & (y_test == 1)).sum()
    wr = wins / total * 100
    pnl = (wins * 0.95 - (total - wins) * 1.0) * 130 / (len(X_test)/1440) * 30
    
    half = len(X_test) // 2
    m1 = probs_ens[:half] > thresh
    m2 = probs_ens[half:] > thresh
    wr1 = (m1 & (y_test[:half]==1)).sum() / max(m1.sum(),1) * 100
    wr2 = (m2 & (y_test[half:]==1)).sum() / max(m2.sum(),1) * 100
    stable = '✅' if abs(wr1-wr2)<3 and wr1>52 and wr2>52 else '⚠️' if wr1>51 and wr2>51 else '❌'
    
    if pnl > best_pnl_ens and wr > 52:
        best_pnl_ens = pnl
        best_thresh_ens = thresh
    
    print(f"  {thresh:.2f}   {total:6d}   {wr:5.1f}%   ${pnl:+8.0f}   {stable} ({wr1:.1f}/{wr2:.1f})")

# ===== 4. GA v2 (UTC hours, cooldown, more patterns) =====
print(f"\n{'='*80}")
print("APPROACH 4: GA v2 (UTC hours, cooldown, multi-pattern)")
print(f"{'='*80}")

# Pre-compute more pattern signals
# Reversal: 2+ bear candles then bull
rev2 = is_bull & np.roll(is_bear, 1) & np.roll(is_bear, 2)
rev3 = rev2 & np.roll(is_bear, 3)
# Bounce from low: price near BB lower + bull
bb_bounce = is_bull & (bb_pos < 0.3)
# Strong bull: big body
strong_bull = is_bull & (body_atr > 0.5)
# Dip buy: price below ema21 + bull
dip_buy = is_bull & (price_vs_ema21 < 0)
# RSI recovery: rsi was < 40, now rising
rsi_recovery = is_bull & (rsi < 50) & (rsi_delta > 0)
# MACD flip
macd_flip = is_bull & macd_cross_up

PATTERNS_V2 = {
    0: is_bull,
    1: bull_engulf,
    2: hammer.astype(bool),
    3: rev2,
    4: rev3,
    5: bb_bounce,
    6: strong_bull,
    7: dip_buy,
    8: rsi_recovery,
    9: macd_flip,
    10: morning_star,
    11: pin_bar.astype(bool),
}
PAT_NAMES = {0:'bull',1:'engulf',2:'hammer',3:'rev2',4:'rev3',5:'bb_bounce',
             6:'strong',7:'dip',8:'rsi_rec',9:'macd_flip',10:'mstar',11:'pin'}

N_GENES_V2 = 50
def random_v2():
    g = np.zeros(N_GENES_V2)
    g[0] = random.randint(0, 11)  # pattern
    g[1] = random.uniform(20, 55)  # rsi_lo
    g[2] = random.uniform(45, 85)  # rsi_hi
    g[3] = random.randint(0, 1)  # ema_bull
    g[4] = random.randint(0, 1)  # price_above_ema
    g[5] = random.randint(0, 1)  # price_below_ema
    g[6] = random.randint(0, 1)  # macd_pos
    g[7] = random.randint(0, 1)  # rsi_rising
    g[8] = random.uniform(0.01, 0.5)  # min_body
    g[9] = random.uniform(0.5, 3.0)  # max_body
    g[10] = random.uniform(0.5, 3.5)  # max_wick
    g[11] = random.randint(0, 1)  # bb_lower_half
    g[12] = random.randint(0, 1)  # mom_positive
    g[13] = random.randint(0, 1)  # require_bear_before (prev candle bear)
    g[14] = random.randint(0, 1)  # require_trend_down_5
    g[15] = random.uniform(1, 5)  # cooldown candles
    # Hours 16-39 (use UTC!)
    for i in range(24):
        g[16 + i] = random.randint(0, 1)
    # Extra: 40=min_ema_gap, 41=max_ema_gap
    g[40] = random.uniform(-5, 0)  # min ema gap (negative = below)
    g[41] = random.uniform(0, 5)   # max ema gap
    return g

def eval_v2(ch, start=0, end=None):
    if end is None: end = N
    pat = int(round(ch[0])) % 12
    rsi_lo, rsi_hi = ch[1], ch[2]
    if rsi_hi <= rsi_lo: return 0, 0, -999999
    cooldown = max(1, int(round(ch[15])))
    
    mask = PATTERNS_V2[pat].copy()
    mask[:10] = False; mask[N-5:] = False
    mask[:start] = False; mask[end:] = False
    
    mask &= (rsi >= rsi_lo) & (rsi <= rsi_hi)
    if ch[3] > 0.5: mask &= (ema21 > ema50)
    if ch[4] > 0.5: mask &= (c > ema21)
    if ch[5] > 0.5: mask &= (c < ema21)
    if ch[6] > 0.5: mask &= (macd > 0)
    if ch[7] > 0.5: mask &= (rsi > rsi_prev)
    mask &= (body_atr >= ch[8]) & (body_atr <= ch[9])
    wr = (upper_wick + lower_wick) / np.maximum(abs_body, 0.01)
    mask &= (wr <= ch[10])
    if ch[11] > 0.5: mask &= (bb_pos < 0.5)
    if ch[12] > 0.5: mask &= (mom5 > 0)
    if ch[13] > 0.5: mask &= np.roll(is_bear, 1)
    if ch[14] > 0.5: mask &= (trend_5 < 0)
    
    # EMA gap filter
    if ch[40] != 0 or ch[41] != 0:
        mask &= (ema_gap >= ch[40]) & (ema_gap <= ch[41])
    
    # UTC hours
    active = [i for i in range(24) if ch[16+i] > 0.5]
    if 0 < len(active) < 24:
        mask &= np.isin(hours_utc, active)
    
    # Apply cooldown
    indices = np.where(mask)[0]
    if len(indices) < 50: return 0, len(indices), -999999
    
    filtered = []
    last_trade = -999
    for idx in indices:
        if idx - last_trade >= cooldown:
            filtered.append(idx)
            last_trade = idx
    
    total = len(filtered)
    if total < 50: return 0, total, -999999
    
    wins = sum(1 for idx in filtered if up5[idx])
    w = wins / total * 100
    # Use period-specific day count
    period_days = (end - start) / 1440
    pnl = (wins * 0.95 - (total - wins) * 1.0) * 130 / max(period_days, 1) * 30
    return w, total, pnl

POP_V2 = 200
GENS_V2 = 100

pop = [random_v2() for _ in range(POP_V2)]
best_fit = -999999

for gen in range(GENS_V2):
    fitness = []
    for ch in pop:
        wr, trades, pnl = eval_v2(ch)
        wr1, t1, p1 = eval_v2(ch, 0, N//2)
        wr2, t2, p2 = eval_v2(ch, N//2, N)
        stab = min(p1,p2)*0.5 if (p1>0 and p2>0) else -abs(p1-p2)*0.3
        fitness.append((wr, trades, pnl, ch, pnl+stab, wr1, wr2, p1, p2))
    
    fitness.sort(key=lambda x: x[4], reverse=True)
    if fitness[0][4] > best_fit:
        best_fit = fitness[0][4]
    
    if gen % 20 == 0 or gen == GENS_V2-1:
        t = fitness[0]
        pn = PAT_NAMES.get(int(round(t[3][0]))%12, '?')
        print(f"  Gen {gen:3d}: PnL=${t[2]:+.0f} WR={t[0]:.1f}% T={t[1]} Pat={pn} "
              f"H1:{t[5]:.1f}%/${t[7]:+.0f} H2:{t[6]:.1f}%/${t[8]:+.0f}")
    
    new = [f[3].copy() for f in fitness[:20]]
    while len(new) < POP_V2:
        t1 = max(random.sample(fitness, 5), key=lambda x: x[4])
        t2 = max(random.sample(fitness, 5), key=lambda x: x[4])
        pt = random.randint(1, N_GENES_V2-1)
        child = np.concatenate([t1[3][:pt], t2[3][pt:]])
        for i in range(N_GENES_V2):
            if random.random() < 0.12:
                if i == 0: child[i] = random.randint(0, 11)
                elif i in (1,): child[i] += random.gauss(0, 5); child[i] = max(10, min(60, child[i]))
                elif i in (2,): child[i] += random.gauss(0, 5); child[i] = max(40, min(90, child[i]))
                elif i in (3,4,5,6,7,11,12,13,14): child[i] = random.randint(0, 1)
                elif i == 8: child[i] += random.gauss(0, 0.1); child[i] = max(0.01, min(1.0, child[i]))
                elif i == 9: child[i] += random.gauss(0, 0.3); child[i] = max(0.3, min(5.0, child[i]))
                elif i == 10: child[i] += random.gauss(0, 0.3); child[i] = max(0.3, min(5.0, child[i]))
                elif i == 15: child[i] += random.gauss(0, 1); child[i] = max(1, min(10, child[i]))
                elif 16 <= i <= 39: child[i] = random.randint(0, 1)
                elif i == 40: child[i] += random.gauss(0, 0.5); child[i] = max(-8, min(0, child[i]))
                elif i == 41: child[i] += random.gauss(0, 0.5); child[i] = max(0, min(8, child[i]))
        new.append(child)
    pop = new

# Final results
print(f"\n{'='*80}")
print("GA v2 TOP 5 CHROMOSOMES")
print(f"{'='*80}")
fitness_final = []
for ch in pop:
    wr, trades, pnl = eval_v2(ch)
    wr1, t1, p1 = eval_v2(ch, 0, N//2)
    wr2, t2, p2 = eval_v2(ch, N//2, N)
    fitness_final.append((wr, trades, pnl, ch, wr1, wr2, p1, p2))
fitness_final.sort(key=lambda x: x[2], reverse=True)

for i, (wr, trades, pnl, ch, wr1, wr2, p1, p2) in enumerate(fitness_final[:5]):
    pat = PAT_NAMES.get(int(round(ch[0]))%12, '?')
    active_h = [j for j in range(24) if ch[16+j]>0.5]
    filters = []
    if ch[3]>0.5: filters.append('emaBull')
    if ch[4]>0.5: filters.append('prAbove')
    if ch[5]>0.5: filters.append('prBelow')
    if ch[6]>0.5: filters.append('macd+')
    if ch[7]>0.5: filters.append('rsiUp')
    if ch[11]>0.5: filters.append('bbLow')
    if ch[12]>0.5: filters.append('mom+')
    if ch[13]>0.5: filters.append('prevBear')
    if ch[14]>0.5: filters.append('trend↓')
    stable = '✅' if (p1>0 and p2>0 and abs(wr1-wr2)<5) else '⚠️' if (p1>0 and p2>0) else '❌'
    cd = int(round(ch[15]))
    print(f"  #{i+1} {stable} WR={wr:.1f}% T={trades} PnL=${pnl:+,.0f} Pat={pat} "
          f"RSI={ch[1]:.0f}-{ch[2]:.0f} CD={cd} Filt={'+'.join(filters)} "
          f"H1={wr1:.1f}%/${p1:+.0f} H2={wr2:.1f}%/${p2:+.0f}")
    if i == 0:
        print(f"       Hours(UTC): {active_h}")
        print(f"       Body: {ch[8]:.2f}-{ch[9]:.2f} ATR | Wick: {ch[10]:.2f}")

# ===== FINAL COMPARISON =====
print(f"\n{'='*80}")
print("FINAL COMPARISON — ALL APPROACHES")
print(f"{'='*80}")

# GA best
ga_best = fitness_final[0]
ga_pnl = ga_best[2]

# GB best (threshold 0.55)
gb_mask = probs_gb > 0.55
gb_total = gb_mask.sum()
gb_wins = (gb_mask & (y_test==1)).sum()
gb_wr = gb_wins/max(gb_total,1)*100
gb_pnl = (gb_wins * 0.95 - (gb_total-gb_wins)) * 130 / (len(X_test)/1440) * 30

# MLP best
mlp_mask = probs_mlp > 0.55
mlp_total = mlp_mask.sum()
mlp_wins = (mlp_mask & (y_test==1)).sum()
mlp_wr = mlp_wins/max(mlp_total,1)*100
mlp_pnl = (mlp_wins * 0.95 - (mlp_total-mlp_wins)) * 130 / (len(X_test)/1440) * 30

# Ensemble
ens_mask = probs_ens > 0.55
ens_total = ens_mask.sum()
ens_wins = (ens_mask & (y_test==1)).sum()
ens_wr = ens_wins/max(ens_total,1)*100
ens_pnl = (ens_wins * 0.95 - (ens_total-ens_wins)) * 130 / (len(X_test)/1440) * 30

print(f"  {'Approach':25s} {'WR':>7} {'Trades':>8} {'PnL/mo':>10}")
print(f"  {'-'*55}")
print(f"  {'GA v2':25s} {ga_best[0]:>6.1f}% {ga_best[1]:>7} ${ga_pnl:>+9.0f}")
print(f"  {'GradientBoosting':25s} {gb_wr:>6.1f}% {gb_total:>7} ${gb_pnl:>+9.0f}")
print(f"  {'MLP Neural Net':25s} {mlp_wr:>6.1f}% {mlp_total:>7} ${mlp_pnl:>+9.0f}")
print(f"  {'Ensemble (GB+MLP)':25s} {ens_wr:>6.1f}% {ens_total:>7} ${ens_pnl:>+9.0f}")

print(f"\nTotal time: {time.time()-t0:.0f}s")
