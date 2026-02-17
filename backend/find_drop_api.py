
import urllib.request
import json
from datetime import datetime

url = "http://localhost:8000/api/candles?limit=2000"

try:
    with urllib.request.urlopen(url) as response:
        if response.status != 200:
            print(f"Error: API returned status {response.status}")
            exit(1)
            
        data = json.loads(response.read().decode())
        
        # data is list of {time, open, high, low, close}
        # Find drops
        drops = []
        for c in data:
            change = c['close'] - c['open']
            if change < -2.0:
                dt = datetime.utcfromtimestamp(c['time']).strftime('%Y-%m-%d %H:%M:%S')
                drops.append({
                    'time': dt,
                    'ts': c['time'],
                    'change': change,
                    'o': c['open'],
                    'c': c['close']
                })
        
        drops.sort(key=lambda x: x['change']) # Most negative first
        
        print(f"Total Candles Fetched: {len(data)}")
        print("Top 10 Bearish Candles (UTC):")
        for d in drops[:10]:
            print(f"Time: {d['time']} | Change: {d['change']:.2f} | {d['o']} -> {d['c']}")
            
        # Also print recent candles to verify time
        last = data[-1]
        last_dt = datetime.utcfromtimestamp(last['time']).strftime('%Y-%m-%d %H:%M:%S')
        print(f"\nLast Candle Time: {last_dt} | Close: {last['close']}")

except Exception as e:
    print(f"Error: {e}")
