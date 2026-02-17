import asyncio
import websockets
import json
import ssl
from datetime import datetime

APP_ID = 125728  # From config
WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

async def test_connection():
    print(f"Connecting to {WS_URL}...")
    
    # Create SSL context to be explicit, though usually auto-handled
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    async with websockets.connect(WS_URL, ssl=ssl_context) as ws:
        print("Connected!")
        
        # 1. PING
        print("Sending Ping...")
        await ws.send(json.dumps({"ping": 1}))
        resp = await ws.recv()
        print(f"Ping Response: {resp}")
        
        # 2. History Request
        req = {
            "ticks_history": "R_100",
            "adjust_start_time": 1,
            "count": 10,
            "end": "latest",
            "style": "candles",
            "granularity": 60
        }
        print(f"Requesting History: {json.dumps(req)}")
        await ws.send(json.dumps(req))
        
        # Wait for response
        resp = await ws.recv()
        data = json.loads(resp)
        
        if "error" in data:
            print(f"❌ API Error: {data['error']}")
        elif "candles" in data:
            print(f"✅ Success! Received {len(data['candles'])} candles")
            print(f"Sample: {data['candles'][0]}")
        else:
            print(f"Unknown response: {data.keys()}")

if __name__ == "__main__":
    asyncio.run(test_connection())
