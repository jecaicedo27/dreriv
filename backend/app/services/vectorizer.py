"""
Vectorizer: Convert candlestick windows into 360-dimensional vectors for pgvector
"""
import numpy as np
from typing import List, Dict, Optional
from loguru import logger


def encode_regime(regime: str) -> float:
    """Encode market regime as a float value"""
    return {
        'trending_up': 1.0,
        'trending_down': -1.0,
        'trending': 0.8,          # Generic trending
        'ranging_tight': 0.0,
        'ranging_wide': 0.2,
        'mean_reverting': -0.5,
        'volatile_expansion': 0.5,
        'EXPANDING': 0.5,
        'NORMAL': 0.0,
        'CONTRACTING': -0.3,
    }.get(regime or '', 0.0)


def vectorize_candles(candles: List[Dict], window: int = 30) -> Optional[np.ndarray]:
    """
    Convert last N candles into a flat vector for pgvector storage.
    
    Features per candle (12):
    0: open_norm      - Z-score normalized open price
    1: high_norm      - Z-score normalized high
    2: low_norm       - Z-score normalized low  
    3: close_norm     - Z-score normalized close
    4: rsi_norm       - RSI normalized to [0,1]
    5: macd_norm      - MACD normalized by z-score
    6: returns        - (close - prev_close) / prev_close
    7: momentum_5     - 5-period momentum
    8: vol_realized   - Realized volatility
    9: bb_position    - Price position within Bollinger Bands [0,1]
    10: hurst         - Hurst exponent
    11: ou_deviation  - Ornstein-Uhlenbeck deviation
    
    Total: 30 candles × 12 features = 360 dimensions
    """
    if len(candles) < window:
        return None
    
    recent = candles[-window:]
    
    # Use longer window for normalization stats
    stats_window = candles[-min(100, len(candles)):]
    
    # Z-score normalization for price
    close_prices = [float(c['close']) for c in stats_window]
    price_mean = float(np.mean(close_prices))
    price_std = float(np.std(close_prices)) or 1.0
    
    # MACD normalization
    macd_values = [float(c.get('macd', 0) or 0) for c in stats_window]
    macd_mean = float(np.mean(macd_values))
    macd_std = float(np.std(macd_values)) or 1.0
    
    features = []
    for c in recent:
        f = [
            (float(c['open']) - price_mean) / price_std,              # 0: open_norm
            (float(c['high']) - price_mean) / price_std,              # 1: high_norm
            (float(c['low']) - price_mean) / price_std,               # 2: low_norm
            (float(c['close']) - price_mean) / price_std,             # 3: close_norm
            float(c.get('rsi_14') or 50) / 100.0,                    # 4: rsi_norm [0,1]
            (float(c.get('macd') or 0) - macd_mean) / macd_std,      # 5: macd_norm
            float(c.get('returns') or 0),                              # 6: returns
            float(c.get('momentum_5') or 0),                           # 7: momentum
            float(c.get('volatility_realized') or 0),                  # 8: volatility
            float(c.get('price_position') or 0.5),                     # 9: BB position
            float(c.get('hurst_exponent') or 0.5),                     # 10: hurst
            float(c.get('ou_deviation') or 0),                         # 11: O-U deviation
        ]
        features.extend(f)
    
    vec = np.array(features, dtype=np.float32)
    
    # Replace NaN/Inf with 0
    vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)
    
    return vec


