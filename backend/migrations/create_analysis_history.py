#!/usr/bin/env python3
"""
Create analysis_history table for storing bot analysis metrics
"""
import sys
sys.path.insert(0, '/app')

from app.core.database import engine
from sqlalchemy import text

def create_analysis_history_table():
    """Create analysis_history table"""
    
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS analysis_history (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        symbol VARCHAR(50) NOT NULL DEFAULT 'R_100',
        
        -- Hurst metrics
        hurst_value NUMERIC(6, 4),
        hurst_regime VARCHAR(50),
        
        -- O-U metrics
        ou_signal VARCHAR(10),
        ou_deviation NUMERIC(10, 4),
        ou_confidence NUMERIC(5, 4),
        ou_theta NUMERIC(10, 6),
        ou_half_life NUMERIC(10, 2),
        
        -- GARCH metrics
        garch_regime VARCHAR(50),
        garch_current_vol NUMERIC(10, 6),
        garch_forecast_vol NUMERIC(10, 6),
        garch_stake_multiplier NUMERIC(5, 2),
        
        -- Final signal
        final_signal VARCHAR(10),
        final_confidence NUMERIC(5, 4),
        contract_type VARCHAR(50),
        duration INTEGER,
        
        -- Price context
        current_price NUMERIC(12, 2),
        
        -- Technical indicators
        rsi_14 NUMERIC(6, 2),
        ema_9 NUMERIC(12, 2),
        ema_21 NUMERIC(12, 2),
        macd NUMERIC(12, 6),
        
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """
    
    create_indexes_sql = """
    CREATE INDEX IF NOT EXISTS idx_analysis_timestamp ON analysis_history(timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_analysis_symbol ON analysis_history(symbol);
    """
    
    with engine.connect() as conn:
        print("Creating analysis_history table...")
        conn.execute(text(create_table_sql))
        conn.commit()
        
        print("Creating indexes...")
        conn.execute(text(create_indexes_sql))
        conn.commit()
        
        print("✅ Table and indexes created successfully!")

if __name__ == "__main__":
    create_analysis_history_table()
