"""
Smart Money Concepts (SMC) Calculator

Detects institutional trading patterns:
- Order Blocks (OB): Last opposing candle before a strong move
- Fair Value Gaps (FVG): Price imbalance zones (3-candle gap)
- Break of Structure (BOS): Higher highs/lower lows continuation
- Change of Character (ChoCh): First sign of trend reversal
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple


def calculate_smc(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Calculate all SMC indicators and add columns to DataFrame."""
    df = df.copy()
    
    # Initialize columns
    df['is_order_block'] = False
    df['ob_type'] = None
    df['is_fvg'] = False
    df['fvg_type'] = None
    df['bos'] = False
    df['choch'] = False
    
    highs = df['high'].astype(float).values
    lows = df['low'].astype(float).values
    opens = df['open'].astype(float).values
    closes = df['close'].astype(float).values
    
    n = len(df)
    if n < 10:
        return df
    
    # === 1. Swing Points Detection ===
    # A swing high: high[i] > high[i-1] AND high[i] > high[i+1] (simplified)
    swing_highs = []  # (index, price)
    swing_lows = []   # (index, price)
    
    for i in range(2, n - 2):
        # Swing high: higher than 2 candles on each side
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append((i, highs[i]))
        # Swing low: lower than 2 candles on each side
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append((i, lows[i]))
    
    # === 2. BOS and ChoCh Detection ===
    # Track the last swing high and swing low
    last_sh_idx, last_sh_price = -1, 0
    last_sl_idx, last_sl_price = -1, float('inf')
    trend = 0  # 1 = bullish, -1 = bearish, 0 = undefined
    
    # Merge swing points by index
    all_swings = []
    for idx, price in swing_highs:
        all_swings.append((idx, price, 'high'))
    for idx, price in swing_lows:
        all_swings.append((idx, price, 'low'))
    all_swings.sort(key=lambda x: x[0])
    
    bos_indices = set()
    choch_indices = set()
    
    for idx, price, swing_type in all_swings:
        if swing_type == 'high':
            if last_sh_price > 0 and price > last_sh_price:
                # Higher high
                if trend == 1:
                    # BOS bullish — continuation of uptrend
                    bos_indices.add(idx)
                elif trend == -1:
                    # ChoCh — trend was bearish, now making higher high
                    choch_indices.add(idx)
                trend = 1
            elif last_sh_price > 0 and price < last_sh_price:
                # Lower high — potential weakness
                pass
            last_sh_idx, last_sh_price = idx, price
            
        elif swing_type == 'low':
            if last_sl_price < float('inf') and price < last_sl_price:
                # Lower low
                if trend == -1:
                    # BOS bearish — continuation of downtrend
                    bos_indices.add(idx)
                elif trend == 1:
                    # ChoCh — trend was bullish, now making lower low
                    choch_indices.add(idx)
                trend = -1
            elif last_sl_price < float('inf') and price > last_sl_price:
                # Higher low — potential strength
                pass
            last_sl_idx, last_sl_price = idx, price
    
    for idx in bos_indices:
        if idx < n:
            df.iloc[idx, df.columns.get_loc('bos')] = True
    for idx in choch_indices:
        if idx < n:
            df.iloc[idx, df.columns.get_loc('choch')] = True
    
    # === 3. Fair Value Gap (FVG) Detection ===
    # Bullish FVG: candle[i-2].high < candle[i].low (gap between 3 candles)
    # Bearish FVG: candle[i-2].low > candle[i].high
    for i in range(2, n):
        # Bullish FVG
        if lows[i] > highs[i-2]:
            df.iloc[i, df.columns.get_loc('is_fvg')] = True
            df.iloc[i, df.columns.get_loc('fvg_type')] = 'bullish'
        # Bearish FVG
        elif highs[i] < lows[i-2]:
            df.iloc[i, df.columns.get_loc('is_fvg')] = True
            df.iloc[i, df.columns.get_loc('fvg_type')] = 'bearish'
    
    # === 4. Order Block Detection ===
    # Bullish OB: Last bearish candle before a strong bullish move
    # Bearish OB: Last bullish candle before a strong bearish move
    atr = (df['high'].astype(float) - df['low'].astype(float)).rolling(14).mean().values
    
    for i in range(3, n):
        if np.isnan(atr[i]) or atr[i] <= 0:
            continue
        
        # Check for strong move (> 2x ATR in last 3 candles)
        move_up = closes[i] - closes[i-3]
        move_down = closes[i-3] - closes[i]
        
        if move_up > 2.0 * atr[i]:
            # Strong bullish move — find last bearish candle before it
            for j in range(i-1, max(i-5, 0), -1):
                if closes[j] < opens[j]:  # Bearish candle
                    df.iloc[j, df.columns.get_loc('is_order_block')] = True
                    df.iloc[j, df.columns.get_loc('ob_type')] = 'bullish'
                    break
        
        elif move_down > 2.0 * atr[i]:
            # Strong bearish move — find last bullish candle before it
            for j in range(i-1, max(i-5, 0), -1):
                if closes[j] > opens[j]:  # Bullish candle
                    df.iloc[j, df.columns.get_loc('is_order_block')] = True
                    df.iloc[j, df.columns.get_loc('ob_type')] = 'bearish'
                    break
    
    return df
