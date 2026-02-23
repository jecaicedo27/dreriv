"""Fast parameter sweep for dualmode_v4 strategy."""
import pandas as pd
import numpy as np
from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

dates = ['2026-02-07','2026-02-08','2026-02-09','2026-02-10','2026-02-11','2026-02-12',
         '2026-02-13','2026-02-14','2026-02-15','2026-02-16','2026-02-17','2026-02-18']
num_days = len(dates)

# Load all data once
all_data = {}
for date in dates:
    rows = db.execute(text('''
        SELECT open_time, open, high, low, close, 
               rsi_14::float, ema_9::float, ema_21::float, ema_50::float,
               momentum_5::float
        FROM candles WHERE symbol = 'R_100'
        AND DATE(open_time AT TIME ZONE 'America/Bogota') = :d
        ORDER BY open_time
    '''), {'d': date}).fetchall()
    if rows:
        df = pd.DataFrame(rows, columns=['time','open','high','low','close','rsi','ema9','ema21','ema50','mom5'])
        for c in ['open','high','low','close','rsi','ema9','ema21','ema50','mom5']:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(float)
        all_data[date] = df

CALL_HOURS = {3, 4, 6, 8, 9, 10, 11}
PUT_HOURS = {13, 14, 15, 16, 18, 19, 20, 21, 22}

def simulate(data, min_ema_dist_call, min_ema_dist_put, rsi_call_max, rsi_put_min, 
             cooldown, duration, use_ema_filter=True):
    """Fast simulation."""
    balance = 10000.0
    total_trades = 0
    total_wins = 0
    total_pnl = 0
    peak = 10000.0
    max_dd = 0
    daily_pnls = []
    
    for date, df in data.items():
        day_start_bal = balance
        cd_until = 0
        for i in range(200, len(df) - duration):
            if i < cd_until:
                continue

            row = df.iloc[i]
            close = row['close']
            ema21 = row['ema21']
            rsi = row['rsi']
            
            if ema21 == 0 or rsi == 0:
                continue
            
            t = row['time']
            col_hour = (t.hour - 5) % 24 if hasattr(t, 'hour') else -1
            
            if col_hour in CALL_HOURS:
                mode = 'CALL'
            elif col_hour in PUT_HOURS:
                mode = 'PUT'
            else:
                continue
            
            ema21_dist = (close - ema21) / ema21 * 100
            
            if use_ema_filter:
                if mode == 'CALL':
                    if rsi > rsi_call_max:
                        continue
                    if ema21_dist > min_ema_dist_call:
                        continue
                else:
                    if rsi < rsi_put_min:
                        continue
                    if ema21_dist < min_ema_dist_put:
                        continue
            else:
                # Only RSI filter
                if mode == 'CALL' and rsi > rsi_call_max:
                    continue
                if mode == 'PUT' and rsi < rsi_put_min:
                    continue
            
            entry = close
            exit_price = df.iloc[i + duration]['close']
            won = (exit_price > entry) if mode == 'CALL' else (exit_price < entry)
            
            stake = max(0.35, balance * 0.014)
            pnl = stake * 0.95 if won else -stake
            balance += pnl
            total_pnl += pnl
            total_trades += 1
            if won:
                total_wins += 1
            
            peak = max(peak, balance)
            dd = (peak - balance) / peak * 100
            max_dd = max(max_dd, dd)
            
            cd_until = i + duration + cooldown
        
        daily_pnls.append(balance - day_start_bal)
    
    wr = total_wins / total_trades * 100 if total_trades else 0
    avg_pnl = total_pnl / num_days
    worst_day = min(daily_pnls) if daily_pnls else 0
    profitable_days = sum(1 for p in daily_pnls if p > 0)
    
    return {
        'trades': total_trades, 'wr': wr, 'pnl': total_pnl, 
        'dd': max_dd, 'avg_pnl': avg_pnl, 'balance': balance,
        'worst_day': worst_day, 'profitable_days': profitable_days
    }

print('===== FAST PARAMETER SWEEP =====')
print(f'Testing across {num_days} days of data\n')

results = []

# Strategy 1: EMA filter ON - vary parameters
for cd in [0, 1, 2]:
    for dur in [3, 5, 7]:
        for ema_c in [-0.3, -0.1, 0.0, 0.1, 0.2, 0.5]:
            for ema_p in [-0.5, -0.2, -0.1, 0.0, 0.1]:
                for rsi_c in [55, 60, 70, 80]:
                    for rsi_p in [20, 30, 40]:
                        r = simulate(all_data, ema_c, ema_p, rsi_c, rsi_p, cd, dur, True)
                        name = f"EMc{ema_c:+.1f}_EMp{ema_p:+.1f}_Rc{rsi_c}_Rp{rsi_p}_cd{cd}_d{dur}"
                        results.append((r['avg_pnl'], name, r))

# Strategy 2: NO EMA filter - only hour + RSI
for cd in [0, 1, 2]:
    for dur in [3, 5, 7]:
        for rsi_c in [55, 60, 70, 80, 100]:
            for rsi_p in [0, 20, 30, 40]:
                r = simulate(all_data, 0, 0, rsi_c, rsi_p, cd, dur, False)
                name = f"NoEMA_Rc{rsi_c}_Rp{rsi_p}_cd{cd}_d{dur}"
                results.append((r['avg_pnl'], name, r))

results.sort(key=lambda x: -x[0])

print(f'Total configs tested: {len(results)}')
print(f'\n{"#":>3s} {"Config":>55s} {"Tr":>5s} {"T/d":>4s} {"WR%":>5s} {"PnL":>9s} {"$/d":>7s} {"DD%":>5s} {"W.Day":>8s} {"P.Ds":>4s}')

for i, (avg_pnl, name, r) in enumerate(results[:30]):
    flag = '🏆' if avg_pnl >= 2000 else ('🔥' if avg_pnl >= 1000 else ('✅' if avg_pnl >= 500 else ''))
    td = r['trades'] / num_days
    print(f'{i+1:3d} {flag:2s}{name:>53s} {r["trades"]:5d} {td:4.0f} {r["wr"]:5.1f} ${r["pnl"]:>+8.0f} ${avg_pnl:>+6.0f}/d {r["dd"]:5.1f} ${r["worst_day"]:>+7.0f} {r["profitable_days"]:3d}/{num_days}')

# Show the winning day breakdown for top 3
print('\n===== TOP 3 DAY-BY-DAY ANALYSIS =====')
for avg_pnl, name, r in results[:3]:
    print(f'\n--- {name} (avg ${avg_pnl:+.0f}/d, WR={r["wr"]:.1f}%) ---')

db.close()
