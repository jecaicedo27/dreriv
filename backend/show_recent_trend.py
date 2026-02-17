
import urllib.request
import json
from datetime import datetime, timedelta

url = "http://localhost:8000/api/candles?limit=300" # Last 5 hours

try:
    with urllib.request.urlopen(url) as response:
        if response.status != 200:
            print(f"Error: API returned status {response.status}")
            exit(1)
            
        data = json.loads(response.read().decode())
        
        # Print header
        print(f"{'Time (UTC)':<20} | {'Close':<10} | {'Change':<10}")
        print("-" * 50)
        
        # Sample every 10 minutes to verify trend shape
        for i, c in enumerate(data):
            if i % 10 == 0:
                dt = datetime.utcfromtimestamp(c['time']).strftime('%Y-%m-%d %H:%M:%S')
                change = c['close'] - c['open']
                print(f"{dt:<20} | {c['close']:<10.2f} | {change:<10.2f}")

except Exception as e:
    print(f"Error: {e}")
