"""
Download EUR/USD Forex Historical Data from Deriv API
Saves to candles table for simulation compatibility
"""
import sys
sys.path.insert(0, '/app')

import asyncio
import pandas as pd
import json
from datetime import datetime, timedelta, timezone as dt_tz
from sqlalchemy import text
from app.core.database import SessionLocal
from app.analysis.indicators import TechnicalIndicators
from loguru import logger
from app.core.config import get_settings

settings = get_settings()

async def fetch_chunk(ws, symbol, start_epoch, end_epoch):
    req = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "start": start_epoch,
        "end": end_epoch,
        "granularity": 60,
        "style": "candles",
        "count": 5000
    }
    await ws.send(json.dumps(req))
    resp = json.loads(await ws.recv())
    if 'candles' not in resp:
        print(f"  ⚠️ No candles: {resp.get('error', {}).get('message', 'unknown')}")
        return []
    return [{
        'open_time': datetime.fromtimestamp(c['epoch'], tz=dt_tz.utc),
        'open': float(c['open']),
        'high': float(c['high']),
        'low': float(c['low']),
        'close': float(c['close']),
        'volume': 0
    } for c in resp['candles']]

async def download_forex(months=3):
    import websockets
    
    symbol = "frxEURUSD"
    end_date = datetime.now(dt_tz.utc)
    start_date = end_date - timedelta(days=months * 30)
    
    print(f"\n{'='*60}")
    print(f"📥 Downloading {symbol} | {start_date.date()} → {end_date.date()} ({months} months)")
    print(f"{'='*60}\n")
    
    # Chunks of 3 days
    chunks = []
    cur = start_date
    while cur < end_date:
        chunks.append((cur, min(cur + timedelta(days=3), end_date)))
        cur += timedelta(days=3)
    
    print(f"📦 {len(chunks)} chunks to download\n")
    
    url = f"wss://ws.derivws.com/websockets/v3?app_id={settings.DERIV_APP_ID}"
    all_candles = []
    
    async with websockets.connect(url, ping_interval=None) as ws:
        for i, (cs, ce) in enumerate(chunks, 1):
            try:
                candles = await fetch_chunk(ws, symbol, int(cs.timestamp()), int(ce.timestamp()))
                all_candles.extend(candles)
                print(f"  [{i}/{len(chunks)}] {cs.strftime('%Y-%m-%d')} → {ce.strftime('%Y-%m-%d')} ✓ {len(candles)} candles (total: {len(all_candles):,})")
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"  [{i}/{len(chunks)}] ✗ {e}")
    
    print(f"\n✅ Downloaded {len(all_candles):,} candles total")
    
    if not all_candles:
        print("❌ No data. Check if frxEURUSD is available on your Deriv app_id.")
        return
    
    # Calculate indicators
    print("📊 Calculating indicators...")
    df = pd.DataFrame(all_candles)
    df = df.drop_duplicates(subset='open_time').sort_values('open_time').reset_index(drop=True)
    df = TechnicalIndicators.calculate_all(df)
    print(f"   Enriched {len(df):,} candles with indicators")
    
    # Save to candles table using batch inserts with proper error handling
    print("💾 Saving to candles table...")
    db = SessionLocal()
    saved = 0
    errors = 0
    batch_size = 500
    
    for start_idx in range(0, len(df), batch_size):
        batch = df.iloc[start_idx:start_idx + batch_size]
        for _, row in batch.iterrows():
            try:
                db.execute(text("""
                    INSERT INTO candles (symbol, timeframe, open_time, close_time, open, high, low, close, volume,
                        rsi_14, ema_9, ema_21, ema_50, macd, macd_signal, macd_histogram,
                        bollinger_upper, bollinger_middle, bollinger_lower, atr_14,
                        returns, momentum_5, volatility_realized, price_position,
                        hurst_exponent, hurst_fast)
                    VALUES (:symbol, '1m', :open_time, :open_time + INTERVAL '1 minute',
                        :open, :high, :low, :close, :volume,
                        :rsi_14, :ema_9, :ema_21, :ema_50, :macd, :macd_signal, :macd_histogram,
                        :bollinger_upper, :bollinger_middle, :bollinger_lower, :atr_14,
                        :returns, :momentum_5, :volatility_realized, :price_position,
                        :hurst_exponent, :hurst_fast)
                    ON CONFLICT (symbol, timeframe, open_time) DO NOTHING
                """), {
                    'symbol': symbol,
                    'open_time': row['open_time'],
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': 0,
                    'rsi_14': float(row['rsi_14']) if pd.notna(row.get('rsi_14')) else None,
                    'ema_9': float(row['ema_9']) if pd.notna(row.get('ema_9')) else None,
                    'ema_21': float(row['ema_21']) if pd.notna(row.get('ema_21')) else None,
                    'ema_50': float(row['ema_50']) if pd.notna(row.get('ema_50')) else None,
                    'macd': float(row['macd']) if pd.notna(row.get('macd')) else None,
                    'macd_signal': float(row['macd_signal']) if pd.notna(row.get('macd_signal')) else None,
                    'macd_histogram': float(row['macd_histogram']) if pd.notna(row.get('macd_histogram')) else None,
                    'bollinger_upper': float(row['bollinger_upper']) if pd.notna(row.get('bollinger_upper')) else None,
                    'bollinger_middle': float(row['bollinger_middle']) if pd.notna(row.get('bollinger_middle')) else None,
                    'bollinger_lower': float(row['bollinger_lower']) if pd.notna(row.get('bollinger_lower')) else None,
                    'atr_14': float(row['atr_14']) if pd.notna(row.get('atr_14')) else None,
                    'returns': float(row['returns']) if pd.notna(row.get('returns')) else None,
                    'momentum_5': float(row['momentum_5']) if pd.notna(row.get('momentum_5')) else None,
                    'volatility_realized': float(row['volatility_realized']) if pd.notna(row.get('volatility_realized')) else None,
                    'price_position': float(row['price_position']) if pd.notna(row.get('price_position')) else None,
                    'hurst_exponent': float(row['hurst_exponent']) if pd.notna(row.get('hurst_exponent')) else None,
                    'hurst_fast': float(row['hurst_fast']) if pd.notna(row.get('hurst_fast')) else None,
                })
                saved += 1
            except Exception as e:
                db.rollback()
                errors += 1
                if errors <= 3:
                    print(f"   Error row: {e}")
        
        db.commit()
        print(f"   Progress: {saved:,}/{len(df):,} saved ({errors} errors)")
    
    db.close()
    
    print(f"\n{'='*60}")
    print(f"🎉 Saved {saved:,} candles for {symbol} ({errors} errors)")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    asyncio.run(download_forex(months))
