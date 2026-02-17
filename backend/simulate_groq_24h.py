"""
SIMULATION: CONFIG #65 + GROQ FILTER (Last 24 Hours)
Tests the production Layer 1 engine AND Groq validation against the last 24 hours of data.
"""
import sys
import time
import asyncio
import json
from app.prompts.trading_system_prompt import TRADING_SYSTEM_PROMPT
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
from app.services.groq_client import GroqTradingEngine

# Suppress noisy logging
import logging
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

def format_duration(seconds):
    return f"{seconds//60}m"

def main():
    print("=" * 70)
    print("🚀 SIMULATION: CONFIG #65 + GROQ (Phase 3) - Last 24 Hours")
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
    
    # 2. Setup Engines
    engine = Layer1SignalEngine()
    groq = GroqTradingEngine()
    
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
            
            if (i - sim_start_idx) % 200 == 0:
                print(f"   Pre-computed bar {i}/{len(df_all)}")
                
        except Exception as e:
            continue
            
    print(f"   ✅ Pre-computed {len(precomputed)} bars")

    # 4. Simulation Loop (L1 + Groq)
    STAKE = 10.0
    PAYOUT = 0.88
    COOLDOWN = 5
    
    l1_trades = []
    groq_trades = []
    last_trade_idx = -COOLDOWN
    
    print("\n🏃 Running strategy logic with Groq Validation...")
    print("-" * 70)
    print(f"{'Time':5s} | {'Type':4s} | {'L1%':4s} | {'Groq':4s} | {'Res':3s} | {'PNL'}")
    print("-" * 70)
    
    for i in range(sim_start_idx, len(df_all)):
        # Cooldown check
        if i - last_trade_idx < COOLDOWN:
            continue
            
        if i not in precomputed:
            continue
            
        pc = precomputed[i]
        current_price = float(df_all.iloc[i]['close'])
        
        # --- RUN LAYER 1 ---
        result = engine._aggregate_signals(
            pc['ou'], pc['garch'], pc['hurst'], pc['indicators'], current_price
        )
        
        sig = result.get('signal', 'HOLD')
        conf = result.get('confidence', 0.0)
        
        if sig in ['CALL', 'PUT'] and conf >= 0.60:
            # Valid L1 Signal -> Ask Groq
            
            # Prepare market data for Groq
            market_data = {
                'current_price': current_price,
                'indicators': pc['indicators'],
                'hurst': pc['hurst'],
                'ou': pc['ou'],
                'garch': pc['garch'],
                'l1_signal': {'signal': sig, 'confidence': conf, 'reasoning': result.get('reasoning', '')}
            }
            
            # Format context
            market_context = json.dumps(market_data, indent=2, default=str)
            
            # Call Groq (Async)
            try:
                g_decision = asyncio.run(groq.get_decision(TRADING_SYSTEM_PROMPT, market_context))
                groq_signal = g_decision.get('decision', 'HOLD')
                groq_conf = g_decision.get('confidence', 0.0)
                groq_reason = g_decision.get('reasoning', '')
            except Exception as e:
                print(f"⚠️ Groq Error: {e}")
                groq_signal = 'HOLD'
            
            # Determine Outcome
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
            
            # Record L1 Trade
            l1_trades.append({
                'result': 'WIN' if won else 'LOSS',
                'pnl': pnl
            })
            
            # Record Groq Trade (IF Groq agrees)
            groq_agrees = (groq_signal == sig)
            if groq_agrees:
                groq_trades.append({
                    'result': 'WIN' if won else 'LOSS',
                    'pnl': pnl
                })
            
            outcome_icon = "✅" if won else "❌"
            groq_icon = "👍" if groq_agrees else "⛔"
            
            time_str = str(df_all.iloc[i]['open_time'])[11:16]
            print(f"{time_str} | {sig:4s} | {conf:.0%} | {groq_icon}   | {outcome_icon}   | ${pnl:+.2f}")
            
            last_trade_idx = i
            
            # Rate limit
            time.sleep(1.5)

    # 5. Summary
    print("-" * 70)
    
    def print_stats(name, trade_list):
        total = len(trade_list)
        wins = sum(1 for t in trade_list if t['result'] == 'WIN')
        losses = total - wins
        wr = (wins/total*100) if total > 0 else 0
        pnl = sum(t['pnl'] for t in trade_list)
        print(f"📊 {name}")
        print(f"   Trades: {total}")
        print(f"   Win Rate: {wr:.1f}% ({wins}/{total})")
        print(f"   Total P&L: ${pnl:+.2f}")
    
    print_stats("L1 Only (Baseline)", l1_trades)
    print("")
    print_stats("L1 + Groq (Filtered)", groq_trades)

if __name__ == '__main__':
    main()
