
from sqlalchemy import create_engine, text
from app.core.config import get_settings
import pandas as pd

try:
    engine = create_engine(get_settings().DATABASE_URL)
    run_id = 20  # Layer 1 Month Simulation
    
    query = text("""
        SELECT 
            entry_time, 
            direction, 
            entry_price, 
            exit_time, 
            exit_price, 
            profit_loss, 
            outcome 
        FROM simulation_trades 
        WHERE run_id = :run_id 
        ORDER BY entry_time ASC
    """)
    
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={'run_id': run_id})
        
        print(f"📊 REPORT FOR RUN {run_id}")
        print("-" * 50)
        print(f"Total Trades: {len(df)}")
        print(f"Total PnL: {df['profit_loss'].sum():.2f}")
        print(f"Win Rate: {(len(df[df['profit_loss'] > 0]) / len(df) * 100):.1f}%")
        print("-" * 50)
        # print(df.to_string(index=False))
        
except Exception as e:
    print(f"Error: {e}")
