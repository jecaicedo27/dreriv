"""
GARCH(1,1) Model for Volatility Forecasting

Based on skill: statistical-trading-models
"""
import numpy as np
import pandas as pd
from arch import arch_model
from loguru import logger
from typing import Dict, Any, Optional


class GARCHModel:
    """
    GARCH(1,1) for forecasting volatility
    
    GARCH (Generalized Autoregressive Conditional Heteroskedasticity) models
    volatility clustering - periods of high volatility tend to cluster together.
    
    GARCH(1,1) equation:
    σ²_t = ω + α * ε²_{t-1} + β * σ²_{t-1}
    
    Where:
    - σ²_t: Conditional variance at time t
    - ω: Long-term average variance
    - α: ARCH term (impact of recent shocks)
    - β: GARCH term (persistence of volatility)
    """
    
    def __init__(self, window: int = 100):
        self.window = window
        self.model = None
        self.fitted_model = None
        self.last_forecast = None
        
    def fit(self, returns: pd.Series) -> bool:
        """
        Fit GARCH(1,1) model to return series
        
        Args:
            returns: Series of returns (%, not log returns)
            
        Returns:
            bool: True if fit successful
        """
        if len(returns) < self.window:
            logger.warning(f"Not enough data for GARCH (need {self.window}, got {len(returns)})")
            return False
        
        try:
            # Use last 'window' returns
            returns = returns.tail(self.window)
            
            # Remove NaN values
            returns = returns.dropna()
            
            if len(returns) < 50:
                logger.warning("Not enough valid returns for GARCH after dropping NaN")
                return False
            
            # Convert to percentage if needed
            returns_pct = returns * 100
            
            # Create GARCH(1,1) model
            self.model = arch_model(
                returns_pct,
                vol='Garch',
                p=1,  # GARCH order
                q=1,  # ARCH order
                rescale=False
            )
            
            # Fit model (suppress output)
            self.fitted_model = self.model.fit(disp='off', show_warning=False)
            
            logger.debug(f"✅ GARCH(1,1) fitted - ω={self.fitted_model.params['omega']:.6f}")
            return True
            
        except Exception as e:
            logger.error(f"❌ GARCH fit error: {e}")
            return False
    
    def forecast(self, horizon: int = 5) -> Optional[np.ndarray]:
        """
        Forecast volatility for next periods
        
        Args:
            horizon: Number of periods to forecast ahead
            
        Returns:
            Array of forecasted volatilities (or None if not fitted)
        """
        if self.fitted_model is None:
            logger.warning("GARCH model not fitted, cannot forecast")
            return None
        
        try:
            # Get forecast
            forecast = self.fitted_model.forecast(horizon=horizon)
            
            # Extract variance forecast and convert to volatility (std dev)
            variance_forecast = forecast.variance.values[-1, :]
            volatility_forecast = np.sqrt(variance_forecast)
            
            self.last_forecast = volatility_forecast
            
            logger.debug(f"GARCH forecast (next {horizon}): {volatility_forecast}")
            return volatility_forecast
            
        except Exception as e:
            logger.error(f"❌ GARCH forecast error: {e}")
            return None
    
    def detect_volatility_regime(self, current_volatility: float) -> Dict[str, Any]:
        """
        Detect if we're entering expansion or contraction regime
        
        Args:
            current_volatility: Current realized volatility
            
        Returns:
            Dict with regime and confidence
        """
        if self.last_forecast is None:
            forecast = self.forecast(horizon=5)
            if forecast is None:
                return {
                    'regime': 'UNKNOWN',
                    'confidence': 0.0,
                    'reason': 'No forecast available'
                }
        
        # Compare current vol to forecast
        forecast_mean = np.mean(self.last_forecast)
        
        # Trend: is volatility increasing or decreasing
        if len(self.last_forecast) > 1:
            forecast_trend = (self.last_forecast[-1] - self.last_forecast[0]) / (self.last_forecast[0] + 1e-10)
        else:
            forecast_trend = 0
        
        # Determine regime
        if forecast_trend > 0.05:  # 5% increase
            regime = 'EXPANDING'
            confidence = min(abs(forecast_trend) * 2, 0.9)
            reason = f'Volatility forecast increasing by {forecast_trend*100:.1f}%'
        elif forecast_trend < -0.05:  # 5% decrease
            regime = 'CONTRACTING'
            confidence = min(abs(forecast_trend) * 2, 0.9)
            reason = f'Volatility forecast decreasing by {abs(forecast_trend)*100:.1f}%'
        else:
            regime = 'STABLE'
            confidence = 0.5
            reason = 'Volatility forecast relatively stable'
        
        return {
            'regime': regime,
            'confidence': round(confidence, 4),
            'forecast_mean': round(forecast_mean, 4),
            'forecast_trend_pct': round(forecast_trend * 100, 2),
            'reason': reason
        }
    
    def get_signal(self, current_volatility: float) -> Dict[str, Any]:
        """
        Get trading adjustment signal based on volatility regime
        
        Args:
            current_volatility: Current realized volatility
            
        Returns:
            Dictionary with signal and metadata
        """
        regime_info = self.detect_volatility_regime(current_volatility)
        
        # Signal interpretation:
        # - EXPANDING: Reduce position size (more risk)
        # - CONTRACTING: Can maintain/increase position size (less risk)
        # - STABLE: No adjustment
        
        signal = 'NEUTRAL'
        stake_multiplier = 1.0
        
        regime = regime_info['regime']
        
        if regime == 'EXPANDING':
            signal = 'REDUCE_RISK'
            stake_multiplier = 0.7  # Reduce stake to 70%
        elif regime == 'CONTRACTING':
            signal = 'INCREASE_RISK'
            stake_multiplier = 1.2  # Increase stake to 120%
        else:
            signal = 'NEUTRAL'
            stake_multiplier = 1.0
        
        return {
            'signal': signal,
            'regime': regime,
            'stake_multiplier': stake_multiplier,
            'confidence': regime_info['confidence'],
            'forecast_mean': regime_info['forecast_mean'],
            'reason': regime_info['reason']
        }
