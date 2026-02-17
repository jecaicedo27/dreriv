"""
Candle Enrichment Service - Fixed Version
Pre-calculates and stores all indicators for backtesting
"""

import sys
sys.path.insert(0, '/app')

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from app.core.config import get_settings
from app.analysis.indicators import TechnicalIndicators

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)

def enrich_historical_candles():
    """
    Backfill indicators for existing candles using pandas batch processing
    """
    print("\n🔄 Enriching historical candles with indicators...\n")
    
    # Load all candles
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT id, open_time, open, high, low, close, volume
            FROM candles
            ORDER BY open_time ASC
        """), conn)
    
    if len(df) < 50:
        print(f"❌ Not enough candles ({len(df)}). Need at least 50.")
        return
    
    print(f"📊 Loaded {len(df)} candles")
    print(f"📅 Period: {df['open_time'].min()} → {df['open_time'].max()}")
    print(f"\n⏳ Calculating indicators...\n")
    
    # Calculate all indicators at once
    df_enriched = TechnicalIndicators.calculate_all(df)
    
    print(f"✅ Calculated indicators\n")
    print(f"⏳ Saving to database...\n")
    
    # Update database in batches
    updated = 0
    errors = 0
    
    with engine.connect() as conn:
        for idx, row in df_enriched.iterrows():
            try:
                conn.execute(text("""
                    UPDATE candles
                    SET 
                        rsi_14 = :rsi_14,
                        ema_9 = :ema_9,
                        ema_21 = :ema_21,
                        ema_50 = :ema_50,
                        macd = :macd,
                        macd_signal = :macd_signal,
                        macd_histogram = :macd_histogram,
                        bollinger_upper = :bollinger_upper,
                        bollinger_middle = :bollinger_middle,
                        bollinger_lower = :bollinger_lower,
                        atr_14 = :atr_14,
                        returns = :returns,
                        momentum_5 = :momentum_5,
                        volatility_realized = :volatility_realized,
                        price_position = :price_position
                    WHERE id = :candle_id
                """), {
                    'candle_id': int(row['id']),
                    'rsi_14': float(row.get('rsi_14', 0)) if pd.notna(row.get('rsi_14')) else None,
                    'ema_9': float(row.get('ema_9', 0)) if pd.notna(row.get('ema_9')) else None,
                    'ema_21': float(row.get('ema_21', 0)) if pd.notna(row.get('ema_21')) else None,
                    'ema_50': float(row.get('ema_50', 0)) if pd.notna(row.get('ema_50')) else None,
                    'macd': float(row.get('macd', 0)) if pd.notna(row.get('macd')) else None,
                    'macd_signal': float(row.get('macd_signal', 0)) if pd.notna(row.get('macd_signal')) else None,
                    'macd_histogram': float(row.get('macd_histogram', 0)) if pd.notna(row.get('macd_histogram')) else None,
                    'bollinger_upper': float(row.get('bollinger_upper', 0)) if pd.notna(row.get('bollinger_upper')) else None,
                    'bollinger_middle': float(row.get('bollinger_middle', 0)) if pd.notna(row.get('bollinger_middle')) else None,
                    'bollinger_lower': float(row.get('bollinger_lower', 0)) if pd.notna(row.get('bollinger_lower')) else None,
                    'atr_14': float(row.get('atr_14', 0)) if pd.notna(row.get('atr_14')) else None,
                    'returns': float(row.get('returns', 0)) if pd.notna(row.get('returns')) else None,
                    'momentum_5': float(row.get('momentum_5', 0)) if pd.notna(row.get('momentum_5')) else None,
                    'volatility_realized': float(row.get('volatility_realized', 0)) if pd.notna(row.get('volatility_realized')) else None,
                    'price_position': float(row.get('price_position', 0)) if pd.notna(row.get('price_position')) else None
                })
                
                updated += 1
                
                if updated % 100 == 0:
                    print(f"  Progress: {updated}/{len(df)} candles")
                    conn.commit()
                    
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"❌ Error updating candle {row['id']}: {e}")
        
        conn.commit()
    
    print(f"\n✅ Enrichment complete!")
    print(f"   Updated: {updated} candles")
    print(f"   Errors: {errors}")
    print(f"\n📊 Sample enriched candle:")
    
    # Show sample
    with engine.connect() as conn:
        sample = conn.execute(text("""
            SELECT open_time, close, rsi_14, macd, macd_signal
            FROM candles
            WHERE rsi_14 IS NOT NULL
            ORDER BY open_time DESC
            LIMIT 1
        """))
        row = sample.fetchone()
        if row:
            print(f"   Time: {row[0]}")
            print(f"   Close: {row[1]:.2f}")
            print(f"   RSI: {row[2]:.2f if row[2] else 'N/A'}")
            print(f"   MACD: {row[3]:.4f if row[3] else 'N/A'}")
            print(f"   Signal: {row[4]:.4f if row[4] else 'N/A'}")

if __name__ == "__main__":
    try:
        enrich_historical_candles()
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
