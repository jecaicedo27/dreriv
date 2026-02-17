"""
Migration: Create candle_patterns table with pgvector support
Run: docker exec deriv-backend python migrations/pattern_migration.py
"""
import sys
sys.path.insert(0, '/app')

from sqlalchemy import text
from app.core.database import SessionLocal


def run_migration():
    db = SessionLocal()
    try:
        # 1. Enable vector extension
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        db.commit()
        print("✅ pgvector extension enabled")

        # 2. Drop and recreate candle_patterns table
        db.execute(text("DROP TABLE IF EXISTS candle_patterns CASCADE;"))
        db.commit()
        db.execute(text("""
            CREATE TABLE candle_patterns (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL DEFAULT 'R_100',
                timeframe VARCHAR(10) NOT NULL DEFAULT '1m',
                
                -- The vector embedding (30 candles × 12 features = 360 dimensions)
                pattern_vector vector(360),
                
                -- When this pattern was observed
                pattern_time TIMESTAMPTZ NOT NULL,
                
                -- Outcome: what happened after this pattern
                outcome_direction VARCHAR(10),  -- 'CALL' or 'PUT' (which would have won)
                outcome_pips FLOAT,             -- How much price moved  
                outcome_5min FLOAT,             -- Price change after 5 min
                outcome_15min FLOAT,            -- Price change after 15 min
                
                -- Context
                regime_at_formation VARCHAR(30),
                hurst_at_formation FLOAT,
                rsi_at_formation FLOAT,
                
                -- Quality tracking
                pattern_quality_score FLOAT DEFAULT 0.5,
                times_matched INT DEFAULT 0,
                times_correct INT DEFAULT 0,
                last_used_at TIMESTAMPTZ,
                
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """))
        db.commit()
        print("✅ candle_patterns table created")

        # 3. Create HNSW index for fast similarity search
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_pattern_vector 
            ON candle_patterns 
            USING hnsw (pattern_vector vector_cosine_ops)
            WITH (m = 24, ef_construction = 128);
        """))
        db.commit()
        print("✅ HNSW index created (m=24, ef_construction=128)")

        # 4. Create supporting indexes
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_pattern_time ON candle_patterns (pattern_time);
            CREATE INDEX IF NOT EXISTS idx_pattern_regime ON candle_patterns (regime_at_formation);
            CREATE INDEX IF NOT EXISTS idx_pattern_symbol ON candle_patterns (symbol, timeframe);
        """))
        db.commit()
        print("✅ Supporting indexes created")

        # Verify
        count = db.execute(text("SELECT COUNT(*) FROM candle_patterns")).scalar()
        print(f"\n📊 candle_patterns table ready. Current rows: {count}")
        
        # Check vector extension
        ext = db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
        print(f"📦 pgvector version: {ext}")

    except Exception as e:
        db.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
