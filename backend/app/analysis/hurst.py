"""
Hurst Exponent Calculator
For detecting if market is trending (H > 0.5) or mean-reverting (H < 0.5)

Based on skill: statistical-trading-models
"""
import numpy as np
import pandas as pd
from loguru import logger
from typing import Dict, Any


class HurstExponent:
    """
    Calculate Hurst exponent to detect market regime:
    - H < 0.5: Mean-reverting (anti-persistent)
    - H ≈ 0.5: Random walk (no edge)
    - H > 0.5: Trending (persistent)
    
    Uses R/S (Rescaled Range) method
    """
    
    @staticmethod
    def calculate(prices: pd.Series, window: int = 200) -> float:
        """
        Calculate Hurst exponent using R/S method
        
        Args:
            prices: Series of prices
            window: Window size for calculation
            
        Returns:
            Hurst exponent (0 to 1)
        """
        if len(prices) < window:
            logger.warning(f"Not enough data for Hurst (need {window}, got {len(prices)})")
            return 0.5  # Default to random walk
        
        try:
            # Use last 'window' prices
            prices = prices.tail(window).values
            
            # Calculate log returns
            log_returns = np.log(prices[1:] / prices[:-1])
            
            # Number of sub-periods to test
            lags = range(2, min(100, len(log_returns) // 2))
            
            # Store (lag, R/S) pairs
            rs_values = []
            
            for lag in lags:
                # Split into chunks of size 'lag'
                n_chunks = len(log_returns) // lag
                
                if n_chunks < 2:
                    continue
                
                rs_chunk = []
                
                for i in range(n_chunks):
                    chunk = log_returns[i*lag:(i+1)*lag]
                    
                    # Mean
                    mean = np.mean(chunk)
                    
                    # Cumulative deviation from mean
                    Y = np.cumsum(chunk - mean)
                    
                    # Range
                    R = np.max(Y) - np.min(Y)
                    
                    # Standard deviation
                    S = np.std(chunk, ddof=1)
                    
                    # R/S ratio
                    if S > 0:
                        rs_chunk.append(R / S)
                
                if rs_chunk:
                    rs_values.append((lag, np.mean(rs_chunk)))
            
            # Linear regression: log(R/S) = H * log(lag) + c
            if len(rs_values) < 5:
                logger.warning("Not enough R/S values for regression")
                return 0.5
            
            lags_array = np.array([x[0] for x in rs_values])
            rs_array = np.array([x[1] for x in rs_values])
            
            # Avoid log(0) or negative values
            valid_idx = rs_array > 0
            lags_array = lags_array[valid_idx]
            rs_array = rs_array[valid_idx]
            
            if len(lags_array) < 5:
                return 0.5
            
            # Log-log regression
            log_lags = np.log(lags_array)
            log_rs = np.log(rs_array)
            
            # Fit line: log_rs = H * log_lags + c
            coeffs = np.polyfit(log_lags, log_rs, 1)
            H = coeffs[0]
            
            # Clamp to valid range [0, 1]
            H = max(0.0, min(1.0, H))
            
            logger.debug(f"Hurst exponent: {H:.4f}")
            return H
            
        except Exception as e:
            logger.error(f"❌ Hurst calculation error: {e}")
            return 0.5  # Default to random walk
    
    @staticmethod
    def interpret(H: float) -> Dict[str, Any]:
        """
        Interpret Hurst exponent value
        
        Args:
            H: Hurst exponent (0 to 1)
            
        Returns:
            Dictionary with interpretation
        """
        # Classification
        if H < 0.45:
            regime = 'MEAN_REVERTING'
            signal = 'FAVORABLE'  # Mean reversion strategies work
            confidence = (0.5 - H) * 2  # Stronger if further from 0.5
            reason = f'Strong mean reversion (H={H:.3f}), O-U strategy favorable'
        elif H < 0.5:
            regime = 'WEAK_MEAN_REVERTING'
            signal = 'FAVORABLE'
            confidence = (0.5 - H) * 2
            reason = f'Weak mean reversion (H={H:.3f}), some edge for O-U'
        elif H > 0.55:
            regime = 'TRENDING'
            signal = 'UNFAVORABLE'
            confidence = (H - 0.5) * 2
            reason = f'Market trending (H={H:.3f}), mean reversion strategies not recommended'
        elif H > 0.5:
            regime = 'WEAK_TRENDING'
            signal = 'CAUTION'
            confidence = (H - 0.5) * 2
            reason = f'Weak trending (H={H:.3f}), reduced edge for mean reversion'
        else:
            regime = 'RANDOM_WALK'
            signal = 'UNFAVORABLE'
            confidence = 0.9
            reason = f'Pure random walk (H={H:.3f}), NO EDGE - avoid trading'
        
        return {
            'hurst': round(H, 4),
            'regime': regime,
            'signal': signal,
            'confidence': round(confidence, 4),
            'reason': reason,
            'trade_recommended': signal == 'FAVORABLE'
        }
    
    @staticmethod
    def get_signal(prices: pd.Series, window: int = 200) -> Dict[str, Any]:
        """
        Calculate Hurst and return trading signal
        
        Args:
            prices: Price series
            window: Calculation window
            
        Returns:
            Signal dictionary
        """
        H = HurstExponent.calculate(prices, window)
        return HurstExponent.interpret(H)
