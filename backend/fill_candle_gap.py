"""
Fill Candle Gap — Downloads missing candles from Deriv API
and inserts them into the live 'candles' table.
Then runs indicator backfill (Pass 1 + Pass 2).
"""
import sys
sys.path.insert(0, '/app')

import asyncio
import json
import ssl
from datetime import datetime, timezone
from sqlalchemy import text
from app.core.database import SessionLocal
from app.core.config import get_settings

settings = get_settings()


async def fetch_and_fill_gap():
    """Fetch missing candles from Deriv and insert into candles table"""
    db = SessionLocal()
    
    try:
        # 1. Find the gap
        last_candle = db.execute(text(
            "SELECT MAX(open_time) FROM candles WHERE symbol = 'R_100'"
        )).scalar()
        
        first_new = db.execute(text(
            "SELECT MIN(open_time) FROM candles WHERE symbol = 'R_100' AND open_time::date = CURRENT_DATE"
        )).scalar()
        
        print(f"📊 Last candle before gap: {last_candle}")
        print(f"📊 First candle after gap: {first_new}")
        
        if not last_candle:
            print("❌ No candles in DB at all!")
            return
        
        # Calculate gap range
        import time
        start_epoch = int(last_candle.timestamp()) + 60  # Start 1 min after last candle
        end_epoch = int(time.time()) - 60  # Up to 1 min ago
        
        gap_minutes = (end_epoch - start_epoch) // 60
        print(f"🕳️ Gap: ~{gap_minutes} minutes ({gap_minutes/60:.1f} hours)")
        
        if gap_minutes <= 0:
            print("✅ No gap to fill!")
            return
        
        # 2. Connect to Deriv WebSocket and fetch candles
        import websockets
        
        uri = "wss://ws.derivws.com/websockets/v3"
        ssl_ctx = ssl.create_default_context()
        
        print(f"🔌 Connecting to Deriv API...")
        async with websockets.connect(uri, ssl=ssl_ctx) as ws:
            # Fetch candles in chunks of 5000
            all_candles = []
            chunk_start = start_epoch
            
            while chunk_start < end_epoch:
                chunk_end = min(chunk_start + 5000 * 60, end_epoch)
                
                request = {
                    "ticks_history": "R_100",
                    "adjust_start_time": 1,
                    "count": 5000,
                    "end": chunk_end,
                    "start": chunk_start,
                    "style": "candles",
                    "granularity": 60
                }
                
                await ws.send(json.dumps(request))
                response = json.loads(await ws.recv())
                
                if 'candles' in response:
                    candles = response['candles']
                    all_candles.extend(candles)
                    print(f"   📥 Fetched {len(candles)} candles ({datetime.fromtimestamp(chunk_start, tz=timezone.utc).strftime('%H:%M')} → {datetime.fromtimestamp(chunk_end, tz=timezone.utc).strftime('%H:%M')})")
                    chunk_start = chunk_end + 60
                else:
                    print(f"   ⚠️ No candles in response: {response.get('error', {}).get('message', 'unknown')}")
                    break
                
                await asyncio.sleep(0.5)  # Rate limit
            
            print(f"\n📊 Total fetched: {len(all_candles)} candles")
        
        # 3. Insert into candles table
        if not all_candles:
            print("❌ No candles to insert")
            return
        
        inserted = 0
        skipped = 0
        
        for c in all_candles:
            open_time = datetime.fromtimestamp(c['epoch'], tz=timezone.utc)
            
            try:
                result = db.execute(text("""
                    INSERT INTO candles (symbol, timeframe, open_time, close_time, open, high, low, close, volume)
                    VALUES ('R_100', '1m', :open_time, :open_time + INTERVAL '1 minute',
                            :open, :high, :low, :close, 0)
                    ON CONFLICT (symbol, timeframe, open_time) DO NOTHING
                """), {
                    'open_time': open_time,
                    'open': float(c['open']),
                    'high': float(c['high']),
                    'low': float(c['low']),
                    'close': float(c['close']),
                })
                
                if result.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
                    
            except Exception as e:
                db.rollback()
                print(f"   ❌ Error inserting: {e}")
                continue
        
        db.commit()
        print(f"\n✅ Inserted: {inserted} new candles, Skipped: {skipped} duplicates")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    # Step 1: Fill the gap
    print("=" * 60)
    print("STEP 1: Download & Fill Missing Candles")
    print("=" * 60)
    asyncio.run(fetch_and_fill_gap())
    
    # Step 2: Run indicator backfill
    print("\n" + "=" * 60)
    print("STEP 2: Backfill Indicators (Pass 1 + Pass 2)")
    print("=" * 60)
    from backfill_two_pass import pass1_standard_indicators, pass2_hurst_ou
    pass1_standard_indicators()
    pass2_hurst_ou()
    
    print("\n🎉 ALL DONE!")
