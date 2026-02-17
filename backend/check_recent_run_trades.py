
from sqlalchemy import create_engine, text
from app.core.config import get_settings

try:
    engine = create_engine(get_settings().DATABASE_URL)
    with engine.connect() as conn:
        # Get latest run ID
        run_id = conn.execute(text("SELECT id FROM simulation_runs ORDER BY created_at DESC LIMIT 1")).fetchone()[0]
        print(f"🆔 Latest Run ID: {run_id}")
        
        # Count trades for this run
        count = conn.execute(text("SELECT COUNT(*) FROM simulation_trades WHERE run_id = :run_id"), {'run_id': run_id}).fetchone()[0]
        print(f"📊 Trades in this Run: {count}")
        
        if count > 0:
            last_trade = conn.execute(text("SELECT entry_time, profit_loss FROM simulation_trades WHERE run_id = :run_id ORDER BY entry_time DESC LIMIT 1"), {'run_id': run_id}).fetchone()
            print(f"🕒 Last Trade Time: {last_trade[0]}")
            print(f"💰 Last Trade PnL: {last_trade[1]}")
            
except Exception as e:
    print(f"Error checking run trades: {e}")
