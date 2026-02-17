#!/usr/bin/env python3
"""
Run Simulation - CLI Tool
Execute backtests on historical data without affecting production

Usage:
    python simulate.py --strategy CurrentBotStrategy --start 2025-08-01 --end 2026-02-01 --name "baseline-6m"
    python simulate.py --months 3 --strategy CurrentBotStrategy
"""

import sys
sys.path.insert(0, '/app')

import asyncio
import argparse
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text
from loguru import logger

from app.core.config import get_settings
from app.simulation.engine import SimulationEngine
from app.simulation.strategies.current_bot import CurrentBotStrategy
from app.simulation.strategies.old_5min_bug import Old5MinStrategy
from app.simulation.strategies.new_15min_fix import New15MinStrategy

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)


# Strategy registry
STRATEGIES = {
    'CurrentBotStrategy': CurrentBotStrategy,
    'Old5MinStrategy': Old5MinStrategy,      # Bug replica: 300s always
    'New15MinStrategy': New15MinStrategy,    # Fixed: 900s for TRENDING
}


async def run_simulation(args):
    """Run a simulation"""
    
    # Parse dates
    if args.months:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=args.months * 30)
    else:
        start_date = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end_date = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    
    # Get strategy class
    if args.strategy not in STRATEGIES:
        print(f"❌ Unknown strategy: {args.strategy}")
        print(f"Available strategies: {', '.join(STRATEGIES.keys())}")
        return
    
    StrategyClass = STRATEGIES[args.strategy]
    
    # Create simulation run record
    with engine.connect() as conn:
        result = conn.execute(text("""
            INSERT INTO simulation_runs
            (name, strategy_name, start_date, end_date, initial_balance, config)
            VALUES (:name, :strategy, :start, :end, :balance, CAST(:config AS jsonb))
            RETURNING id
        """), {
            'name': args.name or f"{args.strategy}_{start_date.date()}",
            'strategy': args.strategy,
            'start': start_date,
            'end': end_date,
            'balance': args.balance,
            'config': '{}'
        })
        run_id = result.fetchone()[0]
        conn.commit()
    
    logger.info(f"🆔 Simulation run ID: {run_id}")
    
    # Create strategy instance
    strategy = StrategyClass(config={
        'min_confidence': args.min_confidence,
        'default_stake': args.stake
    })
    
    # Create engine
    sim_engine = SimulationEngine(
        run_id=run_id,
        strategy=strategy,
        initial_balance=args.balance
    )
    
    # Run simulation
    try:
        results = await sim_engine.run(start_date, end_date)
        
        # Print results
        print("\n" + "="*70)
        print("🎉 SIMULATION COMPLETE")
        print("="*70)
        print(f"Strategy: {args.strategy}")
        print(f"Period: {start_date.date()} → {end_date.date()}")
        print(f"\n📊 RESULTS:")
        print(f"  Initial Balance:  ${args.balance:,.2f}")
        print(f"  Final Balance:    ${results['final_balance']:,.2f}")
        print(f"  Total P&L:        ${results['total_pnl']:+,.2f}")
        print(f"  Total Trades:     {results['total_trades']}")
        print(f"  Winning Trades:   {results['winning_trades']}")
        print(f"  Losing Trades:    {results['losing_trades']}")
        print(f"  Win Rate:         {results['win_rate']:.1f}%")
        print(f"  Max Drawdown:     {results['max_drawdown_pct']:.2f}%")
        print("="*70 + "\n")
        
        print(f"✅ Results saved to simulation_runs.id = {run_id}")
        print(f"   View trades: SELECT * FROM simulation_trades WHERE run_id = {run_id};")
        
    except Exception as e:
        logger.error(f"❌ Simulation failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description='Run trading strategy simulation')
    
    # Date options
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--start', help='Start date (YYYY-MM-DD)')
    date_group.add_argument('--months', type=int, help='Number of months from now backwards')
    
    parser.add_argument('--end', help='End date (YYYY-MM-DD), defaults to now')
    
    # Strategy
    parser.add_argument('--strategy', required=True, help='Strategy name (e.g., CurrentBotStrategy)')
    parser.add_argument('--name', help='Simulation run name')
    
    # Config
    parser.add_argument('--balance', type=float, default=10000.0, help='Initial balance (default: 10000)')
    parser.add_argument('--stake', type=float, default=60.0, help='Stake per trade (default: 60)')
    parser.add_argument('--min-confidence', type=float, default=0.60, help='Min confidence threshold (default: 0.60)')
    
    args = parser.parse_args()
    
    # Run
    asyncio.run(run_simulation(args))


if __name__ == "__main__":
    main()
