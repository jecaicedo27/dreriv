"""
Download Historical Data from Deriv API
Downloads 6 months of R_100 1-minute candles for simulation
"""

import sys
sys.path.insert(0, '/app')

import asyncio
import pandas as pd
import json
import ssl
from datetime import datetime, timedelta, timezone as dt_timezone
from sqlalchemy import create_engine, text
from app.core.config import get_settings
from app.analysis.indicators import TechnicalIndicators
from loguru import logger

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)

async def fetch_candles_chunk(ws, symbol: str, start_epoch: int, end_epoch: int):
    """Fetch candles from Deriv API for a time range"""
    
    request = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "start": start_epoch,
        "end": end_epoch,
        "granularity": 60,  # 1 minute
        "style": "candles",
        "count": 5000  # Max allowed
    }
    
    await ws.send(json.dumps(request))
    response = await ws.recv()
    data = json.loads(response)
    
    if 'candles' not in data:
        logger.error(f"No candles in response: {data}")
        return []
    
    candles = []
    for c in data['candles']:
        candles.append({
            'open_time': datetime.fromtimestamp(c['epoch'], tz=dt_timezone.utc),
            'open': float(c['open']),
            'high': float(c['high']),
            'low': float(c['low']),
            'close': float(c['close']),
            'volume': 0  # Synthetic indices don't have volume
        })
    
    return candles

async def download_historical_data(months: int = 6):
    """Download historical candles from Deriv"""
    
    import websockets
    
    # Calculate date range
    end_date = datetime.now(dt_timezone.utc)
    start_date = end_date - timedelta(days=months * 30)
    
    total_days = (end_date - start_date).days
    expected_candles = total_days * 24 * 60
    
    print(f"\n{'='*70}")
    print(f"📥 HISTORICAL DATA DOWNLOAD")
    print(f"Stream: R_100 (Volatility 100 Index)")
    print(f"Period: {start_date.date()} → {end_date.date()}")
    print(f"Duration: {months} months (~{total_days} days)")
    print(f"Expected: ~{expected_candles:,} candles")
    print(f"{'='*70}\n")
    
    # Create chunks (3 days = ~4320 candles, under 5000 limit)
    chunk_days = 3
    chunks = []
    current = start_date
    
    while current < end_date:
        chunk_end = min(current + timedelta(days=chunk_days), end_date)
        chunks.append((current, chunk_end))
        current = chunk_end
    
    print(f"📦 Will download in {len(chunks)} chunks\n")
    
    # Connect to Deriv WebSocket
    url = f"wss://ws.derivws.com/websockets/v3?app_id={settings.DERIV_APP_ID}"
    
    all_candles = []
    
    async with websockets.connect(url, ping_interval=None) as ws:
        print("🔌 Connected to Deriv API")
        
        # Authorize first (optional but good for higher limits)
        # await ws.send(json.dumps({"ping": 1}))
        # await ws.recv()
        
        for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
            try:
                start_epoch = int(chunk_start.timestamp())
                end_epoch = int(chunk_end.timestamp())
                
                print(f"[{i}/{len(chunks)}] {chunk_start.strftime('%Y-%m-%d %H:%M')} → {chunk_end.strftime('%Y-%m-%d %H:%M')}", end=' ', flush=True)
                
                # Fetch candles
                candles = await fetch_candles_chunk(ws, "R_100", start_epoch, end_epoch)
                all_candles.extend(candles)
                
                print(f"✓ {len(candles)} candles")
                
                # Rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"✗ Error: {e}")
                logger.error(f"Chunk {i} failed: {e}")
                # Try to reconnect if error
                try:
                    await ws.close()
                except:
                    pass
                try:
                     ws = await websockets.connect(url, ping_interval=None)
                except Exception as rec_e:
                    print(f"  Reconnection failed: {rec_e}")
    
    print(f"\n✅ Downloaded {len(all_candles):,} candles total\n")
    
    if len(all_candles) == 0:
        print("❌ No candles downloaded. Exiting.")
        return
    
    # Convert to DataFrame
    print("🔄 Converting to DataFrame...")
    df = pd.DataFrame(all_candles)
    
    # Calculate indicators
    print("📊 Calculating technical indicators...")
    df_enriched = TechnicalIndicators.calculate_all(df)
    
    # Save to database
    print("💾 Saving to database...\n")
    
    saved = 0
    errors = 0
    
    with engine.connect() as conn:
        for idx, row in df_enriched.iterrows():
            try:
                conn.execute(text("""
                    INSERT INTO historical_candles 
                    (symbol, timeframe, open_time, close_time, open, high, low, close, volume,
                     rsi_14, ema_9, ema_21, ema_50, macd, macd_signal, macd_histogram,
                     bollinger_upper, bollinger_middle, bollinger_lower, atr_14,
                     returns, momentum_5, volatility_realized, price_position)
                    VALUES 
                    ('R_100', '1m', :open_time, :open_time + INTERVAL '1 minute',
                     :open, :high, :low, :close, :volume,
                     :rsi_14, :ema_9, :ema_21, :ema_50, :macd, :macd_signal, :macd_histogram,
                     :bollinger_upper, :bollinger_middle, :bollinger_lower, :atr_14,
                     :returns, :momentum_5, :volatility_realized, :price_position)
                    ON CONFLICT (symbol, timeframe, open_time) DO NOTHING
                """), {
                    'open_time': row['open_time'],
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row.get('volume', 0)),
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
                
                saved += 1
                
                if saved % 1000 == 0:
                    print(f"  Progress: {saved:,}/{len(df_enriched):,} candles saved")
                    conn.commit()
                    
            except Exception as e:
                errors += 1
                if errors < 5:
                    logger.error(f"Error saving candle {idx}: {e}")
        
        conn.commit()
    
    print(f"\n{'='*70}")
    print(f"🎉 DOWNLOAD COMPLETE")
    print(f"Saved: {saved:,} candles")
    print(f"Errors: {errors}")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    try:
        months = int(sys.argv[1]) if len(sys.argv) > 1 else 6
        asyncio.run(download_historical_data(months))
    except KeyboardInterrupt:
        print("\n\n⚠️ Download interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
