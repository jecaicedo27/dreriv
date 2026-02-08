---
name: pgvector-pattern-matching
description: "PostgreSQL pgvector extension for trading pattern similarity search. Use when implementing vector embeddings of candlestick patterns, building HNSW indexes for fast similarity search, implementing temporal decay on pattern quality, regime-aware filtering, or building feedback loops that improve pattern quality scores over time."
---

# pgvector Pattern Matching for Trading

## Overview

Implements a pattern recognition system using PostgreSQL's pgvector extension to find historically similar market conditions and predict outcomes. Covers vectorization of candlestick data, HNSW indexing, temporal decay, regime-aware filtering, and feedback loops.

## When to Use This Skill

- Creating vector embeddings from candlestick/OHLC data
- Building pgvector tables with HNSW indexes
- Querying for similar historical patterns
- Implementing temporal decay (recent patterns > old patterns)
- Filtering patterns by market regime
- Building feedback loops that update pattern quality scores

## Do Not Use This Skill When

- Working with non-time-series data
- Building general-purpose vector search (RAG, embeddings for text)
- Using a different vector database (Pinecone, Weaviate, etc.)

## pgvector Setup

```sql
-- Install extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Verify
SELECT * FROM pg_extension WHERE extname IN ('vector', 'timescaledb');
```

**Docker image:** `timescale/timescaledb:latest-pg16` includes TimescaleDB. Install pgvector separately:
```dockerfile
RUN apt-get update && apt-get install -y postgresql-16-pgvector
```

Or use `timescale/timescaledb-ha:pg16` which includes both.

## Vectorization: Candlestick to Vector

### Feature Engineering (12 features per candle)

```python
import numpy as np

def vectorize_candles(candles: list[dict], window: int = 30) -> np.ndarray:
    """
    Convert last N candles into a flat vector for pgvector storage.
    
    Features per candle (12):
    0: open_norm      - Normalized open price
    1: high_norm      - Normalized high
    2: low_norm       - Normalized low  
    3: close_norm     - Normalized close
    4: rsi_norm       - RSI normalized to [0,1]
    5: atr_norm       - ATR normalized by z-score
    6: returns        - (close - prev_close) / prev_close
    7: momentum_5     - 5-period momentum
    8: vol_realized   - Realized volatility (std of returns, 20-period)
    9: volume_delta   - tick_count / avg(tick_count, 20)
    10: price_pos     - (close - low_20) / (high_20 - low_20)
    11: regime_enc    - Regime encoded: trending_up=1, down=-1, ranging=0, volatile=0.5
    
    Total: 30 candles × 12 features = 360 dimensions
    """
    if len(candles) < window:
        return None
    
    recent = candles[-window:]
    
    # Z-score normalization for price (more robust than min-max)
    prices_100 = [c['close'] for c in candles[-100:]]  # Longer window for stats
    price_mean = np.mean(prices_100)
    price_std = np.std(prices_100) or 1.0
    
    features = []
    for c in recent:
        f = [
            (c['open'] - price_mean) / price_std,
            (c['high'] - price_mean) / price_std,
            (c['low'] - price_mean) / price_std,
            (c['close'] - price_mean) / price_std,
            c.get('rsi_14', 50) / 100.0,
            (c.get('atr_14', 0) - np.mean([x.get('atr_14', 0) for x in candles[-100:]])) / (np.std([x.get('atr_14', 0) for x in candles[-100:]]) or 1.0),
            c.get('returns', 0),
            c.get('momentum_5', 0),
            c.get('volatility_realized', 0),
            c.get('volume_delta', 1.0),
            c.get('price_position', 0.5),
            encode_regime(c.get('regime', 'unknown'))
        ]
        features.extend(f)
    
    return np.array(features, dtype=np.float32)

def encode_regime(regime: str) -> float:
    return {
        'trending_up': 1.0,
        'trending_down': -1.0,
        'ranging_tight': 0.0,
        'ranging_wide': 0.2,
        'volatile_expansion': 0.5,
        'unknown': 0.0
    }.get(regime, 0.0)
```

### Why Z-Score Over Min-Max

- Min-max is distorted by outliers (1 spike candle ruins the entire normalization)
- Z-score preserves relative scale between features
- Z-score is translation-invariant (same pattern at different price levels matches)
- Use 100-candle window for statistics (not the 30-candle pattern window)

