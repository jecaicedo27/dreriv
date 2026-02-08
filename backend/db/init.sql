-- ============================================
-- BOT DERIV V2 - DATABASE INITIALIZATION
-- ============================================
-- Enable required extensions

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- Drop existing tables if any (for clean setup)
-- ============================================

DROP TABLE IF EXISTS ab_test_results CASCADE;
DROP TABLE IF EXISTS spike_events CASCADE;
DROP TABLE IF EXISTS regime_history CASCADE;
DROP TABLE IF EXISTS groq_decisions_log CASCADE;
DROP TABLE IF EXISTS bot_state CASCADE;
DROP TABLE IF EXISTS trades CASCADE;
DROP TABLE IF NOT EXISTS candle_patterns CASCADE;
DROP TABLE IF EXISTS candles CASCADE;
DROP TABLE IF EXISTS raw_ticks CASCADE;

-- ============================================
-- 1. RAW_TICKS (TimescaleDB Hypertable)
-- ============================================

CREATE TABLE raw_ticks (
    id BIGSERIAL,
    symbol VARCHAR(20) NOT NULL,
    epoch BIGINT NOT NULL,
    quote DECIMAL(18, 8) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, epoch)
);

-- Convert to hypertable
SELECT create_hypertable('raw_ticks', 'epoch', chunk_time_interval => 86400000000::BIGINT);

-- Indexes
CREATE INDEX idx_raw_ticks_symbol_epoch ON raw_ticks (symbol, epoch DESC);

-- ============================================
-- 2. CANDLES (TimescaleDB Hypertable)
-- ============================================

CREATE TABLE candles (
    id BIGSERIAL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,  -- '1m', '5m', '15m', '1h'
    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,
    open DECIMAL(18, 8) NOT NULL,
    high DECIMAL(18, 8) NOT NULL,
    low DECIMAL(18, 8) NOT NULL,
    close DECIMAL(18, 8) NOT NULL,
    volume DECIMAL(18, 4) DEFAULT 0,
    
    -- Technical Indicators
    ema_9 DECIMAL(18, 8),
    ema_21 DECIMAL(18, 8),
    ema_50 DECIMAL(18, 8),
    rsi_14 DECIMAL(8, 4),
    atr_14 DECIMAL(18, 8),
    bollinger_upper DECIMAL(18, 8),
    bollinger_middle DECIMAL(18, 8),
    bollinger_lower DECIMAL(18, 8),
    macd DECIMAL(18, 8),
    macd_signal DECIMAL(18, 8),
    macd_histogram DECIMAL(18, 8),
    
    -- Advanced Features for pgvector
    returns DECIMAL(12, 8),
    log_returns DECIMAL(12, 8),
    momentum_5 DECIMAL(12, 8),
    momentum_10 DECIMAL(12, 8),
    volatility_realized DECIMAL(12, 8),
    volume_delta DECIMAL(18, 4),
    price_position DECIMAL(8, 6),  -- (close - low) / (high - low)
    
    -- Market Structure (SMC)
    is_order_block BOOLEAN DEFAULT FALSE,
    ob_type VARCHAR(10),  -- 'BULL' or 'BEAR'
    is_fvg BOOLEAN DEFAULT FALSE,
    fvg_type VARCHAR(10),
    bos BOOLEAN DEFAULT FALSE,  -- Break of Structure
    choch BOOLEAN DEFAULT FALSE,  -- Change of Character
    
    -- Statistical Analysis
    hurst_exponent DECIMAL(8, 6),
    ou_deviation DECIMAL(12, 8),  -- Ornstein-Uhlenbeck deviation from mean
    garch_volatility_forecast DECIMAL(12, 8),
    regime VARCHAR(30),  -- HMM regime
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, timeframe, open_time)
);

-- Convert to hypertable
SELECT create_hypertable('candles', 'open_time', chunk_time_interval => INTERVAL '1 day');

-- Indexes
CREATE INDEX idx_candles_symbol_timeframe ON candles (symbol, timeframe, open_time DESC);
CREATE INDEX idx_candles_regime ON candles (regime) WHERE regime IS NOT NULL;

-- ============================================
-- 3. CANDLE_PATTERNS (pgvector similarity search)
-- ============================================

CREATE TABLE candle_patterns (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    
    -- Vector embedding (360 dimensions: 12 features × 30 candles)
    embedding vector(360) NOT NULL,
    
    -- Pattern metadata
    regime VARCHAR(30),
    pattern_length INT DEFAULT 30,
    
    -- Outcome tracking
    outcome VARCHAR(10),  -- 'WIN', 'LOSS', null if pending
    future_move_pct DECIMAL(8, 4),
    quality_score DECIMAL(8, 6) DEFAULT 0.5,  -- Updated via feedback loop
    
    -- Decay tracking
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_matched_at TIMESTAMPTZ
);

