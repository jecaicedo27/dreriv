
import sys
import os
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

# Add /app to python path for Docker environment
sys.path.append('/app')

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.simulation.engine import SimulationEngine
from app.simulation.strategies.current_bot import CurrentBotStrategy

# Setup Logger
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="INFO")

def create_simulation_run(strategy_name, start_date, end_date):
    db = SessionLocal()
    try:
        # Use RAW SQL as SimulationRun model might depend on migrations not yet in app/models
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
            'conf': '{"layer2_enabled": false}',
            'now': datetime.now(timezone.utc)
        })
        run_id = result.fetchone()[0]
        db.commit()
        print(f"✅ Created Simulation Run ID: {run_id}")
        return run_id
    except Exception as e:
        print(f"❌ Failed to create run: {e}")
        db.rollback()
        raise
    finally:
        db.close()

async def main():
    print("🚀 Starting Layer 1 (No Groq) Simulation Launcher...")
    
    today = datetime.now(timezone.utc)
    # Start 6 months ago (where data begins)
    start_date = today - timedelta(days=180)
    # End 30 days later
    end_date = start_date + timedelta(days=30)
    
    print(f"📅 Period: {start_date} -> {end_date} (30 Days - Layer 1 Only)")
    
    # Create DB entry
    run_id = create_simulation_run("Layer1_Only_Sim", start_date, end_date)
    
    # Initialize Strategy (CurrentBot = Layer 1 Only)
    strategy = CurrentBotStrategy()
    
    # Initialize Engine
    engine = SimulationEngine(
        run_id=run_id,
        strategy=strategy,
        initial_balance=10000.0
    )
    
    # Run Simulation
    results = await engine.run(start_date, end_date)
    
    print("\n🏁 Final Results (Layer 1 Only):")
    print(results)

if __name__ == "__main__":
    asyncio.run(main())
