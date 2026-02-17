"""
Simulate the NEW EMA Crossover Strategy on last 6 hours of LIVE candle data.
Tests if the model would have made better decisions than the old strategy.
"""
import sys
sys.path.insert(0, '/app')

from datetime import datetime, timedelta, timezone
from app.core.database import SessionLocal
from app.models.models import Candle
from app.analysis.indicators import TechnicalIndicators
from app.analysis.layer1_engine import Layer1SignalEngine
import pandas as pd
import numpy as np

db = SessionLocal()

# Fetch last 6 hours of candles + 50 extra for warmup
cutoff = datetime.now(timezone.utc) - timedelta(hours=6, minutes=30)  # extra 30min warmup
candles = db.query(Candle).filter(
    Candle.open_time >= cutoff
).order_by(Candle.open_time.asc()).all()

print(f"📊 Loaded {len(candles)} candles for simulation")
print(f"   Range: {candles[0].open_time} → {candles[-1].open_time}")
print()

# Convert to DataFrame
data = []
for c in candles:
    data.append({
        'open_time': c.open_time,
        'open': float(c.open),
        'high': float(c.high),
        'low': float(c.low),
        'close': float(c.close),
        'volume': 0,
    })

df_all = pd.DataFrame(data)

# Simulation parameters
STAKE = 10.0  # $10 per trade
PAYOUT_RATIO = 0.88  # 88% payout on win
LOOKBACK = 250  # Candles needed for analysis
MIN_BARS_FOR_SIM = 100  # Start simulating after this many bars

engine = Layer1SignalEngine()

# Results tracking
trades = []
signals_log = []

# Walk-forward simulation
# Use a sliding window of LOOKBACK candles
actual_start = datetime.now(timezone.utc) - timedelta(hours=6)

print(f"🔄 Running walk-forward simulation...")
print(f"   Strategy: NEW EMA Crossover Confirmation (Feb 15)")
print(f"   Stake: ${STAKE} | Payout: {PAYOUT_RATIO*100}%")
print(f"=" * 70)

for i in range(MIN_BARS_FOR_SIM, len(df_all)):
    # Get window of data up to current bar
    start_idx = max(0, i - LOOKBACK)
    window = df_all.iloc[start_idx:i+1].copy()
    
    current_time = df_all.iloc[i]['open_time']
    
    # Skip warmup period
    if current_time.tzinfo is None:
        from datetime import timezone as tz
        current_time = current_time.replace(tzinfo=tz.utc)
    if current_time < actual_start:
        continue
    
    current_price = float(window.iloc[-1]['close'])
    
    # Run Layer 1 analysis
    try:
        signal = engine.analyze(window, 'R_100')
    except Exception as e:
        continue
    
    final_signal = signal.get('final_signal', 'HOLD')
    final_confidence = signal.get('final_confidence', 0)
    reasoning = signal.get('reasoning', '')
    duration = signal.get('duration', 300)
    
    # Log all signals
    signals_log.append({
        'time': current_time,
        'price': current_price,
        'signal': final_signal,
        'confidence': final_confidence,
        'reasoning': reasoning[:120],
    })
    
    # Only process CALL/PUT signals with sufficient confidence
    if final_signal in ['CALL', 'PUT'] and final_confidence >= 0.60:
        # Determine outcome by looking at future price
        # Duration in seconds → bars (1 bar = 60s)
        future_bars = min(duration // 60, len(df_all) - i - 1)
        
        if future_bars < 1:
            continue  # Not enough future data
        
        future_idx = i + future_bars
        if future_idx >= len(df_all):
            future_idx = len(df_all) - 1
            
        future_price = float(df_all.iloc[future_idx]['close'])
        
        # Determine win/loss
        if final_signal == 'CALL':
            won = future_price > current_price
        else:  # PUT
            won = future_price < current_price
        
        pnl = STAKE * PAYOUT_RATIO if won else -STAKE
        
        trade = {
            'time': current_time,
            'direction': final_signal,
            'confidence': final_confidence,
            'entry_price': current_price,
            'exit_price': future_price,
            'duration_bars': future_bars,
            'duration_s': duration,
            'won': won,
            'pnl': pnl,
            'reasoning': reasoning[:100],
        }
        trades.append(trade)
        
        outcome = "✅ WIN" if won else "❌ LOSS"
        print(f"  {current_time.strftime('%H:%M')} | {final_signal:4s} | conf={final_confidence:.0%} | "
              f"entry={current_price:.2f} → exit={future_price:.2f} ({future_bars}bars) | "
              f"{outcome} | PnL: ${pnl:+.2f}")

# Summary
print(f"\n{'=' * 70}")
print(f"📊 SIMULATION RESULTS — NEW EMA Crossover Strategy")
print(f"{'=' * 70}")

total_signals = len(signals_log)
hold_count = sum(1 for s in signals_log if s['signal'] == 'HOLD')
trade_count = len(trades)

print(f"\n📋 Signal Distribution:")
print(f"   Total analysis cycles: {total_signals}")
print(f"   HOLD signals: {hold_count} ({hold_count/max(total_signals,1)*100:.0f}%)")
print(f"   Trade signals: {trade_count} ({trade_count/max(total_signals,1)*100:.0f}%)")

if trades:
    wins = sum(1 for t in trades if t['won'])
    losses = trade_count - wins
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = wins / trade_count * 100
    
    print(f"\n💰 Trade Results:")
    print(f"   Trades: {trade_count}")
    print(f"   Wins: {wins} | Losses: {losses}")
    print(f"   Win Rate: {win_rate:.1f}%")
    print(f"   Total P&L: ${total_pnl:+.2f}")
    print(f"   Avg PnL/trade: ${total_pnl/trade_count:+.2f}")
    
    # Breakdown by direction
    calls = [t for t in trades if t['direction'] == 'CALL']
    puts = [t for t in trades if t['direction'] == 'PUT']
    
    if calls:
        call_wins = sum(1 for t in calls if t['won'])
        call_pnl = sum(t['pnl'] for t in calls)
        print(f"\n   📈 CALL: {len(calls)} trades, {call_wins} wins ({call_wins/len(calls)*100:.0f}%), PnL: ${call_pnl:+.2f}")
    if puts:
        put_wins = sum(1 for t in puts if t['won'])
        put_pnl = sum(t['pnl'] for t in puts)
        print(f"   📉 PUT:  {len(puts)} trades, {put_wins} wins ({put_wins/len(puts)*100:.0f}%), PnL: ${put_pnl:+.2f}")
    
    # Show reasons for HOLDs
    print(f"\n📝 Sample HOLD reasons (last 10):")
    hold_reasons = [s for s in signals_log if s['signal'] == 'HOLD'][-10:]
    for h in hold_reasons:
        print(f"   {h['time'].strftime('%H:%M')} | {h['reasoning'][:90]}")
else:
    print(f"\n⚠️ No trades generated — strategy was too conservative or no valid signals in this period")
    print(f"\n📝 Sample HOLD reasons (last 15):")
    hold_reasons = [s for s in signals_log if s['signal'] == 'HOLD'][-15:]
    for h in hold_reasons:
        print(f"   {h['time'].strftime('%H:%M')} | {h['reasoning'][:100]}")

db.close()
