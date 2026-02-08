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
    atr_14 = Column(Numeric(18, 8))
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
    ou_deviation = Column(Numeric(12, 8))
    garch_volatility_forecast = Column(Numeric(12, 8))
    regime = Column(String(30))
    
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
    
    # Deriv contract reference
    deriv_contract_id = Column(String(50))
    
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
