
import psycopg2
from datetime import datetime
import os

# Database Connection
DB_USER = "user"
DB_PASS = "password"
DB_NAME = "deriv_db"
DB_HOST = "db"

try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST
    )
    cur = conn.cursor()
    
    # Query last 2000 candles
    query = """
    SELECT time, open, close, (close - open) as change 
    FROM candle_data 
    ORDER BY time DESC 
    LIMIT 2000
    """
    
    cur.execute(query)
    rows = cur.fetchall()
    
    drops = []
    for r in rows:
        ts = r[0]
        change = float(r[3])
        if change < -2.0:
            dt = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            drops.append((dt, r[1], r[2], change))
    
    # Sort drops by change (ascending, i.e., most negative first)
    drops.sort(key=lambda x: x[3])
    
    print("Top 10 Drops Today (UTC):")
    for d in drops[:10]:
        print(f"Time: {d[0]} | Change: {d[3]:.2f} | Open: {d[1]} -> Close: {d[2]}")

    print("\nLast 5 Candles (Check current time):")
    for r in rows[:5]:
         ts = r[0]
         dt = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
         print(f"Time: {dt} | Close: {r[2]}")

except Exception as e:
    print(f"Error: {e}")
finally:
    if conn:
        conn.close()