-- pgvector HNSW index (optimized for fast similarity search)
CREATE INDEX idx_candle_patterns_embedding ON candle_patterns 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Other indexes
CREATE INDEX idx_candle_patterns_symbol_timeframe ON candle_patterns (symbol, timeframe);
CREATE INDEX idx_candle_patterns_regime ON candle_patterns (regime) WHERE regime IS NOT NULL;
CREATE INDEX idx_candle_patterns_quality ON candle_patterns (quality_score DESC);

-- ============================================
-- 4. TRADES
-- ============================================

CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(20) NOT NULL,
    contract_type VARCHAR(20) NOT NULL,  -- 'CALL', 'PUT', 'DIGITEVEN', etc.
    direction VARCHAR(10) NOT NULL,  -- 'RISE', 'FALL', 'EVEN', 'ODD'
    
    -- Entry
    entry_time TIMESTAMPTZ NOT NULL,
    entry_price DECIMAL(18, 8) NOT NULL,
    stake DECIMAL(10, 2) NOT NULL,
    duration_seconds INT NOT NULL,
    
    -- Exit
    exit_time TIMESTAMPTZ,
    exit_price DECIMAL(18, 8),
    profit_loss DECIMAL(10, 2),
    outcome VARCHAR(10),  -- 'WIN', 'LOSS', 'PENDING'
    
    -- Decision layers (A/B testing)
    layer1_signal VARCHAR(20),  -- Statistical model signal
    layer1_confidence DECIMAL(6, 4),
    layer2_similar_patterns INT,  -- Count of similar patterns found
    layer2_weighted_winrate DECIMAL(6, 4),
    layer3_groq_used BOOLEAN DEFAULT FALSE,
    layer3_groq_confidence DECIMAL(6, 4),
    layer3_groq_reasoning TEXT,
    
    -- Final decision
    final_confidence DECIMAL(6, 4) NOT NULL,
    concordance_score DECIMAL(6, 4),  -- How much layers agree
    
    -- Risk management applied
    kelly_fraction DECIMAL(6, 4),
    drawdown_multiplier DECIMAL(6, 4) DEFAULT 1.0,
    
    -- Contract reference
    deriv_contract_id VARCHAR(50),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_trades_symbol ON trades (symbol);
CREATE INDEX idx_trades_outcome ON trades (outcome);
CREATE INDEX idx_trades_entry_time ON trades (entry_time DESC);
CREATE INDEX idx_trades_pending ON trades (outcome) WHERE outcome = 'PENDING';

-- ============================================
-- 5. BOT_STATE (singleton table for state tracking)
-- ============================================

CREATE TABLE bot_state (
    id INT PRIMARY KEY DEFAULT 1,
    
    -- Account
    balance DECIMAL(12, 2) NOT NULL DEFAULT 0,
    initial_balance DECIMAL(12, 2) NOT NULL,
    peak_balance DECIMAL(12, 2) NOT NULL DEFAULT 0,
    current_drawdown_pct DECIMAL(8, 4) DEFAULT 0,
    
    -- Trading state
    is_trading_enabled BOOLEAN DEFAULT TRUE,
    trades_today INT DEFAULT 0,
    losses_consecutive INT DEFAULT 0,
    wins_today INT DEFAULT 0,
    losses_today INT DEFAULT 0,
    daily_pnl DECIMAL(10, 2) DEFAULT 0,
    
    -- Cooldown tracking
    cooldown_until TIMESTAMPTZ,
    cooldown_reason VARCHAR(100),
    
    -- Date tracking
    last_trade_date DATE,
    
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT single_row CHECK (id = 1)
);

-- Insert initial state
INSERT INTO bot_state (id, balance, initial_balance, peak_balance) 
VALUES (1, 0, 0, 0);

-- ============================================
-- 6. GROQ_DECISIONS_LOG
-- ============================================

