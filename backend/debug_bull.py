import os
import pandas as pd
from app.core.database import engine
from app.analysis.ultimate_bull_engine import UltimateBullEngine

def run_debug():
    print("Loading recent 5 days for deep debugging...")
    query = """
    SELECT 
        open_time, open, high, low, close,
        ema_9, ema_21, ema_50,
        macd_histogram, rsi_14, momentum_5,
        bollinger_upper, hurst_fast, hurst_exponent
    FROM candles
    WHERE symbol = 'R_100' AND timeframe = '1m'
    ORDER BY open_time DESC
    LIMIT 7200
    """
    df = pd.read_sql(query, engine)
    df = df.sort_values('open_time').reset_index(drop=True)
    
    # Calculate HA offline just to have it
    df['ha_open_2'] = (df['open'].shift(3) + df['close'].shift(3)) / 2
    df['ha_close_2'] = (df['open'].shift(2) + df['high'].shift(2) + df['low'].shift(2) + df['close'].shift(2)) / 4
    df['ha_open_1'] = (df['ha_open_2'] + df['ha_close_2']) / 2
    df['ha_close_1'] = (df['open'].shift(1) + df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 4
    df['ha_open_0'] = (df['ha_open_1'] + df['ha_close_1']) / 2
    df['ha_close_0'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    df['ha_green'] = df['ha_close_0'] > df['ha_open_0']
    
    # Let's see what the optimizer WOULD have found here
    # Hurst = 0.6, MACD > 0.2, RSI 45-55, EMA dist -0.2 to 0.2
    df['dist_ema21'] = (df['close'] - df['ema_21']) / df['ema_21'] * 100
    mask = (df['ema_50'] > df['ema_50'].shift(1))
    mask &= (df[['hurst_fast', 'hurst_exponent']].max(axis=1) >= 0.60)
    mask &= (df['macd_histogram'] > 0.2)
    mask &= (df['rsi_14'] >= 45) & (df['rsi_14'] <= 55)
    mask &= (df['dist_ema21'] >= -0.2) & (df['dist_ema21'] <= 0.2)
    mask &= df['ha_green']
    
    opt_trades = df[mask]
    print(f"Optimizer mathematically finds {len(opt_trades)} trades in these 5 days.")
    
    bull = UltimateBullEngine()
    rejections = {}
    
    # Test those exactly rows in the live engine
    for idx in opt_trades.index:
        # Give it a 250 candle window just like ReplayBot
        window = df.iloc[max(0, idx-249):idx+1].copy()
        res = bull.analyze(window, hurst_min=0.6)
        if res.get('signal') != 'CALL':
            reason = res.get('reasoning', '').split(' | ')[-1]
            rejections[reason] = rejections.get(reason, 0) + 1
            
    print("\n--- Why the live engine rejected these mathematically perfect trades ---")
    for r, count in rejections.items():
        print(f"[{count} times] -> {r}")

if __name__ == "__main__":
    run_debug()
