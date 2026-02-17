
import sys
sys.path.insert(0, '/app')

import asyncio
import pandas as pd
from app.simulation.strategies.current_bot import CurrentBotStrategy
from app.simulation.engine import SimulationEngine
from datetime import datetime, timezone

class DebugStrategy(CurrentBotStrategy):
    async def analyze(self, current_candle, history):
        # Call original for logic check
        params = {
            'rsi': current_candle.get('rsi_14'),
            'ema_9': current_candle.get('ema_9'),
            'ema_21': current_candle.get('ema_21'),
            'close': current_candle.get('close')
        }
        
        decision = await super().analyze(current_candle, history)
        
        # Log first few candles to see what we have
        if len(history) % 1000 == 0:
            print(f"DEBUG Candle {current_candle['open_time']}: {params} -> {decision}")
        
        return decision

async def run_debug():
    strategy = DebugStrategy()
    engine = SimulationEngine(run_id=999, strategy=strategy)
    
    start = datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 9, 0, 0, tzinfo=timezone.utc)
    
    print("Running debug simulation...")
    await engine.run(start, end)

if __name__ == "__main__":
    asyncio.run(run_debug())
