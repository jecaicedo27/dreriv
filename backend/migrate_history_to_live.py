
import sys
import time
from sqlalchemy import text
from app.core.database import SessionLocal, engine
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

def migrate_history():
    """
    Migrate data from historical_candles to candles table.
    1. Copy old history (Aug-Jan)
    2. Update recent history (Feb 1-19) with calculated indicators
    """
    logger.info("🚀 Starting migration...")
    
    with engine.connect() as conn:
        # 1. Copy old history (open_time < '2026-02-01')
        logger.info("📦 Copying old history (Aug 2025 - Jan 2026)...")
        result = conn.execute(text("""
            INSERT INTO candles (
                symbol, timeframe, open_time, close_time, 
                open, high, low, close, volume,
                rsi_14, ema_9, ema_21, ema_50, 
                macd, macd_signal, macd_histogram,
                bollinger_upper, bollinger_middle, bollinger_lower, 
                atr_14, returns, momentum_5, volatility_realized, price_position,
                hurst_exponent, ou_deviation, garch_volatility_forecast, regime,
                is_order_block, ob_type, is_fvg, fvg_type, bos, choch, created_at
            )
            SELECT 
                symbol, timeframe, open_time, close_time, 
                open, high, low, close, volume,
                rsi_14, ema_9, ema_21, ema_50, 
                macd, macd_signal, macd_histogram,
                bollinger_upper, bollinger_middle, bollinger_lower, 
                atr_14, returns, momentum_5, volatility_realized, price_position,
                hurst_exponent, ou_deviation, garch_volatility_forecast, regime,
                is_order_block, ob_type, is_fvg, fvg_type, bos, choch, created_at
            FROM historical_candles
            WHERE open_time < '2026-02-01'
            ON CONFLICT DO NOTHING
        """))
        conn.commit()
        logger.success(f"✅ Copied {result.rowcount} rows")
        
        # 2. Update recent history (Feb 1 - Present)
        logger.info("🔄 Updating recent indicators (Feb 2026)...")
        result = conn.execute(text("""
            UPDATE candles c
            SET hurst_exponent = h.hurst_exponent,
                ou_deviation = h.ou_deviation,
                regime = h.regime,
                garch_volatility_forecast = h.garch_volatility_forecast
            FROM historical_candles h
            WHERE c.symbol = h.symbol 
              AND c.open_time = h.open_time
              AND h.hurst_exponent IS NOT NULL
              AND (c.hurst_exponent IS NULL OR c.regime IS NULL)
        """))
        conn.commit()
        logger.success(f"✅ Updated {result.rowcount} rows with indicators")
        
        logger.success("🎉 Migration complete!")

if __name__ == "__main__":
    migrate_history()