def populate_patterns_from_history(db, symbol: str = 'R_100', batch_size: int = 100):
    """
    Generate pattern vectors from all historical candles and store in candle_patterns.
    For each position in history (starting from candle 30), create a vector from the
    previous 30 candles and record what happened next (outcome).
    """
    from sqlalchemy import text
    
    logger.info(f"🔄 Starting pattern population for {symbol}...")
    
    # Get all candles ordered by time
    result = db.execute(text("""
        SELECT id, open_time, open, high, low, close, 
               rsi_14, macd, macd_signal, macd_histogram,
               returns, momentum_5, volatility_realized,
               price_position, hurst_exponent, ou_deviation,
               regime, bollinger_upper, bollinger_lower
        FROM candles 
        WHERE symbol = :symbol 
        ORDER BY open_time ASC
    """), {"symbol": symbol}).fetchall()
    
    candles = [dict(row._mapping) for row in result]
    total = len(candles)
    logger.info(f"📊 Found {total} candles for {symbol}")
    
    if total < 35:  # Need at least 30 for pattern + 5 for outcome
        logger.warning("❌ Not enough candles for pattern generation")
        return 0
    
    # Check existing patterns to avoid duplicates
    existing = db.execute(text(
        "SELECT COUNT(*) FROM candle_patterns WHERE symbol = :symbol"
    ), {"symbol": symbol}).scalar()
    
    if existing > 0:
        logger.info(f"⚠️ Found {existing} existing patterns. Clearing for fresh population...")
        db.execute(text("DELETE FROM candle_patterns WHERE symbol = :symbol"), {"symbol": symbol})
        db.commit()
    
    patterns_created = 0
    batch_values = []
    
    # Slide window: for each position from 30 to (total - 5)
    for i in range(30, total - 5):
        # Get window of 30 candles ending at position i
        window = candles[i-30:i]
        current_candle = candles[i]
        
        # Vectorize
        vec = vectorize_candles(window, window=30)
        if vec is None:
            continue
        
        # Calculate outcome (what happened in next 5 candles)
        future_candles = candles[i:i+5]
        price_now = float(current_candle['close'])
        price_5min = float(future_candles[-1]['close'])
        price_change = price_5min - price_now
        
        # Determine direction
        outcome_direction = 'CALL' if price_change > 0 else 'PUT'
        outcome_pips = abs(price_change)
        
        # 15-min outcome if available
        outcome_15min = None
        if i + 15 < total:
            outcome_15min = float(candles[i + 15]['close']) - price_now
        
        batch_values.append({
            "symbol": symbol,
            "timeframe": "1m",
            "pattern_vector": f"[{','.join(str(x) for x in vec)}]",
            "pattern_time": current_candle['open_time'],
            "outcome_direction": outcome_direction,
            "outcome_pips": outcome_pips,
            "outcome_5min": price_change,
            "outcome_15min": outcome_15min,
            "regime_at_formation": current_candle.get('regime') or 'unknown',
            "hurst_at_formation": current_candle.get('hurst_exponent'),
            "rsi_at_formation": current_candle.get('rsi_14'),
        })
        patterns_created += 1
        
        # Batch insert
        if len(batch_values) >= batch_size:
            _insert_batch(db, batch_values)
            batch_values = []
            if patterns_created % 1000 == 0:
                logger.info(f"  📝 {patterns_created}/{total - 35} patterns created...")
    
    # Insert remaining
    if batch_values:
        _insert_batch(db, batch_values)
    
    db.commit()
    logger.info(f"✅ Created {patterns_created} patterns from {total} candles")
    return patterns_created


def _insert_batch(db, batch: List[Dict]):
    """Insert a batch of patterns"""
    from sqlalchemy import text
    
    for p in batch:
        db.execute(text("""
            INSERT INTO candle_patterns 
            (symbol, timeframe, pattern_vector, pattern_time, 
             outcome_direction, outcome_pips, outcome_5min, outcome_15min,
             regime_at_formation, hurst_at_formation, rsi_at_formation)
            VALUES 
            (:symbol, :timeframe, CAST(:pattern_vector AS vector), :pattern_time,
             :outcome_direction, :outcome_pips, :outcome_5min, :outcome_15min,
             :regime_at_formation, :hurst_at_formation, :rsi_at_formation)
        """), p)


def find_similar_patterns(
    db, 
    query_vector: np.ndarray, 
    symbol: str = 'R_100',
    regime: str = None,
    limit: int = 10,
    min_similarity: float = 0.7
) -> List[Dict]:
    """
    Find historically similar patterns using pgvector cosine similarity
    """
    from sqlalchemy import text
    
    vec_str = f"[{','.join(str(x) for x in query_vector)}]"
    
    # Build query with optional regime filter
    regime_filter = ""
    params = {"vec": vec_str, "symbol": symbol, "limit": limit, "min_sim": min_similarity}
    
    if regime:
        regime_filter = "AND regime_at_formation = :regime"
        params["regime"] = regime
    
    # Set HNSW search params for better recall
    db.execute(text("SET hnsw.ef_search = 100;"))
    
    result = db.execute(text(f"""
        SELECT 
            id,
            pattern_time,
            outcome_direction,
            outcome_pips,
            outcome_5min,
            outcome_15min,
            regime_at_formation,
            hurst_at_formation,
            rsi_at_formation,
            pattern_quality_score,
            1 - (pattern_vector <=> CAST(:vec AS vector)) as similarity
        FROM candle_patterns
        WHERE symbol = :symbol
          {regime_filter}
          AND outcome_direction IS NOT NULL
          AND 1 - (pattern_vector <=> CAST(:vec AS vector)) >= :min_sim
        ORDER BY pattern_vector <=> CAST(:vec AS vector) ASC
        LIMIT :limit
    """), params).fetchall()
    
    matches = []
    for row in result:
        matches.append({
            "id": row.id,
            "pattern_time": str(row.pattern_time),
            "outcome_direction": row.outcome_direction,
            "outcome_pips": round(float(row.outcome_pips or 0), 2),
            "outcome_5min": round(float(row.outcome_5min or 0), 2),
            "outcome_15min": round(float(row.outcome_15min or 0), 4) if row.outcome_15min else None,
            "regime": row.regime_at_formation,
            "hurst": round(float(row.hurst_at_formation or 0), 3),
            "rsi": round(float(row.rsi_at_formation or 0), 1),
            "quality_score": round(float(row.pattern_quality_score or 0.5), 2),
            "similarity": round(float(row.similarity), 4),
        })
    
    return matches
