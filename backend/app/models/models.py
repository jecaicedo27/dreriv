"""
SQLAlchemy Models for Bot Deriv V2
"""
from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, Text, Date, ForeignKey, BigInteger, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from datetime import datetime
import uuid

from app.core.database import Base


class RawTick(Base):
    """Raw tick data from Deriv WebSocket"""
    __tablename__ = "raw_ticks"
    
    id = Column(BigInteger, primary_key=True)
    symbol = Column(String(20), nullable=False)
    epoch = Column(BigInteger, nullable=False)
    quote = Column(Numeric(18, 8), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Candle(Base):
    """OHLC candles with technical indicators"""
    __tablename__ = "candles"
    
    id = Column(BigInteger, primary_key=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(5), nullable=False)
    open_time = Column(DateTime(timezone=True), nullable=False)
    close_time = Column(DateTime(timezone=True), nullable=False)
    
    # OHLCV
    open = Column(Numeric(18, 8), nullable=False)
    high = Column(Numeric(18, 8), nullable=False)
    low = Column(Numeric(18, 8), nullable=False)
    close = Column(Numeric(18, 8), nullable=False)
    volume = Column(Numeric(18, 4), default=0)
    
    # Technical Indicators
    ema_9 = Column(Numeric(18, 8))
    ema_21 = Column(Numeric(18, 8))
    ema_50 = Column(Numeric(18, 8))
    rsi_14 = Column(Numeric(8, 4))
    stoch_rsi = Column(Numeric(8, 4))
    atr_14 = Column(Numeric(18, 8))
    adx_14 = Column(Numeric(8, 4))
    plus_di = Column(Numeric(8, 4))
    minus_di = Column(Numeric(8, 4))
    bollinger_upper = Column(Numeric(18, 8))
    bollinger_middle = Column(Numeric(18, 8))
    bollinger_lower = Column(Numeric(18, 8))
    macd = Column(Numeric(18, 8))
    macd_signal = Column(Numeric(18, 8))
    macd_histogram = Column(Numeric(18, 8))
    
    # Advanced Features
    returns = Column(Numeric(12, 8))
    log_returns = Column(Numeric(12, 8))
    momentum_5 = Column(Numeric(12, 8))
    momentum_10 = Column(Numeric(12, 8))
    volatility_realized = Column(Numeric(12, 8))
    volume_delta = Column(Numeric(18, 4))
    price_position = Column(Numeric(8, 6))
    
    # Market Structure
    is_order_block = Column(Boolean, default=False)
    ob_type = Column(String(10))
    is_fvg = Column(Boolean, default=False)
    fvg_type = Column(String(10))
    bos = Column(Boolean, default=False)
    choch = Column(Boolean, default=False)
    
    # Statistical Analysis
    hurst_exponent = Column(Numeric(8, 6))
    hurst_fast = Column(Numeric(8, 6))  # Variance Ratio fast Hurst
    ou_deviation = Column(Numeric(12, 8))
    garch_volatility_forecast = Column(Numeric(12, 8))
    regime = Column(String(30))
    
    # Adaptive Trend Flow (ATF)
    atf_basis = Column(Numeric(12, 8))
    atf_upper = Column(Numeric(12, 8))
    atf_lower = Column(Numeric(12, 8))
    atf_trend = Column(Integer, default=0)  # +1=bullish, -1=bearish, 0=neutral
    atf_slope = Column(Numeric(12, 8))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Trade(Base):
    """Executed trades"""
    __tablename__ = "trades"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False)
    contract_type = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    
    # Entry
    entry_time = Column(DateTime(timezone=True), nullable=False)
    entry_price = Column(Numeric(18, 8), nullable=False)
    stake = Column(Numeric(10, 2), nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    
    # Exit
    exit_time = Column(DateTime(timezone=True))
    exit_price = Column(Numeric(18, 8))
    profit_loss = Column(Numeric(10, 2))
    outcome = Column(String(10))  # WIN, LOSS, PENDING
    
    # Decision layers
    layer1_signal = Column(String(20))
    layer1_confidence = Column(Numeric(6, 4))
    layer2_similar_patterns = Column(Integer)
    layer2_weighted_winrate = Column(Numeric(6, 4))
    layer3_groq_used = Column(Boolean, default=False)
    layer3_groq_confidence = Column(Numeric(6, 4))
    layer3_groq_reasoning = Column(Text)
    
    # Final decision
    final_confidence = Column(Numeric(6, 4), nullable=False)
    concordance_score = Column(Numeric(6, 4))
    
    # Risk management
    kelly_fraction = Column(Numeric(6, 4))
    drawdown_multiplier = Column(Numeric(6, 4), default=1.0)
    hurst_at_entry = Column(Numeric(6, 4))
    
    # Deriv contract reference
    deriv_contract_id = Column(String(50))
    
    # Engine that produced this trade
    engine_name = Column(String(50))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BotState(Base):
    """Bot state tracking (singleton)"""
    __tablename__ = "bot_state"
    
    id = Column(Integer, primary_key=True, default=1)
    
    # Account
    balance = Column(Numeric(12, 2), nullable=False, default=0)
    initial_balance = Column(Numeric(12, 2), nullable=False)
    peak_balance = Column(Numeric(12, 2), nullable=False, default=0)
    current_drawdown_pct = Column(Numeric(8, 4), default=0)
    
    # Trading state
    is_trading_enabled = Column(Boolean, default=True)
    trades_today = Column(Integer, default=0)
    losses_consecutive = Column(Integer, default=0)
    wins_today = Column(Integer, default=0)
    losses_today = Column(Integer, default=0)
    daily_pnl = Column(Numeric(10, 2), default=0)
    
    # Cooldown
    cooldown_until = Column(DateTime(timezone=True))
    cooldown_reason = Column(String(100))
    
    # Date tracking
    last_trade_date = Column(Date)
    
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AnalysisHistory(Base):
    """Historical analysis metrics for chart visualization"""
    __tablename__ = "analysis_history"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    symbol = Column(String(50), nullable=False, default='R_100', index=True)
    
    # Hurst metrics
    hurst_value = Column(Numeric(6, 4))
    hurst_regime = Column(String(50))
    
    # O-U metrics
    ou_signal = Column(String(10))
    ou_deviation = Column(Numeric(10, 4))
    ou_confidence = Column(Numeric(5, 4))
    ou_theta = Column(Numeric(10, 6))
    ou_half_life = Column(Numeric(10, 2))
    
    # GARCH metrics
    garch_regime = Column(String(50))
    garch_current_vol = Column(Numeric(10, 6))
    garch_forecast_vol = Column(Numeric(10, 6))
    garch_stake_multiplier = Column(Numeric(5, 2))
    
    # Final signal
    final_signal = Column(String(10))
    final_confidence = Column(Numeric(5, 4))
    contract_type = Column(String(50))
    duration = Column(Integer)
    
    # Price context
    current_price = Column(Numeric(12, 2))
    
    # Technical indicators
    rsi_14 = Column(Numeric(6, 2))
    ema_9 = Column(Numeric(12, 2))
    ema_21 = Column(Numeric(12, 2))
    macd = Column(Numeric(12, 6))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Additional models (simplified for now)
class GroqDecisionLog(Base):
    """Groq AI decision logging"""
    __tablename__ = "groq_decisions_log"
    
    id = Column(BigInteger, primary_key=True)
    trade_id = Column(UUID(as_uuid=True), ForeignKey('trades.id'))
    layer1_signals = Column(JSONB, nullable=False)
    layer2_patterns = Column(JSONB, nullable=False)
    market_context = Column(JSONB, nullable=False)
    groq_raw_response = Column(Text, nullable=False)
    groq_parsed_decision = Column(JSONB)
    decision = Column(String(20))
    confidence = Column(Numeric(6, 4))
    reasoning = Column(Text)
    counter_arguments = Column(Text)
    was_correct = Column(Boolean)
    meta_confidence_score = Column(Numeric(6, 4), default=0.5)
    response_time_ms = Column(Integer)
    tokens_used = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DecisionComparison(Base):
    """Track L1 vs Groq decisions and hypothetical outcomes"""
    __tablename__ = "decision_comparisons"
    
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    entry_price = Column(Numeric(12, 5))
    exit_price = Column(Numeric(12, 5))
    duration = Column(Integer, default=300)
    l1_signal = Column(String(10), nullable=False)
    l1_confidence = Column(Numeric(6, 4))
    groq_signal = Column(String(10), nullable=False)
    groq_confidence = Column(Numeric(6, 4))
    l1_hypothetical = Column(String(10))  # WIN/LOSS
    groq_result = Column(String(10))      # WIN/LOSS/SKIPPED
    price_change = Column(Numeric(12, 5))
    resolved = Column(Boolean, default=False)
    resolve_at = Column(DateTime(timezone=True))


# ============================================================
#  FOREX TABLES — Completely isolated from R_100 / synthetic
# ============================================================

class ForexCandle(Base):
    """OHLC candles + indicators for Forex instruments (e.g. frxEURUSD).
    Kept fully separate from 'candles' table to avoid mixing with synthetics."""
    __tablename__ = "forex_candles"

    id = Column(BigInteger, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)   # e.g. 'frxEURUSD'
    timeframe = Column(String(5), nullable=False)              # '60s'
    open_time = Column(DateTime(timezone=True), nullable=False, index=True)
    close_time = Column(DateTime(timezone=True), nullable=False)

    # OHLCV (price scale ~1.0800–1.1200 for EURUSD)
    open  = Column(Numeric(18, 8), nullable=False)
    high  = Column(Numeric(18, 8), nullable=False)
    low   = Column(Numeric(18, 8), nullable=False)
    close = Column(Numeric(18, 8), nullable=False)
    volume = Column(Numeric(18, 4), default=0)

    # Standard Technical Indicators
    ema_9  = Column(Numeric(18, 8))
    ema_21 = Column(Numeric(18, 8))
    ema_50 = Column(Numeric(18, 8))
    rsi_14 = Column(Numeric(8, 4))
    stoch_rsi = Column(Numeric(8, 4))
    atr_14 = Column(Numeric(18, 8))
    adx_14 = Column(Numeric(8, 4))
    plus_di  = Column(Numeric(8, 4))
    minus_di = Column(Numeric(8, 4))
    bollinger_upper  = Column(Numeric(18, 8))
    bollinger_middle = Column(Numeric(18, 8))
    bollinger_lower  = Column(Numeric(18, 8))
    macd          = Column(Numeric(18, 8))
    macd_signal   = Column(Numeric(18, 8))
    macd_histogram = Column(Numeric(18, 8))

    # Returns & Volatility
    returns             = Column(Numeric(12, 8))
    log_returns         = Column(Numeric(12, 8))
    momentum_5          = Column(Numeric(12, 8))
    momentum_10         = Column(Numeric(12, 8))
    volatility_realized = Column(Numeric(12, 8))
    volume_delta        = Column(Numeric(18, 4))
    price_position      = Column(Numeric(8, 6))

    # Market Structure (SMC — works on real forex)
    is_order_block = Column(Boolean, default=False)
    ob_type  = Column(String(10))
    is_fvg   = Column(Boolean, default=False)
    fvg_type = Column(String(10))
    bos   = Column(Boolean, default=False)
    choch = Column(Boolean, default=False)

    # Statistical Analysis
    hurst_exponent           = Column(Numeric(8, 6))
    hurst_fast               = Column(Numeric(8, 6))
    ou_deviation             = Column(Numeric(12, 8))
    garch_volatility_forecast = Column(Numeric(12, 8))
    regime = Column(String(30))

    # ATF
    atf_basis  = Column(Numeric(12, 8))
    atf_upper  = Column(Numeric(12, 8))
    atf_lower  = Column(Numeric(12, 8))
    atf_trend  = Column(Integer, default=0)
    atf_slope  = Column(Numeric(12, 8))

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ForexTrade(Base):
    """Executed forex trades — separate from synthetic 'trades' table."""
    __tablename__ = "forex_trades"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False)       # frxEURUSD
    contract_type = Column(String(20), nullable=False) # CALL / PUT
    direction     = Column(String(10), nullable=False)

    # Entry
    entry_time  = Column(DateTime(timezone=True), nullable=False)
    entry_price = Column(Numeric(18, 8), nullable=False)
    stake            = Column(Numeric(10, 2), nullable=False)
    duration_seconds = Column(Integer, nullable=False)

    # Exit
    exit_time   = Column(DateTime(timezone=True))
    exit_price  = Column(Numeric(18, 8))
    profit_loss = Column(Numeric(10, 2))
    outcome     = Column(String(10))  # WIN, LOSS, PENDING

    # Decision layers
    layer1_signal      = Column(String(20))
    layer1_confidence  = Column(Numeric(6, 4))
    layer3_groq_used   = Column(Boolean, default=False)
    layer3_groq_confidence = Column(Numeric(6, 4))
    layer3_groq_reasoning  = Column(Text)

    # Final
    final_confidence   = Column(Numeric(6, 4), nullable=False)
    hurst_at_entry     = Column(Numeric(6, 4))
    deriv_contract_id  = Column(String(50))
    engine_name        = Column(String(50))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ForexBotState(Base):
    """Forex bot state — independent from synthetic bot state."""
    __tablename__ = "forex_bot_state"

    id = Column(Integer, primary_key=True, default=1)

    balance         = Column(Numeric(12, 2), nullable=False, default=0)
    initial_balance = Column(Numeric(12, 2), nullable=False, default=10000)
    peak_balance    = Column(Numeric(12, 2), nullable=False, default=0)
    current_drawdown_pct = Column(Numeric(8, 4), default=0)

    is_trading_enabled  = Column(Boolean, default=True)
    trades_today        = Column(Integer, default=0)
    losses_consecutive  = Column(Integer, default=0)
    wins_today          = Column(Integer, default=0)
    losses_today        = Column(Integer, default=0)
    daily_pnl           = Column(Numeric(10, 2), default=0)

    cooldown_until  = Column(DateTime(timezone=True))
    cooldown_reason = Column(String(100))
    last_trade_date = Column(Date)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


