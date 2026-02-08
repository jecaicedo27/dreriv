"""
Ornstein-Uhlenbeck Mean Reversion Model
For detecting mean reversion opportunities in Volatility indices (R_75, R_100)

Based on skill: statistical-trading-models
"""
import numpy as np
import pandas as pd
from scipy import stats
from typing import Tuple, Dict, Any
from loguru import logger


class OrnsteinUhlenbeckModel:
    """
    Ornstein-Uhlenbeck process for mean reversion detection
    
    The O-U process models mean reversion with force proportional to deviation:
    dx = theta * (mu - x) * dt + sigma * dW
    
    Where:
    - mu: Long-term mean (equilibrium level)
    - theta: Speed of mean reversion
    - sigma: Volatility
    """
    
    def __init__(self, window: int = 200):
        self.window = window
        self.mu = None  # Long-term mean
        self.theta = None  # Mean reversion speed
        self.sigma = None  # Volatility
        self.half_life = None  # Time to revert 50% to mean
        
    def fit(self, prices: pd.Series) -> bool:
        """
        Fit O-U parameters to price series
        
        Args:
            prices: Series of prices
            
        Returns:
            bool: True if fit successful
        """
        if len(prices) < self.window:
            logger.warning(f"Not enough data for O-U fit (need {self.window}, got {len(prices)})")
            return False
        
        try:
            # Use last 'window' prices
            prices = prices.tail(self.window)
            
            # Calculate log prices for better stability
            log_prices = np.log(prices)
            
            # Long-term mean
            self.mu = log_prices.mean()
            
            # Fit AR(1) model to estimate theta
            # dx_t = -theta * x_{t-1} + noise
            x = log_prices.values[:-1]
            dx = np.diff(log_prices.values)
            
            # Linear regression: dx = a + b*x
            slope, intercept, r_value, p_value, std_err = stats.linregress(x, dx)
            
            # theta = -slope (assuming dt = 1)
            self.theta = -slope
            
            # Volatility (std of residuals)
            fitted_dx = intercept + slope * x
            residuals = dx - fitted_dx
            self.sigma = np.std(residuals)
            
            # Half-life: time for process to revert 50% to mean
            if self.theta > 0:
                self.half_life = np.log(2) / self.theta
            else:
                self.half_life = np.inf
                logger.warning("⚠️ Theta <= 0, no mean reversion detected")
            
            logger.debug(f"O-U fitted: mu={self.mu:.4f}, theta={self.theta:.4f}, sigma={self.sigma:.4f}, half_life={self.half_life:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"❌ O-U fit error: {e}")
            return False
    
    def get_deviation(self, current_price: float) -> float:
        """
        Calculate current deviation from equilibrium in standard deviations
        
        Args:
            current_price: Current price level
            
        Returns:
            Deviation in sigma units (positive = above mean, negative = below mean)
        """
        if self.mu is None or self.sigma is None:
            return 0.0
        
        log_price = np.log(current_price)
        deviation_raw = log_price - self.mu
        
        # Normalize by sigma
        deviation_std = deviation_raw / (self.sigma + 1e-10)
        
        return deviation_std
    
    def get_signal(self, current_price: float, threshold: float = 2.0) -> Dict[str, Any]:
        """
        Get trading signal based on O-U deviation
        
        Args:
            current_price: Current price
            threshold: Deviation threshold in sigma (default 2.0)
            
        Returns:
            Dictionary with signal, deviation, and metadata
        """
        if self.mu is None:
            return {
                'signal': 'HOLD',
                'deviation': 0.0,
                'confidence': 0.0,
                'reason': 'Model not fitted'
            }
        
        deviation = self.get_deviation(current_price)
        
        # Signal logic
        signal = 'HOLD'
        confidence = 0.0
        reason = ''
        
        if abs(deviation) > threshold:
            # Strong deviation → mean reversion expected
            if deviation > threshold:
                # Price too high → expect reversion DOWN → SELL/PUT signal
                signal = 'PUT'
                confidence = min(abs(deviation) / 3.0, 0.95)  # Cap at 0.95
                reason = f'Price {deviation:.2f}σ above mean, expecting reversion down'
            else:
                # Price too low → expect reversion UP → BUY/CALL signal
                signal = 'CALL'
                confidence = min(abs(deviation) / 3.0, 0.95)
                reason = f'Price {abs(deviation):.2f}σ below mean, expecting reversion up'
        else:
            reason = f'Deviation {deviation:.2f}σ below threshold {threshold}σ'
        
        return {
            'signal': signal,
            'deviation': round(deviation, 4),
            'confidence': round(confidence, 4),
            'half_life': round(self.half_life, 2) if self.half_life else None,
            'theta': round(self.theta, 6) if self.theta else None,
            'reason': reason
        }
    
    def get_suggested_duration(self) -> int:
        """
        Suggest contract duration based on half-life
        
        Returns:
            Duration in seconds
        """
        if self.half_life is None or self.half_life == np.inf:
            return 300  # Default 5 minutes
        
        # Use 1-2 half-lives as duration
        duration = int(self.half_life * 1.5 * 60)  # Convert to seconds
        
        # Clamp between 1 minute and 15 minutes
        duration = max(60, min(duration, 900))
        
        return duration