## HNSW Index Configuration

```sql
-- For 360-dimensional vectors
CREATE INDEX idx_pattern_vector ON candle_patterns 
    USING hnsw (pattern_vector vector_cosine_ops)
    WITH (m = 24, ef_construction = 128);
```

### Parameter Tuning Guide

| Dimensions | m | ef_construction | Recall | Build Time |
|-----------|---|-----------------|--------|------------|
| 140 | 16 | 64 | ~95% | Fast |
| 360 | 24 | 128 | ~97% | Medium |
| 360 | 32 | 200 | ~99% | Slow |

- **m**: Connections per node. Higher = better recall but more memory. 24 is sweet spot for 360d.
- **ef_construction**: Build-time search depth. 128 is good balance for 360d.
- At query time, set `SET hnsw.ef_search = 100;` for production (default 40 is too low).

### Distance Functions

```sql
-- Cosine similarity (RECOMMENDED for normalized features)
SELECT 1 - (pattern_vector <=> query_vector) as similarity FROM ...

-- L2 distance (alternative — good if features aren't normalized)
SELECT pattern_vector <-> query_vector as distance FROM ...

-- Inner product (fastest but requires unit vectors)
SELECT pattern_vector <#> query_vector as neg_inner_product FROM ...
```

**Use cosine** for this use case — it handles scale differences between features naturally.

## Query Pattern: Temporal Decay + Regime Filter

```sql
-- Production query with composite scoring
SET hnsw.ef_search = 100;

SELECT 
    cp.id,
    cp.pattern_type,
    cp.outcome_direction,
    cp.outcome_pips,
    cp.outcome_max_adverse,
    cp.pattern_quality_score,
    cp.regime_at_formation,
    cp.created_at,
    
    -- Raw cosine similarity [0-1]
    1 - (cp.pattern_vector <=> $1::vector) as raw_similarity,
    
    -- Temporal decay: exp(-lambda * days_old)
    -- lambda=0.01 → half-life ~69 days
    EXP(-0.01 * EXTRACT(EPOCH FROM (NOW() - cp.created_at)) / 86400.0) as temporal_decay,
    
    -- Composite score = similarity × decay × quality
    (1 - (cp.pattern_vector <=> $1::vector))
    * EXP(-0.01 * EXTRACT(EPOCH FROM (NOW() - cp.created_at)) / 86400.0)
    * COALESCE(cp.pattern_quality_score, 0.5)
    as composite_score

FROM candle_patterns cp
WHERE cp.symbol = $2
  AND cp.timeframe = $3
  AND cp.outcome_direction IS NOT NULL
  AND cp.regime_at_formation IN ($4, 'ranging_tight')  -- Current regime + neutral
  AND (cp.pattern_quality_score > 0.3 OR cp.created_at > NOW() - INTERVAL '14 days')
ORDER BY composite_score DESC
LIMIT 15;
```

## Feedback Loop: Updating Quality Scores

```python
async def update_pattern_quality(self, trade_result: dict):
    """
    After a trade closes, update quality scores of patterns that were used.
    Uses EMA (exponential moving average) for smooth updates.
    """
    pattern_ids = trade_result['matched_pattern_ids']
    was_winner = trade_result['profit_loss'] > 0
    
    for pid in pattern_ids:
        # EMA update: score = score * alpha + new_value * (1 - alpha)
        alpha = 0.9
        new_value = 1.0 if was_winner else 0.0
        
        await self.db.execute("""
            UPDATE candle_patterns 
            SET pattern_quality_score = pattern_quality_score * $1 + $2 * (1 - $1),
                times_matched = times_matched + 1,
                times_correct = times_correct + CASE WHEN $3 THEN 1 ELSE 0 END,
                last_used_at = NOW()
            WHERE id = $4
        """, alpha, new_value, was_winner, pid)
```

## Performance Tips

1. **Batch inserts**: Insert patterns in batches of 100+ for better index build performance
2. **Partial index**: If most queries filter by symbol, create partial indexes per symbol
3. **Vacuuming**: Run `VACUUM ANALYZE candle_patterns;` weekly — HNSW needs it
4. **Memory**: Set `maintenance_work_mem = 512MB` minimum for HNSW builds
5. **Connection pooling**: Use pgbouncer — pgvector queries hold connections longer
