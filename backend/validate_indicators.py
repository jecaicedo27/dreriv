"""
Indicator Quality Validator
Detects flat lines, NULLs, and suspicious patterns in candle indicators.
"""
import sys
import pandas as pd
import numpy as np
from sqlalchemy import text
from app.core.database import SessionLocal
from loguru import logger

logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")

def validate_indicators():
    db = SessionLocal()
    try:
        # ============================================================
        # 1. NULL CHECK — How many candles are missing each indicator?
        # ============================================================
        logger.info("=" * 60)
        logger.info("1️⃣  NULL CHECK — Missing indicators")
        logger.info("=" * 60)
        
        null_query = text("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) - COUNT(hurst_exponent) as null_hurst,
                COUNT(*) - COUNT(ou_deviation) as null_ou,
                COUNT(*) - COUNT(regime) as null_regime,
                COUNT(*) - COUNT(rsi_14) as null_rsi,
                COUNT(*) - COUNT(ema_21) as null_ema21,
                COUNT(*) - COUNT(ema_50) as null_ema50,
                COUNT(*) - COUNT(macd) as null_macd,
                COUNT(*) - COUNT(bollinger_upper) as null_bb,
                COUNT(*) - COUNT(atr_14) as null_atr,
                COUNT(*) - COUNT(returns) as null_returns,
                COUNT(*) - COUNT(momentum_5) as null_momentum,
                COUNT(*) - COUNT(volatility_realized) as null_vol,
                COUNT(*) - COUNT(price_position) as null_pp
            FROM candles WHERE symbol = 'R_100'
        """)
        r = db.execute(null_query).fetchone()
        
        print(f"\n{'Indicator':<25} {'NULL Count':>10} {'% Missing':>10}")
        print("-" * 47)
        indicators = [
            ('hurst_exponent', r.null_hurst),
            ('ou_deviation', r.null_ou),
            ('regime', r.null_regime),
            ('rsi_14', r.null_rsi),
            ('ema_21', r.null_ema21),
            ('ema_50', r.null_ema50),
            ('macd', r.null_macd),
            ('bollinger_upper', r.null_bb),
            ('atr_14', r.null_atr),
            ('returns', r.null_returns),
            ('momentum_5', r.null_momentum),
            ('volatility_realized', r.null_vol),
            ('price_position', r.null_pp),
        ]
        for name, null_count in indicators:
            pct = (null_count / r.total * 100) if r.total > 0 else 0
            status = "✅" if pct < 5 else "⚠️" if pct < 50 else "❌"
            print(f"{status} {name:<23} {null_count:>10} {pct:>9.1f}%")
        print(f"\nTotal candles: {r.total}")

        # ============================================================
        # 2. FLAT LINE CHECK — Per-day variance of each indicator
        # ============================================================
        logger.info("\n" + "=" * 60)
        logger.info("2️⃣  FLAT LINE CHECK — Days with zero variance (constant value)")
        logger.info("=" * 60)
        
        flat_query = text("""
            SELECT 
                DATE(open_time AT TIME ZONE 'America/Bogota') as d,
                COUNT(*) as cnt,
                STDDEV(hurst_exponent) as std_hurst,
                STDDEV(ou_deviation) as std_ou,
                STDDEV(rsi_14) as std_rsi,
                STDDEV(macd) as std_macd,
                STDDEV(bollinger_upper) as std_bb,
                AVG(hurst_exponent) as avg_hurst,
                COUNT(hurst_exponent) as cnt_hurst
            FROM candles
            WHERE symbol = 'R_100'
            GROUP BY d
            HAVING COUNT(*) >= 100
            ORDER BY d DESC
        """)
        rows = db.execute(flat_query).fetchall()
        
        print(f"\n{'Date':<12} {'Candles':>7} {'Hurst(n)':>8} {'σ(H)':>8} {'σ(RSI)':>8} {'σ(MACD)':>10} {'σ(BB)':>8} {'Status':<10}")
        print("-" * 80)
        
        bad_dates = []
        for row in rows:
            std_h = float(row.std_hurst) if row.std_hurst else 0
            std_rsi = float(row.std_rsi) if row.std_rsi else 0
            std_macd = float(row.std_macd) if row.std_macd else 0
            std_bb = float(row.std_bb) if row.std_bb else 0
            cnt_h = int(row.cnt_hurst) if row.cnt_hurst else 0
            avg_h = float(row.avg_hurst) if row.avg_hurst else 0
            
            # Detect problems
            problems = []
            if cnt_h == 0:
                problems.append("NO_HURST")
            elif std_h < 0.001 and cnt_h > 50:
                problems.append("FLAT_HURST")
            if std_rsi < 0.01 and std_rsi is not None:
                problems.append("FLAT_RSI")
            
            status = ", ".join(problems) if problems else "OK"
            icon = "❌" if problems else "✅"
            
            if problems:
                bad_dates.append(str(row.d))
            
            print(f"{icon} {str(row.d):<10} {row.cnt:>7} {cnt_h:>8} {std_h:>8.4f} {std_rsi:>8.2f} {std_macd:>10.4f} {std_bb:>8.2f} {status:<10}")
        
        # ============================================================
        # 3. SAMPLE CHECK — Show actual values for a few candles
        # ============================================================
        logger.info("\n" + "=" * 60)
        logger.info("3️⃣  SAMPLE CHECK — Latest 10 candles with indicators")
        logger.info("=" * 60)
        
        sample_query = text("""
            SELECT open_time, close, hurst_exponent, ou_deviation, regime,
                   rsi_14, ema_21, macd, bollinger_upper, atr_14
            FROM candles
            WHERE symbol = 'R_100' AND hurst_exponent IS NOT NULL
            ORDER BY open_time DESC
            LIMIT 10
        """)
        samples = db.execute(sample_query).fetchall()
        
        print(f"\n{'Time':<22} {'Close':>10} {'Hurst':>7} {'OU':>8} {'Regime':<12} {'RSI':>6} {'MACD':>8}")
        print("-" * 80)
        for s in samples:
            print(f"{str(s.open_time):<22} {float(s.close):>10.2f} {float(s.hurst_exponent or 0):>7.4f} {float(s.ou_deviation or 0):>8.2f} {(s.regime or 'N/A'):<12} {float(s.rsi_14 or 0):>6.1f} {float(s.macd or 0):>8.4f}")
        
        # ============================================================
        # 4. SUMMARY
        # ============================================================
        logger.info("\n" + "=" * 60)
        logger.info("4️⃣  SUMMARY")
        logger.info("=" * 60)
        
        if bad_dates:
            print(f"\n⚠️  Found {len(bad_dates)} problematic dates:")
            for d in bad_dates[:10]:
                print(f"   - {d}")
            if len(bad_dates) > 10:
                print(f"   ... and {len(bad_dates) - 10} more")
        else:
            print("\n✅ All dates look healthy!")
            
    except Exception as e:
        logger.error(f"❌ Validation error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    validate_indicators()
