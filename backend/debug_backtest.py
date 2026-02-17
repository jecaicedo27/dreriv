#!/usr/bin/env python3
"""
Debugging backtest - print signal generation details
"""

import sys
sys.path.insert(0, '/app')

import numpy as np
from sqlalchemy import create_engine, text
from app.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)

def calculate_rsi(prices, period=14):
    """Calculate RSI"""
    if len(prices) < period + 1:
        return 50
        
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(prices):
    """Calculate MACD"""
    if len(prices) < 26:
        return 0, 0, 0
        
    def ema(data, period):
        multiplier = 2 / (period + 1)
        ema_val = np.mean(data[:period])
        for price in data[period:]:
            ema_val = (price * multiplier) + (ema_val * (1 - multiplier))
        return ema_val
    
    ema_12 = ema(prices, 12)
    ema_26 = ema(prices, 26)
    macd_line = ema_12 - ema_26
    
    # Simplified signal
    signal_line = ema_26  # Simplified
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram

# Load candles
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT open_time, close
        FROM candles
        ORDER BY open_time ASC
        LIMIT 100
    """))
    candles = result.fetchall()

print(f"\n📊 Testing on {len(candles)} candles\n")

for i in range(50, min(60, len(candles))):
    window = candles[max(0, i-50):i+1]
    prices = [c[1] for c in window]
    
    rsi = calculate_rsi(prices, 14)
    macd, macd_sig, macd_hist = calculate_macd(prices)
    
    print(f"Candle #{i}:")
    print(f"  Price: {prices[-1]:.2f}")
    print(f"  RSI: {rsi:.2f}")
    print(f"  MACD: {macd:.4f}, Signal: {macd_sig:.4f}")
    print(f"  MACD Bearish: {macd < macd_sig}")
    
    # Check signal conditions
    if macd < macd_sig and rsi < 40:
        print(f"  ✅ PUT Signal (RSI {rsi:.1f} < 40)")
    elif macd > macd_sig and rsi < 60:
        print(f"  ✅ CALL Signal (RSI {rsi:.1f} < 60)")  
    elif rsi < 20:
        print(f"  ✅ CALL Signal (Oversold RSI {rsi:.1f})")
    elif rsi > 80:
        print(f"  ✅ PUT Signal (Overbought RSI {rsi:.1f})")
    else:
        print(f"  ❌ No Signal")
    print()
