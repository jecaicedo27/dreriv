import os
import sys
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings
from app.models.models import Candle
from app.analysis.layer1_engine import Layer1SignalEngine
from app.services.data_collector import DataCollector

# Setup
settings = get_settings()
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

def analyze_now():
    print("🔍 Fetching latest market data...")
    # Get last 300 candles
    candles = db.query(Candle).order_by(Candle.open_time.desc()).limit(300).all()
    candles.reverse()
    
    if len(candles) < 200:
        print("❌ Not enough data.")
        return

    # Convert to DataFrame
    df = pd.DataFrame([{
        'open_time': c.open_time,
        'open': float(c.open),
        'high': float(c.high),
        'low': float(c.low),
        'close': float(c.close),
        'volume': float(c.volume) if c.volume else 0
    } for c in candles])
    
    current_price = df.iloc[-1]['close']
    print(f"💰 Current Price: {current_price:.2f}")

    # Run Analysis
    print("🧠 Running Layer 1 Engine...")
    engine = Layer1SignalEngine()
    result = engine.analyze(df, 'R_100')
    
    # Extract details
    signal = result.get('final_signal')
    reasoning = result.get('reasoning')
    hurst = result['hurst_signal']
    ou = result['ou_signal']
    indicators = result['indicators']
    
    print("\n📊 --- INDICATORS ---")
    print(f"1. Hurst Exponent: {hurst.get('hurst', 0):.4f} (Regime: {hurst.get('regime')})")
    print(f"   -> Threshold for Strong Trend: > 0.65")
    print(f"   -> Threshold for Mean Reversion: < 0.45")
    
    print(f"\n2. EMA Trend:")
    ema21 = indicators.get('ema_21', 0)
    ema50 = indicators.get('ema_50', 0)
    print(f"   EMA21: {ema21:.2f} | EMA50: {ema50:.2f}")
    if ema21 > ema50:
        print("   -> Structurally BULLISH (21 > 50)")
    else:
        print("   -> Structurally BEARISH (21 < 50)")
        
    print(f"\n3. RSI (Momentum): {indicators.get('rsi_14', 0):.2f}")
    print("   -> Neutral Zone: 40-60 (No clear momentum)")
    
    print(f"\n4. MACD Histogram: {indicators.get('macd_histogram', 0):.4f}")
    
    print("\n🚦 --- DECISION LOGIC ---")
    print(f"Final Signal: {signal}")
    print(f"Confidence: {result.get('final_confidence', 0):.2%}")
    print(f"Reasoning Checklist:")
    if isinstance(reasoning, list):
        for r in reasoning:
            print(f"   - {r}")
    else:
        print(f"   - {reasoning}")

    db.close()

if __name__ == "__main__":
    analyze_now()
