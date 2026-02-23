import requests
import time
import sys

# Generate 53 dates from Jan 1 to Feb 22
dates = []
for d in range(1, 32):
    dates.append(f"2026-01-{d:02d}")
for d in range(1, 23):
    dates.append(f"2026-02-{d:02d}")

url_start = "http://localhost:8000/api/simulation/engine-battle"
url_status = "http://localhost:8000/api/simulation/engine-battle/status"

payload = {
    "dates": dates,
    "config": {
        "initial_balance": 10000,
        "stake": 50
    }
}

print(f"🚀 Starting 53-day battle for {len(dates)} dates...")
try:
    r = requests.post(url_start, json=payload)
    if r.status_code != 200:
        print(f"Error starting: {r.text}")
        sys.exit(1)
    print("✅ Battle triggered successfully!")
except Exception as e:
    print(f"Connection error: {e}")
    sys.exit(1)

# Poll until done
while True:
    time.sleep(10)
    try:
        r = requests.get(url_status)
        data = r.json()
        if not data.get("running"):
            winner = data.get("winner", "Unknown")
            print(f"\n🏆 BATTLE FINISHED! Winner: {winner}")
            
            # Print ranked results
            results = data.get("results", [])
            for i, res in enumerate(results):
                eng = res.get("engine", "Unknown")
                wr = res.get("win_rate", 0)
                pnl = res.get("total_pnl", 0)
                trades = res.get("total_trades", 0)
                print(f"  {i+1}. {eng}: {trades} trades | {wr}% WR | PnL: ${pnl}")
            break
        else:
            engines = data.get("engines", {})
            progs = []
            for name, st in engines.items():
                pct = int((st.get("progress", 0) / len(dates)) * 100)
                progs.append(f"{name}:{pct}%")
            print(f"⏱️ Running... [{', '.join(progs)}]")
    except Exception as e:
        print(f"Polling error: {e}")
        pass
