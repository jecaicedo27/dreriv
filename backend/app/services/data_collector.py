"""
Data Collection Service
Collects ticks from Deriv WebSocket and builds candles
"""
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List
from loguru import logger
from sqlalchemy.orm import Session
from collections import deque

from app.models.models import RawTick, Candle
from app.analysis.indicators import TechnicalIndicators


class DataCollector:
    """
    Collect ticks and aggregate into candles
    """
    
    def __init__(self, db: Session, symbol: str, timeframe_seconds: int = 60):
        self.db = db
        self.symbol = symbol
        self.timeframe_seconds = timeframe_seconds
        
        # In-memory tick buffer (fast access)
        self.tick_buffer = deque(maxlen=1000)
        
        # Current candle being built
        self.current_candle = None
        self.candle_start_time = None
    
    async def process_tick(self, tick_data: Dict[str, Any]):
        """
        Process incoming tick and update candles
        
        Args:
            tick_data: Tick from Deriv WebSocket
        """
        try:
            epoch = tick_data['epoch']
            quote = float(tick_data['quote'])
            symbol = tick_data['symbol']
            
            # Save raw tick with ON CONFLICT DO NOTHING to avoid UniqueViolation crash loops
            from sqlalchemy import text as sa_text
            self.db.execute(
                sa_text("INSERT INTO raw_ticks (symbol, epoch, quote) VALUES (:s, :e, :q) ON CONFLICT DO NOTHING"),
                {"s": symbol, "e": epoch, "q": quote}
            )
            self.db.commit()
            
            # Add to buffer
            self.tick_buffer.append({
                'epoch': epoch,
                'quote': quote,
                'timestamp': datetime.fromtimestamp(epoch)
            })
            
            # Update current candle
            await self._update_candle(epoch, quote)
            
        except Exception as e:
            try:
                self.db.rollback()
            except Exception:
                pass
            logger.error(f"❌ Error processing tick: {e}")
    
    async def _update_candle(self, epoch: int, quote: float):
        """Update or finalize current candle"""
        tick_time = datetime.fromtimestamp(epoch)
        
        # Determine candle start time (round down to timeframe)
        candle_start = tick_time.replace(second=0, microsecond=0)
        minutes = (candle_start.minute // (self.timeframe_seconds // 60)) * (self.timeframe_seconds // 60)
        candle_start = candle_start.replace(minute=minutes)
        
        # If new candle period, finalize previous
        if self.candle_start_time and candle_start > self.candle_start_time:
            await self._finalize_candle()
        
        # Initialize new candle if needed
        if not self.current_candle or candle_start > self.candle_start_time:
            self.candle_start_time = candle_start
            self.current_candle = {
                'open': quote,
                'high': quote,
                'low': quote,
                'close': quote,
                'ticks': []
            }
        
        # Update candle
        self.current_candle['high'] = max(self.current_candle['high'], quote)
        self.current_candle['low'] = min(self.current_candle['low'], quote)
        self.current_candle['close'] = quote
        self.current_candle['ticks'].append(quote)
    
    async def _finalize_candle(self):
        """Save completed candle to database with indicators"""
        if not self.current_candle:
            return
        
        try:
            candle_close_time = self.candle_start_time + timedelta(seconds=self.timeframe_seconds)
            
            # Use upsert to avoid duplicate candle errors
            from sqlalchemy import text as sa_text
            self.db.execute(
                sa_text("""
                    INSERT INTO candles (symbol, timeframe, open_time, close_time, open, high, low, close, volume)
                    VALUES (:sym, :tf, :ot, :ct, :o, :h, :l, :c, :v)
                    ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET
                        high = GREATEST(candles.high, EXCLUDED.high),
                        low = LEAST(candles.low, EXCLUDED.low),
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """),
                {
                    "sym": self.symbol,
                    "tf": f"{self.timeframe_seconds}s",
                    "ot": self.candle_start_time,
                    "ct": candle_close_time,
                    "o": self.current_candle['open'],
                    "h": self.current_candle['high'],
                    "l": self.current_candle['low'],
                    "c": self.current_candle['close'],
                    "v": len(self.current_candle['ticks']),
                }
            )
            self.db.commit()
            
            logger.debug(f"🕯️ Candle saved: {self.symbol} @ {self.candle_start_time}")
            
            # Calculate indicators for recent candles (in background)
            asyncio.create_task(self._calculate_indicators())
            
        except Exception as e:
            try:
                self.db.rollback()
            except Exception:
                pass
            logger.error(f"❌ Error finalizing candle: {e}")
    
    async def _calculate_indicators(self):
        """Calculate technical indicators for recent candles"""
        try:
            # Get last 200 candles
            candles = self.db.query(Candle).filter(
                Candle.symbol == self.symbol,
                Candle.timeframe == f"{self.timeframe_seconds}s"
            ).order_by(Candle.open_time.desc()).limit(200).all()
            
            if len(candles) < 50:
                return
            
            # Convert to DataFrame
            df = pd.DataFrame([{
                'open': float(c.open),
                'high': float(c.high),
                'low': float(c.low),
                'close': float(c.close),
                'volume': float(c.volume) if c.volume else 0
            } for c in reversed(candles)])
            
            # Calculate standard indicators
            df = TechnicalIndicators.calculate_all(df)
            
            # Update candles with indicators (NEWEST 10 candles)
            # candles is DESC order: candles[0]=newest, candles[:10]=newest 10
            # df is ASC order: df.iloc[-1]=newest, df.iloc[-10:]=newest 10
            newest_10 = candles[:10]
            for i, candle in enumerate(newest_10):
                df_idx = len(df) - 1 - i  # Map DESC candle[0] → df.iloc[-1], candle[1] → df.iloc[-2], etc.
                if 0 <= df_idx < len(df):
                    row = df.iloc[df_idx]
                    
                    # EMA
                    candle.ema_9 = row.get('ema_9')
                    candle.ema_21 = row.get('ema_21')
                    candle.ema_50 = row.get('ema_50')
                    # RSI & ATR
                    candle.rsi_14 = row.get('rsi_14')
                    candle.stoch_rsi = row.get('stoch_rsi')
                    candle.atr_14 = row.get('atr_14')
                    candle.adx_14 = row.get('adx_14')
                    candle.plus_di = row.get('plus_di')
                    candle.minus_di = row.get('minus_di')
                    # Returns & Volatility
                    candle.returns = row.get('returns')
                    candle.volatility_realized = row.get('volatility_realized')
                    # MACD
                    candle.macd = row.get('macd')
                    candle.macd_signal = row.get('macd_signal')
                    candle.macd_histogram = row.get('macd_histogram')
                    # Bollinger Bands
                    candle.bollinger_upper = row.get('bollinger_upper')
                    candle.bollinger_middle = row.get('bollinger_middle')
                    candle.bollinger_lower = row.get('bollinger_lower')
                    # Momentum & Price Position
                    candle.momentum_5 = row.get('momentum_5')
                    candle.price_position = row.get('price_position')
                    # Additional indicators needed by engines
                    candle.momentum_10 = row.get('momentum_10')
                    candle.log_returns = row.get('log_returns')
                    candle.volume_delta = row.get('volume_delta')
                    # ATF indicators
                    candle.atf_basis = row.get('atf_basis')
                    candle.atf_upper = row.get('atf_upper')
                    candle.atf_lower = row.get('atf_lower')
                    candle.atf_trend = int(row.get('atf_trend', 0)) if pd.notna(row.get('atf_trend')) else 0
                    candle.atf_slope = row.get('atf_slope')
            
            # --- Calculate Hurst + O-U + GARCH for the LATEST candle ---
            if len(df) >= 200:
                try:
                    from app.analysis.hurst import HurstExponent
                    from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
                    
                    prices = df['close']
                    latest_candle = candles[0]  # Most recent (desc order)
                    
                    # Hurst: both slow (R/S, window=200) and fast (VR, window=50)
                    hurst_val = HurstExponent.calculate(prices, window=200)
                    hurst_fast = HurstExponent.calculate_fast(prices, window=50)
                    hurst_hybrid = HurstExponent.get_hybrid_signal(prices, fast_window=50, slow_window=200)
                    
                    # O-U deviation
                    ou_model = OrnsteinUhlenbeckModel(window=200)
                    ou_dev = 0.0
                    if ou_model.fit(prices):
                        ou_dev = ou_model.get_deviation(float(latest_candle.close))
                    
                    # GARCH volatility forecast
                    garch_forecast = None
                    try:
                        from app.analysis.garch import GARCHModel
                        returns_series = df['returns'].dropna()
                        if len(returns_series) > 50:
                            garch_model = GARCHModel(window=100)
                            if garch_model.fit(returns_series):
                                vol_forecast = garch_model.forecast(horizon=1)
                                if vol_forecast is not None and len(vol_forecast) > 0:
                                    garch_forecast = float(vol_forecast[0]) / 100.0  # Convert from % to decimal
                    except Exception as ge:
                        logger.debug(f"GARCH calc error: {ge}")
                    
                    # Write to latest candle
                    latest_candle.hurst_exponent = hurst_val
                    latest_candle.hurst_fast = hurst_fast
                    latest_candle.ou_deviation = ou_dev
                    latest_candle.regime = hurst_hybrid.get('regime', 'RANDOM_WALK')
                    if garch_forecast is not None:
                        latest_candle.garch_volatility_forecast = garch_forecast
                    
                except Exception as he:
                    logger.debug(f"Hurst/OU calc error: {he}")
            
            self.db.commit()
            
        except Exception as e:
            try:
                self.db.rollback()
            except Exception:
                pass
            logger.error(f"❌ Error calculating indicators: {e}")
    
    def get_recent_candles(self, count: int = 200) -> pd.DataFrame:
        """
        Get recent candles as DataFrame
        
        Args:
            count: Number of candles to retrieve
            
        Returns:
            DataFrame with OHLCV data
        """
        candles = self.db.query(Candle).filter(
            Candle.symbol == self.symbol,
            Candle.timeframe == f"{self.timeframe_seconds}s"
        ).order_by(Candle.open_time.desc()).limit(count).all()
        
        if not candles:
            return pd.DataFrame()
        
        df = pd.DataFrame([{
        'open_time': c.open_time,
        'open': float(c.open),
        'high': float(c.high),
        'low': float(c.low),
        'close': float(c.close),
        'volume': float(c.volume) if c.volume else 0,
        # Standard indicators
        'ema_9': float(c.ema_9) if c.ema_9 else None,
        'ema_21': float(c.ema_21) if c.ema_21 else None,
        'ema_50': float(c.ema_50) if c.ema_50 else None,
        'rsi_14': float(c.rsi_14) if c.rsi_14 else None,
        'atr_14': float(c.atr_14) if c.atr_14 else None,
        'macd': float(c.macd) if c.macd else None,
        'macd_signal': float(c.macd_signal) if c.macd_signal else None,
        'macd_histogram': float(c.macd_histogram) if c.macd_histogram else None,
        'bollinger_upper': float(c.bollinger_upper) if c.bollinger_upper else None,
        'bollinger_middle': float(c.bollinger_middle) if c.bollinger_middle else None,
        'bollinger_lower': float(c.bollinger_lower) if c.bollinger_lower else None,
        'momentum_5': float(c.momentum_5) if c.momentum_5 else None,
        'returns': float(c.returns) if c.returns else None,
        'log_returns': float(c.log_returns) if c.log_returns else None,
        'volatility_realized': float(c.volatility_realized) if c.volatility_realized else None,
        'price_position': float(c.price_position) if c.price_position else None,
        'volume_delta': float(c.volume_delta) if c.volume_delta else None,
        # Statistical indicators (Hurst, O-U, GARCH)
        'hurst_exponent': float(c.hurst_exponent) if c.hurst_exponent else None,
        'hurst_fast': float(c.hurst_fast) if c.hurst_fast else None,
        'garch_volatility_forecast': float(c.garch_volatility_forecast) if c.garch_volatility_forecast else None,
        'ou_deviation': float(getattr(c, 'ou_deviation', None) or 0) if getattr(c, 'ou_deviation', None) else None,
        'regime': getattr(c, 'regime', None),
        # ATF indicators
        'atf_basis': float(c.atf_basis) if getattr(c, 'atf_basis', None) else None,
        'atf_upper': float(c.atf_upper) if getattr(c, 'atf_upper', None) else None,
        'atf_lower': float(c.atf_lower) if getattr(c, 'atf_lower', None) else None,
        'atf_trend': int(c.atf_trend) if getattr(c, 'atf_trend', None) is not None else 0,
        'atf_slope': float(c.atf_slope) if getattr(c, 'atf_slope', None) else None,
    } for c in reversed(candles)])
        
        return df
