"""
SIMULATION: CONFIG #65 (Production) on last 24H
Tests the currently deployed Layer 1 engine against the last 24 hours of data.
"""
import sys
sys.path.insert(0, '/app')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from app.core.database import SessionLocal
from app.models.models import Candle
from app.analysis.layer1_engine import Layer1SignalEngine
from app.analysis.indicators import TechnicalIndicators
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from app.analysis.garch import GARCHModel
from app.analysis.hurst import HurstExponent

# Suppress noisy logging
import logging
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

def format_duration(seconds):
    return f"{seconds//60}m"

def main():
    print("=" * 70)
    print("🚀 SIMULATION: CONFIG #65 (Production Code) - Last 24 Hours")
    print("=" * 70)
    
    # 1. Load Data
    db = SessionLocal()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=25) 
    candles = db.query(Candle).filter(
        Candle.open_time >= cutoff
    ).order_by(Candle.open_time.asc()).all()
    db.close()
    
    data = [{
        'open_time': c.open_time,
        'open': float(c.open), 'high': float(c.high),
        'low': float(c.low), 'close': float(c.close),
        'volume': 0,
    } for c in candles]
    df_all = pd.DataFrame(data)
    
    print(f"📊 Loaded {len(df_all)} candles")
    print(f"   Range: {df_all.iloc[0]['open_time']} → {df_all.iloc[-1]['open_time']}")
    
    # 2. Setup Engine
    engine = Layer1SignalEngine()
    
    # 3. Helpers for models
    ou_model = OrnsteinUhlenbeckModel()
    garch_model = GARCHModel()
    
    # --- PRE-COMPUTE PHASE ---
    print("\n⚡ Pre-computing models for all bars...")
    sim_start_idx = 250 
    precomputed = {}
    
    for i in range(sim_start_idx, len(df_all)):
        window = df_all.iloc[max(0, i-250):i+1].copy()
        
        try:
            # Indicators
            window_ind = TechnicalIndicators.calculate_all(window)
            indicators = TechnicalIndicators.get_latest_values(window_ind)
            
            # Hurst
            prices = window['close'].astype(float)
            hurst_val = HurstExponent.calculate(prices)
            if hurst_val < 0.45:
                h_regime = 'MEAN_REVERSION'
                h_rec = True
            elif hurst_val > 0.55:
                h_regime = 'TRENDING'
                h_rec = False
            else:
                h_regime = 'RANDOM'
                h_rec = False
            hurst_signal = {'hurst': hurst_val, 'regime': h_regime, 'trade_recommended': h_rec}
            
            # O-U
            prices_series = window['close'].astype(float)
            ou_model.fit(prices_series)
            ou_signal = ou_model.get_signal(float(prices_series.iloc[-1]))
            
            # GARCH
            prices_pd = window['close'].astype(float)
            returns = np.log(prices_pd / prices_pd.shift(1)).dropna()
            current_vol = returns.std()
            garch_model.fit(returns)
            garch_signal = garch_model.get_signal(current_vol)
            
            precomputed[i] = {
                'indicators': indicators,
                'hurst': hurst_signal,
                'ou': ou_signal,
                'garch': garch_signal
            }
            
            if (i - sim_start_idx) % 100 == 0:
                print(f"   Pre-computed bar {i}/{len(df_all)}")
                
        except Exception as e:
            if i % 100 == 0:
                print(f"❌ Error at bar {i}: {e}")
            continue
            
    print(f"   ✅ Pre-computed {len(precomputed)} bars")

    # 4. Simulation Loop (Fast)
    STAKE = 10.0
    PAYOUT = 0.88
    COOLDOWN = 5
    trades = []
    last_trade_idx = -COOLDOWN
    
    print("\n🏃 Running strategy logic...")
    print("-" * 70)
    
    for i in range(sim_start_idx, len(df_all)):
        # Cooldown check
        if i - last_trade_idx < COOLDOWN:
            continue
            
        if i not in precomputed:
            continue
            
        pc = precomputed[i]
        current_price = float(df_all.iloc[i]['close'])
        
        # --- RUN ENGINE ---
        result = engine._aggregate_signals(
            pc['ou'], pc['garch'], pc['hurst'], pc['indicators'], current_price
        )
        
        sig = result.get('signal', 'HOLD')  # Changed from 'decision'
        conf = result.get('confidence', 0.0)
        
        if sig in ['CALL', 'PUT'] and conf >= 0.60:
            # Execute Trade
            dur = result.get('duration', 300)
            future_bars = min(dur // 60, len(df_all) - i - 1)
            
            if future_bars < 1:
                continue
                
            future_idx = min(i + future_bars, len(df_all) - 1)
            future_price = float(df_all.iloc[future_idx]['close'])
            
            if sig == 'CALL':
                won = future_price > current_price
            else: # PUT
                won = future_price < current_price
            
            pnl = STAKE * PAYOUT if won else -STAKE
            
            trades.append({
                'time': str(df_all.iloc[i]['open_time']),
                'type': sig,
                'price': current_price,
                'conf': conf,
                'result': 'WIN' if won else 'LOSS',
                'pnl': pnl
            })
            
            outcome_icon = "✅" if won else "❌"
            print(f"{str(df_all.iloc[i]['open_time'])[11:16]} | {sig:4s} | {conf:.0%} | {outcome_icon} ${pnl:+.2f}")
            
            last_trade_idx = i

    # 5. Summary
    print("-" * 70)
    total_trades = len(trades)
    wins = sum(1 for t in trades if t['result'] == 'WIN')
    losses = total_trades - wins
    win_rate = (wins/total_trades*100) if total_trades > 0 else 0
    total_pnl = sum(t['pnl'] for t in trades)
    
    print(f"📊 SUMMARY (Last 24 Hours)")
    print(f"   Trades: {total_trades}")
    print(f"   Wins:   {wins}")
    print(f"   Losses: {losses}")
    print(f"   Win Rate: {win_rate:.1f}%")
    print(f"   Total P&L: ${total_pnl:+.2f}")
    
    if total_trades > 0:
        print(f"   Avg P&L/Trade: ${total_pnl/total_trades:+.2f}")

if __name__ == '__main__':
    main()
