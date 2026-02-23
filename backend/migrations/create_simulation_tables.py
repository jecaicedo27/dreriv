"""
Database Migration: Simulation Sandbox Tables
Creates isolated tables for backtesting without affecting production
"""

import sys
sys.path.insert(0, '/app')

from sqlalchemy import text
from app.core.database import engine

def upgrade():
    """Create simulation sandbox tables"""
    
    with engine.connect() as conn:
        if False: # DEPRECATED: Historical data is now in 'candles' table
            # 1. Historical Candles (6 months data)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS historical_candles (
                    id BIGSERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    timeframe VARCHAR(10) NOT NULL,
                    open_time TIMESTAMP WITH TIME ZONE NOT NULL,
                    close_time TIMESTAMP WITH TIME ZONE,
                    
                    -- OHLCV
                    open NUMERIC(18, 8),
                    high NUMERIC(18, 8),
                    low NUMERIC(18, 8),
                    close NUMERIC(18, 8),
                    volume BIGINT,
                    
                    -- Pre-calculated indicators
                    rsi_14 NUMERIC(10, 4),
                    ema_9 NUMERIC(18, 8),
                    ema_21 NUMERIC(18, 8),
                    ema_50 NUMERIC(18, 8),
                    macd NUMERIC(18, 8),
                    macd_signal NUMERIC(18, 8),
                    macd_histogram NUMERIC(18, 8),
                    bollinger_upper NUMERIC(18, 8),
                    bollinger_middle NUMERIC(18, 8),
                    bollinger_lower NUMERIC(18, 8),
                    atr_14 NUMERIC(18, 8),
                    returns NUMERIC(18, 8),
                    momentum_5 NUMERIC(18, 8),
                    volatility_realized NUMERIC(18, 8),
                    price_position NUMERIC(10, 4),
                    
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(symbol, timeframe, open_time)
                );
            """))
            
            # Indexes for fast queries
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_hist_candles_time 
                ON historical_candles(open_time DESC);
            """))
            
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_hist_candles_symbol_time 
                ON historical_candles(symbol, open_time DESC);
            """))
        
        # 2. Simulation Runs (backtest metadata)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS simulation_runs (
                id BIGSERIAL PRIMARY KEY,
                name VARCHAR(100),
                strategy_name VARCHAR(50),
                
                -- Date range
                start_date TIMESTAMP WITH TIME ZONE,
                end_date TIMESTAMP WITH TIME ZONE,
                
                -- Config
                initial_balance NUMERIC(18, 2) DEFAULT 10000,
                config JSONB,
                
                -- Results
                final_balance NUMERIC(18, 2),
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                win_rate NUMERIC(5, 2),
                total_pnl NUMERIC(18, 2),
                max_drawdown_pct NUMERIC(5, 2),
                sharpe_ratio NUMERIC(10, 4),
                
                -- Metadata
                status VARCHAR(20) DEFAULT 'PENDING',
                error_message TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """))
        
        # 3. Simulation Trades (backtest results)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS simulation_trades (
                id BIGSERIAL PRIMARY KEY,
                run_id BIGINT REFERENCES simulation_runs(id) ON DELETE CASCADE,
                
                -- Trade info
                entry_time TIMESTAMP WITH TIME ZONE,
                exit_time TIMESTAMP WITH TIME ZONE,
                direction VARCHAR(10),
                entry_price NUMERIC(18, 8),
                exit_price NUMERIC(18, 8),
                stake NUMERIC(18, 2),
                
                -- Outcome
                outcome VARCHAR(20),
                profit_loss NUMERIC(18, 2),
                balance_after NUMERIC(18, 2),
                
                -- Decision context
                confidence NUMERIC(4, 2),
                reasoning TEXT,
                
                created_at TIMESTAMP DEFAULT NOW()
            );
        """))
        
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sim_trades_run 
            ON simulation_trades(run_id);
        """))
        
        conn.commit()
        print("✅ Simulation sandbox tables created successfully")

def downgrade():
    """Drop simulation sandbox tables"""
    
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS simulation_trades CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS simulation_runs CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS historical_candles CASCADE;"))
        conn.commit()
        print("✅ Simulation sandbox tables dropped")

if __name__ == "__main__":
    print("🔧 Running simulation sandbox migration...")
    upgrade()