CREATE TABLE groq_decisions_log (
    id BIGSERIAL PRIMARY KEY,
    trade_id UUID REFERENCES trades(id),
    
    -- Input sent to Groq
    layer1_signals JSONB NOT NULL,
    layer2_patterns JSONB NOT NULL,
    market_context JSONB NOT NULL,
    
    -- Groq response
    groq_raw_response TEXT NOT NULL,
    groq_parsed_decision JSONB,
    
    -- Quality metrics
    decision VARCHAR(20),  -- 'CALL', 'PUT', 'HOLD'
    confidence DECIMAL(6, 4),
    reasoning TEXT,
    counter_arguments TEXT,
    
    -- Meta-tracking
    was_correct BOOLEAN,  -- Updated after trade closes
    meta_confidence_score DECIMAL(6, 4) DEFAULT 0.5,  -- Running accuracy
    
    -- Performance
    response_time_ms INT,
    tokens_used INT,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_groq_log_trade ON groq_decisions_log (trade_id);
CREATE INDEX idx_groq_log_created ON groq_decisions_log (created_at DESC);

-- ============================================
-- 7. REGIME_HISTORY (HMM regime transitions)
-- ============================================

CREATE TABLE regime_history (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    
    regime VARCHAR(30) NOT NULL,  -- 'trending_up', 'trending_down', 'ranging_tight', 'volatile_expansion'
    regime_probability DECIMAL(6, 4),
    
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_minutes INT,
    
    -- Performance in this regime
    trades_count INT DEFAULT 0,
    wins_count INT DEFAULT 0,
    regime_winrate DECIMAL(6, 4),
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_regime_history_symbol ON regime_history (symbol, started_at DESC);
CREATE INDEX idx_regime_history_active ON regime_history (ended_at) WHERE ended_at IS NULL;

-- ============================================
-- 8. AB_TEST_RESULTS
-- ============================================

CREATE TABLE ab_test_results (
    id BIGSERIAL PRIMARY KEY,
    test_date DATE NOT NULL,
    
    -- Which layers enabled
    layer1_only_trades INT DEFAULT 0,
    layer1_only_wins INT DEFAULT 0,
    layer1_only_winrate DECIMAL(6, 4),
    
    layer12_trades INT DEFAULT 0,
    layer12_wins INT DEFAULT 0,
    layer12_winrate DECIMAL(6, 4),
    
    layer123_trades INT DEFAULT 0,
    layer123_wins INT DEFAULT 0,
    layer123_winrate DECIMAL(6, 4),
    
    -- Overall metrics
    total_trades INT DEFAULT 0,
    total_pnl DECIMAL(10, 2) DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(test_date)
);

-- ============================================
-- 9. SPIKE_EVENTS (for Crash/Boom tracking)
-- ============================================

CREATE TABLE spike_events (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,  -- e.g., 'CRASH_500', 'BOOM_1000'
    spike_time TIMESTAMPTZ NOT NULL,
    spike_type VARCHAR(10) NOT NULL,  -- 'CRASH' or 'BOOM'
    
    -- Spike characteristics
    ticks_since_last_spike INT,
    price_before DECIMAL(18, 8),
    price_after DECIMAL(18, 8),
    magnitude_pct DECIMAL(8, 4),
    
    -- Weibull parameters at the time
    weibull_shape DECIMAL(8, 6),
    weibull_scale DECIMAL(12, 4),
    predicted_hazard_rate DECIMAL(10, 8),
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_spike_events_symbol ON spike_events (symbol, spike_time DESC);
CREATE INDEX idx_spike_events_time ON spike_events (spike_time DESC);

-- ============================================
-- MATERIALIZED VIEWS (for performance)
-- ============================================

-- Daily performance summary
CREATE MATERIALIZED VIEW daily_performance AS
SELECT 
    DATE(entry_time) as trade_date,
    COUNT(*) as total_trades,
    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
    ROUND(100.0 * SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END)::DECIMAL / COUNT(*), 2) as winrate_pct,
    SUM(profit_loss) as daily_pnl,
    AVG(final_confidence) as avg_confidence
FROM trades
WHERE outcome IN ('WIN', 'LOSS')
GROUP BY DATE(entry_time)
ORDER BY trade_date DESC;

-- Index for materialized view
CREATE INDEX idx_daily_performance_date ON daily_performance (trade_date DESC);

-- ============================================
-- FUNCTIONS
-- ============================================

-- Function to update bot state after trade closes
CREATE OR REPLACE FUNCTION update_bot_state_after_trade()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.outcome IN ('WIN', 'LOSS') AND OLD.outcome = 'PENDING' THEN
        UPDATE bot_state SET
            balance = balance + NEW.profit_loss,
            peak_balance = GREATEST(peak_balance, balance + NEW.profit_loss),
            trades_today = trades_today + 1,
            wins_today = wins_today + CASE WHEN NEW.outcome = 'WIN' THEN 1 ELSE 0 END,
            losses_today = losses_today + CASE WHEN NEW.outcome = 'LOSS' THEN 1 ELSE 0 END,
            daily_pnl = daily_pnl + NEW.profit_loss,
            losses_consecutive = CASE 
                WHEN NEW.outcome = 'LOSS' THEN losses_consecutive + 1 
                ELSE 0 
            END,
            current_drawdown_pct = 100.0 * (peak_balance - (balance + NEW.profit_loss)) / peak_balance,
            updated_at = NOW()
        WHERE id = 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update bot state
CREATE TRIGGER trigger_update_bot_state
AFTER UPDATE OF outcome ON trades
FOR EACH ROW
EXECUTE FUNCTION update_bot_state_after_trade();

-- ============================================
-- GRANTS (if using specific roles)
-- ============================================

-- Grant permissions (uncomment if needed)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO deriv_bot;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO deriv_bot;

-- ============================================
-- SUCCESS MESSAGE
-- ============================================

DO $$
BEGIN
    RAISE NOTICE '✅ Database schema initialized successfully!';
    RAISE NOTICE '📊 Tables created: 9 + 1 materialized view';
    RAISE NOTICE '🔍 Indexes created for performance optimization';
    RAISE NOTICE '🎯 pgvector HNSW index configured for pattern matching';
    RAISE NOTICE '⏱️  TimescaleDB hypertables: raw_ticks, candles';
END $$;
