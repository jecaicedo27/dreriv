import pandas as pd
import numpy as np
from typing import Dict, Any
from loguru import logger
# Using pure pandas/numpy for indicators (no pandas_ta dependency)


class TechnicalIndicators:
    """
    Calculate technical indicators for trading analysis
    """
    
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate all technical indicators for a dataframe of OHLCV data
        
        Args:
            df: DataFrame with columns: open, high, low, close, volume
        
        Returns:
            DataFrame with all indicators added as new columns
        """
        if df.empty or len(df) < 50:
            logger.warning("Not enough data for indicators calculation")
            return df
        
        df = df.copy()
        
        try:
            # Moving Averages (simple EMA calculation)
            df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
            df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
            
            # RSI (Relative Strength Index)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-10)
            df['rsi_14'] = 100 - (100 / (1 + rs))
            
            # ATR (Average True Range)
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df['atr_14'] = tr.rolling(window=14).mean()
            
            # Bollinger Bands
            df['bollinger_middle'] = df['close'].rolling(window=20).mean()
            std = df['close'].rolling(window=20).std()
            df['bollinger_upper'] = df['bollinger_middle'] + (std * 2)
            df['bollinger_lower'] = df['bollinger_middle'] - (std * 2)
            
            # MACD
            ema_12 = df['close'].ewm(span=12, adjust=False).mean()
            ema_26 = df['close'].ewm(span=26, adjust=False).mean()
            df['macd'] = ema_12 - ema_26
            df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
            df['macd_histogram'] = df['macd'] - df['macd_signal']
            
            # Additional features for pgvector
            df['returns'] = df['close'].pct_change()
            df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
            
            # Momentum
            df['momentum_5'] = df['close'] - df['close'].shift(5)
            df['momentum_10'] = df['close'] - df['close'].shift(10)
            
            # Realized volatility (std of returns over 20 periods)
            df['volatility_realized'] = df['returns'].rolling(window=20).std()
            
            # Volume delta (if volume available)
            if 'volume' in df.columns:
                df['volume_delta'] = df['volume'] - df['volume'].shift(1)
            else:
                df['volume_delta'] = 0
            
            # Price position within range (0 = at low, 1 = at high)
            df['price_position'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-10)
            
            logger.debug(f"✅ Calculated indicators for {len(df)} candles")
            return df
            
        except Exception as e:
            logger.error(f"❌ Error calculating indicators: {e}")
            return df
    
    @staticmethod
    def get_latest_values(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Get dictionary of latest indicator values
        """
        if df.empty:
            return {}
        
        latest = df.iloc[-1]
        
        return {
            'ema_9': float(latest.get('ema_9', 0)),
            'ema_21': float(latest.get('ema_21', 0)),
            'ema_50': float(latest.get('ema_50', 0)),
            'rsi_14': float(latest.get('rsi_14', 0)),
            'atr_14': float(latest.get('atr_14', 0)),
            'bollinger_upper': float(latest.get('bollinger_upper', 0)),
            'bollinger_middle': float(latest.get('bollinger_middle', 0)),
            'bollinger_lower': float(latest.get('bollinger_lower', 0)),
            'macd': float(latest.get('macd', 0)),
            'macd_signal': float(latest.get('macd_signal', 0)),
            'macd_histogram': float(latest.get('macd_histogram', 0)),
            'returns': float(latest.get('returns', 0)),
            'momentum_5': float(latest.get('momentum_5', 0)),
            'volatility_realized': float(latest.get('volatility_realized', 0)),
            'price_position': float(latest.get('price_position', 0))
        }
