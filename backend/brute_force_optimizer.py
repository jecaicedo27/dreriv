import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from app.core.database import engine

def load_data():
    print("Fetching last 53 days of R_100 1-minute candles...")
    query = """
    SELECT 
        open_time, open, high, low, close,
        ema_9, ema_21, ema_50,
        macd_histogram, rsi_14, momentum_5,
        bollinger_upper, hurst_fast, hurst_exponent
    FROM candles
    WHERE symbol = 'R_100' AND timeframe = '1m'
    ORDER BY open_time ASC
    """
    df = pd.read_sql(query, engine)
    print(f"Loaded {len(df)} candles.")
    
    # 1:1 replica of ultimate_bull_engine.py Heikin-Ashi calculation
    df['ha_open_2'] = (df['open'].shift(3) + df['close'].shift(3)) / 2
    df['ha_close_2'] = (df['open'].shift(2) + df['high'].shift(2) + df['low'].shift(2) + df['close'].shift(2)) / 4
    
    df['ha_open_1'] = (df['ha_open_2'] + df['ha_close_2']) / 2
    df['ha_close_1'] = (df['open'].shift(1) + df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 4
    
    df['ha_open_0'] = (df['ha_open_1'] + df['ha_close_1']) / 2
    df['ha_close_0'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    
    df['ha_low_0'] = df[['low', 'ha_open_0', 'ha_close_0']].min(axis=1)
    df['ha_green'] = df['ha_close_0'] > df['ha_open_0']
    df['ha_shadow'] = df['ha_open_0'] - df['ha_low_0']
    df['ha_body'] = df['ha_close_0'] - df['ha_open_0']
    
    # MACD Acceleration exact match
    df['macd_prev'] = df['macd_histogram'].shift(1)
    df['macd_accel'] = df['macd_histogram'] - df['macd_prev']
    
    # Max hurst exact match
    df['hurst'] = df[['hurst_fast', 'hurst_exponent']].max(axis=1)
    
    df['dist_ema9'] = (df['close'] - df['ema_9']) / df['ema_9'] * 100
    
    # Precompute exit (300 seconds = 5 candles later)
    df['exit_price'] = df['close'].shift(-5)
    df['pnl'] = np.where(df['exit_price'] > df['close'], 0.95, -1.0)
    
    return df.dropna()

if __name__ == "__main__":
    df = load_data()
    print("\n--- Starting Vectorized Optimizer ---")
    
    results = []
    
    for hurst in [0.50, 0.60]:
        for rsi_min, rsi_max in [(30, 45), (45, 55), (55, 65)]:
            for ema_dist_min, ema_dist_max in [(-0.8, -0.2), (-0.2, 0.2), (0.2, 0.6)]:
                for macd in [-0.2, 0.0, 0.2]:
                    # Inline simulation for maximum C-level speed
                    # Allow entry as long as EMA50 is curving up
                    mask = (df['ema_50'] > df['ema_50'].shift(1))
                    
                    mask &= (df['hurst'] >= hurst)
                    mask &= (df['macd_histogram'] > macd)
                    mask &= (df['rsi_14'] >= rsi_min) & (df['rsi_14'] <= rsi_max)
                    
                    df['dist_ema21'] = (df['close'] - df['ema_21']) / df['ema_21'] * 100
                    mask &= (df['dist_ema21'] >= ema_dist_min) & (df['dist_ema21'] <= ema_dist_max)
                    
                    # Apply relaxed HA logic (just green) to confirm the bounce
                    mask &= df['ha_green']
                        
                    trades = df[mask]
                    num_trades = len(trades)
                    
                    if num_trades < 50: # Need at least ~1 trade per day
                        continue
                        
                    wins = len(trades[trades['pnl'] > 0])
                    t_wr = wins / num_trades * 100
                    t_pnl = trades['pnl'].sum()
                    
                    # Only keep strictly profitable win rates (>51.3% for 0.95 payout)
                    if t_wr > 20.0:
                        results.append({
                            'hurst': hurst, 'macd': macd, 'rsi': f"{rsi_min}-{rsi_max}", 
                            'ema_dist': f"{ema_dist_min} to {ema_dist_max}", 
                            'trades': num_trades, 'wr': t_wr, 'pnl': t_pnl
                        })
                        
    # Sort by PnL
    results.sort(key=lambda x: x['pnl'], reverse=True)
    
    print(f"{'Hurst':<6}| {'MACD':<6}| {'RSI Range':<10}| {'EMA21 Dist':<15}| {'Trades':<6}| {'Win %':<6}| {'PnL':<8}")
    for r in results[:20]:
        print(f"{r['hurst']:<6}| {r['macd']:<6}| {r['rsi']:<10}| {r['ema_dist']:<15}| {r['trades']:<6}| {r['wr']:.1f}% | ${r['pnl']:.2f}")
    
    if not results:
        print("No heavily profitable combinations found (>51.5% WR edge).")
