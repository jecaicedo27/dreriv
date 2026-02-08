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
            
            # Save to database (async would be better)
            raw_tick = RawTick(
                symbol=symbol,
                epoch=epoch,
                quote=quote
            )
            self.db.add(raw_tick)
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
            
            # Create candle
            candle = Candle(
                symbol=self.symbol,
                timeframe=f"{self.timeframe_seconds}s",
                open_time=self.candle_start_time,
                close_time=candle_close_time,
                open=self.current_candle['open'],
                high=self.current_candle['high'],
                low=self.current_candle['low'],
                close=self.current_candle['close'],
                volume=len(self.current_candle['ticks'])
            )
            
            self.db.add(candle)
            self.db.commit()
            
            logger.debug(f"🕯️ Candle saved: {self.symbol} @ {self.candle_start_time}")
            
            # Calculate indicators for recent candles (in background)
            asyncio.create_task(self._calculate_indicators())
            
        except Exception as e:
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
            
            # Calculate indicators
            df = TechnicalIndicators.calculate_all(df)
            
            # Update candles with indicators (only latest ones to avoid overload)
            for i, candle in enumerate(reversed(candles[-10:])):  # Last 10 candles
                idx = len(candles) - 10 + i
                if idx < len(df):
                    row = df.iloc[idx]
                    
                    candle.ema_9 = row.get('ema_9')
                    candle.ema_21 = row.get('ema_21')
                    candle.ema_50 = row.get('ema_50')
                    candle.rsi_14 = row.get('rsi_14')
                    candle.atr_14 = row.get('atr_14')
                    candle.returns = row.get('returns')
                    candle.volatility_realized = row.get('volatility_realized')
            
            self.db.commit()
            
        except Exception as e:
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
            'ema_9': float(c.ema_9) if c.ema_9 else None,
            'ema_21': float(c.ema_21) if c.ema_21 else None,
            'rsi_14': float(c.rsi_14) if c.rsi_14 else None,
            'atr_14': float(c.atr_14) if c.atr_14 else None,
            'returns': float(c.returns) if c.returns else None,
            'volatility_realized': float(c.volatility_realized) if c.volatility_realized else None
        } for c in reversed(candles)])
        
        return df
