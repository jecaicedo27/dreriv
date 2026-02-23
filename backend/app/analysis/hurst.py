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
    
    @staticmethod
    def calculate_fast(prices: pd.Series, window: int = 50) -> float:
        """
        Fast Hurst estimator using Variance Ratio method.
        
        Much more responsive than R/S for short windows.
        VR(q) = Var(q-period returns) / (q * Var(1-period returns))
        If VR > 1 → trending (H > 0.5), VR < 1 → mean-reverting (H < 0.5)
        
        We convert VR to a Hurst-like scale [0, 1] for compatibility.
        
        Args:
            prices: Series of prices
            window: Window size (default 50 = ~50 minutes)
            
        Returns:
            Hurst-like value (0 to 1)
        """
        if len(prices) < window:
            return 0.5
        
        try:
            prices_arr = prices.tail(window).values.astype(float)
            
            # Log returns
            log_ret = np.diff(np.log(prices_arr))
            
            if len(log_ret) < 10:
                return 0.5
            
            # Variance of 1-period returns
            var_1 = np.var(log_ret, ddof=1)
            if var_1 < 1e-20:
                return 0.5
            
            # Test multiple aggregation periods for robustness
            hurst_estimates = []
            for q in [2, 4, 8, 16]:
                if q >= len(log_ret):
                    continue
                
                # q-period returns (non-overlapping)
                n_blocks = len(log_ret) // q
                if n_blocks < 2:
                    continue
                
                q_rets = np.array([
                    np.sum(log_ret[i*q:(i+1)*q]) 
                    for i in range(n_blocks)
                ])
                var_q = np.var(q_rets, ddof=1)
                
                # Variance ratio
                vr = var_q / (q * var_1)
                
                # Convert VR to Hurst: VR = q^(2H-1) → H = (log(VR)/log(q) + 1) / 2
                if vr > 0:
                    h_est = (np.log(vr) / np.log(q) + 1) / 2
                    h_est = max(0.0, min(1.0, h_est))
                    hurst_estimates.append(h_est)
            
            if not hurst_estimates:
                return 0.5
            
            # Weighted average (higher q gets more weight for stability)
            H_fast = np.mean(hurst_estimates)
            H_fast = max(0.0, min(1.0, H_fast))
            
            logger.debug(f"Hurst FAST (VR): {H_fast:.4f} (from {len(hurst_estimates)} estimates)")
            return H_fast
            
        except Exception as e:
            logger.error(f"❌ Hurst VR calculation error: {e}")
            return 0.5
    
    @staticmethod
    def get_hybrid_signal(prices: pd.Series, fast_window: int = 50, slow_window: int = 200) -> Dict[str, Any]:
        """
        Combined signal from Fast (Variance Ratio) + Slow (R/S) Hurst.
        
        Regime matrix:
          Fast > 0.55 AND Slow > 0.50 → TRENDING_CONFIRMED (high confidence)
          Fast > 0.55 AND Slow < 0.50 → TRENDING_EMERGING (medium confidence)
          Fast < 0.45 AND Slow < 0.50 → MEAN_REVERSION_CONFIRMED (high confidence)  
          Fast < 0.45 AND Slow > 0.50 → TRANSITIONING (low confidence, wait)
          Else                        → RANDOM_WALK (no edge)
        """
        H_fast = HurstExponent.calculate_fast(prices, window=fast_window)
        H_slow = HurstExponent.calculate(prices, window=slow_window)
        
        # Determine combined regime
        if H_fast > 0.55 and H_slow > 0.50:
            regime = 'TRENDING_CONFIRMED'
            signal = 'UNFAVORABLE'  # Mean reversion strategies not recommended
            confidence = min((H_fast - 0.5) * 3 + (H_slow - 0.5) * 2, 0.95)
            reason = f'Both fast ({H_fast:.3f}) and slow ({H_slow:.3f}) show trending'
            trade_recommended = False
        elif H_fast > 0.55 and H_slow <= 0.50:
            regime = 'TRENDING_EMERGING'
            signal = 'CAUTION'
            confidence = (H_fast - 0.5) * 2
            reason = f'Fast trending ({H_fast:.3f}) but slow still neutral ({H_slow:.3f}) — trend emerging'
            trade_recommended = False
        elif H_fast < 0.45 and H_slow < 0.50:
            regime = 'MEAN_REVERSION_CONFIRMED'
            signal = 'FAVORABLE'
            confidence = min((0.5 - H_fast) * 3 + (0.5 - H_slow) * 2, 0.95)
            reason = f'Both fast ({H_fast:.3f}) and slow ({H_slow:.3f}) confirm mean reversion'
            trade_recommended = True
        elif H_fast < 0.45 and H_slow >= 0.50:
            regime = 'TRANSITIONING'
            signal = 'CAUTION'
            confidence = (0.5 - H_fast) * 2
            reason = f'Fast mean-reverting ({H_fast:.3f}) but slow still trending ({H_slow:.3f}) — transitioning'
            trade_recommended = False
        else:
            regime = 'RANDOM_WALK'
            signal = 'UNFAVORABLE'
            confidence = 0.3
            reason = f'No clear regime: fast={H_fast:.3f}, slow={H_slow:.3f}'
            trade_recommended = False
        
        return {
            'hurst': round(H_slow, 4),        # Backward compatible
            'hurst_fast': round(H_fast, 4),
            'hurst_slow': round(H_slow, 4),
            'regime': regime,
            'signal': signal,
            'confidence': round(max(0, min(confidence, 0.95)), 4),
            'reason': reason,
            'trade_recommended': trade_recommended,
        }
