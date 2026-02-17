
import sys
import os
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

# Add /app to python path for Docker environment
sys.path.append('/app')

from app.core.database import SessionLocal
from app.simulation.engine import SimulationEngine
from app.simulation.strategies.full_stack import FullStackStrategy

# API KEY from environment
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

def create_simulation_run(strategy_name, start_date, end_date):
    db = SessionLocal()
    try:
        # Check if table exists first (sanity check)
        result = db.execute(text("""
            INSERT INTO simulation_runs 
            (strategy_name, start_date, end_date, initial_balance, status, config, created_at)
            VALUES (:name, :start, :end, :bal, :status, :conf, :now)
            RETURNING id
        """), {
            'name': strategy_name,
            'start': start_date,
            'end': end_date,
            'bal': 10000.0,
            'status': 'PENDING',
            'conf': '{}', # Empty JSON config
            'now': datetime.now(timezone.utc)
        })
        run_id = result.fetchone()[0]
        db.commit()
        print(f"🆕 Created Simulation Run ID: {run_id}")
        return run_id
    except Exception as e:
        print(f"❌ Error creating run: {e}")
        db.rollback()
        # Fallback: maybe table doesn't exist?
        return None
    finally:
        db.close()

async def main():
    print("🚀 Starting Groq Simulation Launcher...")
    
    now = datetime.now(timezone.utc)
    # Start 6 months ago (where data begins)
    start_date = now - timedelta(days=180)
    # End 1 day later (Just 24 hours)
    end_date = start_date + timedelta(days=1)
    
    print(f"📅 Period: {start_date} -> {end_date} (Single Day Simulation)")
    
    # Create DB entry
    run_id = create_simulation_run("FullStack_Groq_Sim", start_date, end_date)
    
    if not run_id:
        print("❌ Could not create simulation run. Aborting.")
        return

    # Initialize Strategy with Custom Key
    try:
        strategy = FullStackStrategy(api_key=GROQ_API_KEY)
        print("✅ Strategy Initialized")
    except Exception as e:
        print(f"❌ Error initializing strategy: {e}")
        return
    
    # Initialize Engine
    try:
        engine = SimulationEngine(
            run_id=run_id,
            strategy=strategy,
            initial_balance=10000.0
        )
        print("✅ Engine Initialized")
    except Exception as e:
        print(f"❌ Error initializing engine: {e}")
        return
    
    # Run Simulation
    await engine.run(start_date, end_date)

if __name__ == "__main__":
    asyncio.run(main())
