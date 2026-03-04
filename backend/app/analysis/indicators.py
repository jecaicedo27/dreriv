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
            df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
            df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
            df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
            
            # RSI (Relative Strength Index)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / (loss + 1e-10)
            df['rsi_14'] = 100 - (100 / (1 + rs))
            
            # Stochastic RSI (K line, 0-100 scale)
            rsi_series = df['rsi_14']
            rsi_min = rsi_series.rolling(window=14).min()
            rsi_max = rsi_series.rolling(window=14).max()
            stoch_rsi_raw = ((rsi_series - rsi_min) / (rsi_max - rsi_min + 1e-10)) * 100
            df['stoch_rsi'] = stoch_rsi_raw.rolling(window=3).mean()  # Smoothed K line
            
            # ATR (Average True Range)
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df['atr_14'] = tr.rolling(window=14).mean()
            
            # ADX (Average Directional Index) with +DI/-DI
            # Directional Movement
            up_move = df['high'] - df['high'].shift(1)
            down_move = df['low'].shift(1) - df['low']
            plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
            minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
            # Smoothed with Wilder's EMA (alpha = 1/14)
            atr_smooth = tr.ewm(alpha=1/14, adjust=False).mean()
            plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / (atr_smooth + 1e-10)
            minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / (atr_smooth + 1e-10)
            dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
            df['adx_14'] = dx.ewm(alpha=1/14, adjust=False).mean()
            df['plus_di'] = plus_di
            df['minus_di'] = minus_di
            
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
            
            # EMA Crossover Analysis
            df['ema_21_above_50'] = (df['ema_21'] > df['ema_50']).astype(int)
            # Detect crossover points (value changes from 0→1 or 1→0)
            df['ema_cross_event'] = df['ema_21_above_50'].diff().abs()
            # Count bars since last crossover (cumulative count resetting at each cross)
            cross_groups = df['ema_cross_event'].cumsum()
            df['ema_cross_age'] = df.groupby(cross_groups).cumcount()
            # EMA separation and its rate of change
            df['ema_gap'] = df['ema_21'] - df['ema_50']
            df['ema_gap_rate'] = df['ema_gap'].diff(3)  # Change over 3 bars
            # Diverging = gap growing in the direction of the trend
            df['ema_diverging'] = (
                ((df['ema_gap'] > 0) & (df['ema_gap_rate'] > 0)) |  # Bullish & widening
                ((df['ema_gap'] < 0) & (df['ema_gap_rate'] < 0))    # Bearish & widening
            ).astype(int)
            
            # ===== ATF: Adaptive Trend Flow (QuantAlgo) =====
            # Dual-EMA basis with volatility-adjusted bands
            atf_fast_len = 10   # Main Length
            atf_slow_len = 14   # Smoothing Length  
            atf_sensitivity = 2.0  # Band sensitivity
            
            atf_fast_ema = df['close'].ewm(span=atf_fast_len, adjust=False).mean()
            atf_slow_ema = df['close'].ewm(span=atf_slow_len, adjust=False).mean()
            df['atf_basis'] = (atf_fast_ema + atf_slow_ema) / 2.0
            
            # Volatility: smoothed stddev of close, window=smoothing length
            atf_raw_vol = df['close'].rolling(window=atf_slow_len).std()
            atf_smoothed_vol = atf_raw_vol.ewm(span=atf_slow_len, adjust=False).mean()
            
            # Adaptive bands
            df['atf_upper'] = df['atf_basis'] + (atf_smoothed_vol * atf_sensitivity)
            df['atf_lower'] = df['atf_basis'] - (atf_smoothed_vol * atf_sensitivity)
            
            # Trend detection: +1 = bullish (close above upper band),
            #                   -1 = bearish (close below lower band), 0 = neutral
            atf_trend = pd.Series(0, index=df.index, dtype=int)
            for i in range(1, len(df)):
                prev_trend = atf_trend.iloc[i-1]
                close_val = df['close'].iloc[i]
                upper_val = df['atf_upper'].iloc[i]
                lower_val = df['atf_lower'].iloc[i]
                
                if pd.isna(upper_val) or pd.isna(lower_val):
                    atf_trend.iloc[i] = prev_trend
                elif close_val > upper_val:
                    atf_trend.iloc[i] = 1   # Bullish breakout
                elif close_val < lower_val:
                    atf_trend.iloc[i] = -1  # Bearish breakdown
                else:
                    atf_trend.iloc[i] = prev_trend  # Stay in current trend
            
            df['atf_trend'] = atf_trend
            
            # Slope of basis (rate of change over 3 bars — direction + strength)
            df['atf_slope'] = df['atf_basis'].diff(3) / (df['atf_basis'].shift(3) + 1e-10) * 100
            
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
            'ema_20': float(latest.get('ema_20', 0)),
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
            'price_position': float(latest.get('price_position', 0)),
            # EMA Crossover metrics
            'ema_cross_direction': 'BULLISH' if int(latest.get('ema_21_above_50', 0)) == 1 else 'BEARISH',
            'ema_cross_age': int(latest.get('ema_cross_age', 0)),
            'ema_diverging': bool(int(latest.get('ema_diverging', 0))),
            'ema_separation_rate': float(latest.get('ema_gap_rate', 0)),
            'adx_14': float(latest.get('adx_14', 0)),
            'plus_di': float(latest.get('plus_di', 0)),
            'minus_di': float(latest.get('minus_di', 0)),
        }

    @staticmethod
    def compute_ema_slope(df: pd.DataFrame, lookback: int = 20) -> dict:
        """
        Compute the linear regression slope of EMA21 over the last `lookback` candles.

        This is the discrete 'derivative' of the trend line — a positive slope means
        the market is trending UP, negative means DOWN, near-zero means LATERAL.

        Returns:
            dict with:
                slope        float  — price pts per candle (signed)
                slope_abs    float  — |slope|
                slope_pct    float  — slope as % of current price per candle
                direction    str    — 'UP', 'DOWN', or 'FLAT'
        """
        result = {'slope': 0.0, 'slope_abs': 0.0, 'slope_pct': 0.0, 'direction': 'FLAT'}
        try:
            col = 'ema_21' if 'ema_21' in df.columns else 'close'
            series = df[col].dropna().tail(lookback)
            if len(series) < 5:
                return result
            n = len(series)
            x = np.arange(n)
            y = series.values
            slope = float(np.polyfit(x, y, 1)[0])
            current_price = float(y[-1])
            slope_pct = (slope / current_price * 100) if current_price else 0.0
            result = {
                'slope': round(slope, 4),
                'slope_abs': round(abs(slope), 4),
                'slope_pct': round(slope_pct, 6),
                'direction': 'UP' if slope > 0 else 'DOWN' if slope < 0 else 'FLAT',
            }
        except Exception as e:
            logger.debug(f"compute_ema_slope error: {e}")
        return result

