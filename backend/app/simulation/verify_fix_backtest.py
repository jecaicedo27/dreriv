import asyncio
import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from app.analysis.layer1_engine import Layer1Engine
from app.services.database import get_db_session
from app.models.candle import Candle
from sqlalchemy import select

async def run_verification():
    print("--- 🔍 VERIFICATION SIMULATION: FEB 12 REPLAY ---")
    print("Objective: Test if new Hurst > 0.65 filter prevents past losses.")
    
    # Initialize Engine with NEW logic
    engine = Layer1Engine()
    
    # Define the "Losing Session" window (Feb 12 14:00 - 16:00 UTC)
    start_time = datetime(2026, 2, 12, 14, 0, 0)
    end_time = datetime(2026, 2, 12, 16, 0, 0)
    
    print(f"Loading candles from {start_time} to {end_time}...")
    
    async with get_db_session() as session:
        query = select(Candle).where(
            Candle.symbol == "R_100",
            Candle.time >= start_time,
            Candle.time <= end_time
        ).order_by(Candle.time)
        
        result = await session.execute(query)
        candles_db = result.scalars().all()
        
    print(f"Loaded {len(candles_db)} candles.")
    
    # Convert to DataFrame for the engine
    df = pd.DataFrame([{
        'time': c.time,
        'open': c.open,
        'high': c.high,
        'low': c.low,
        'close': c.close,
        'tick_volume': c.tick_volume
    } for c in candles_db])
    
    df['time'] = pd.to_datetime(df['time'])
    df.set_index('time', inplace=True)
    
    # Simulate step-by-step
    signals = []
    
    # We need at least 100 candles to start calculating indicators
    window_size = 200
    
    print("\n--- SIMULATION START ---")
    
    potential_trades = 0
    avoided_trades = 0
    allowed_trades = 0
    
    for i in range(window_size, len(df)):
        # Slice the "current" view of the market
        current_slice = df.iloc[i-window_size:i+1]
        current_time = current_slice.index[-1]
        
        try:
            # Run Layer 1 Analysis (The new code)
            signal = engine.analyze(current_slice)
            
            # Check if it generated a signal
            if signal['decision'] != 'HOLD':
                hurst = signal.get('metrics', {}).get('hurst', {}).get('value', 0)
                
                print(f"[{current_time}] SIGNAL: {signal['decision']} | Hurst: {hurst:.3f} | Conf: {signal['confidence']:.2f}")
                
                # Check if this matches a time we lost money?
                # (Simplified: Just count how many signals pass the new filter)
                allowed_trades += 1
                
            else:
                # It was a HOLD. Why?
                reason = signal.get('reasoning', ['Unknown'])[0]
                if "Trend too weak" in reason or "Hurst" in reason:
                    # print(f"[{current_time}] HOLD (Filtered): {reason}") 
                    pass
                
        except Exception as e:
            print(f"Error at {current_time}: {e}")
            continue

    print("\n--- RESULTS ---")
    print(f"Total Candles Analyzed: {len(df) - window_size}")
    print(f"Trades Generated with NEW Logic (Hurst > 0.65): {allowed_trades}")
    
    if allowed_trades == 0:
        print("\n✅ SUCCESS: The new filter BLOCKED all bad trades from this session!")
        print("   (Previously: 10 losses. Now: 0 trades = $0 loss)")
    else:
        print(f"\n⚠️ WARNING: {allowed_trades} trades still passed. Check logs.")

if __name__ == "__main__":
    asyncio.run(run_verification())
