
from sqlalchemy import create_engine, text
from app.core.config import get_settings

try:
    engine = create_engine(get_settings().DATABASE_URL)
    with engine.connect() as conn:
        # Check trades
        trades = conn.execute(text("SELECT COUNT(*) FROM simulation_trades")).fetchone()[0]
        
        # Check run status
        run = conn.execute(text("SELECT status, total_trades, win_rate FROM simulation_runs ORDER BY created_at DESC LIMIT 1")).fetchone()
        
        print(f"📊 Simulation Trades: {trades}")
        if run:
            print(f"🏃 Run Status: {run[0]}")
            print(f"📈 Total Trades in Run: {run[1]}")
            print(f"✅ Win Rate: {run[2]}%")
        
except Exception as e:
    print(f"Error checking trades: {e}")
