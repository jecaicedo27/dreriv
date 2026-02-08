---
name: statistical-trading-models
description: "Statistical models for algorithmic trading on synthetic indices. Use when implementing GARCH volatility forecasting, Ornstein-Uhlenbeck mean reversion models, Weibull spike prediction for Crash/Boom indices, Hidden Markov Models for regime detection, or Hurst exponent calculation. Covers scipy, statsmodels, arch, and hmmlearn libraries."
---

# Statistical Trading Models for Synthetic Indices

## Overview

Four specialized statistical models optimized for Deriv synthetic indices trading: GARCH for volatility forecasting, Ornstein-Uhlenbeck for mean reversion, Weibull for spike prediction, and HMM for regime detection. Each model includes fitting, prediction, and signal generation.

## When to Use This Skill

- Implementing volatility forecasting (GARCH)
- Building mean reversion strategies for Volatility indices (O-U process)
- Predicting spike probability in Crash/Boom indices (Weibull)
- Detecting market regime changes (HMM)
- Calculating Hurst exponent for mean-reversion vs trending detection

## Dependencies

```
pip install arch statsmodels scipy hmmlearn numpy
```

## Model 1: GARCH(1,1) — Volatility Forecasting

**Purpose:** Predict if volatility will EXPAND or CONTRACT. Critical for position sizing and strategy selection.

```python
from arch import arch_model
import numpy as np

class GARCHModel:
    def __init__(self):
        self.model = None
        self.fitted = None
    
    def fit(self, returns: np.ndarray):
        """Fit GARCH(1,1) on percentage returns."""
        # arch library expects percentage returns
        self.model = arch_model(
            returns * 100,
            vol='Garch', p=1, q=1,
            mean='Zero',          # No mean model needed for vol forecast
            dist='StudentsT'      # Fat tails for synthetic indices
        )
        self.fitted = self.model.fit(disp='off', show_warning=False)
        return self
    
    def forecast(self, horizon: int = 5) -> dict:
        """Forecast volatility for next N periods."""
        if self.fitted is None:
            return None
        
        fc = self.fitted.forecast(horizon=horizon)
        current_vol = float(self.fitted.conditional_volatility.iloc[-1])
        forecast_vols = fc.variance.values[-1]  # Array of forecasted variances
        forecast_vol = float(np.sqrt(forecast_vols[-1]))  # Last period's vol
        
        return {
            "current_vol": current_vol,
            "forecast_vol": forecast_vol,
            "vol_trend": "expanding" if forecast_vol > current_vol * 1.05 else
                        "contracting" if forecast_vol < current_vol * 0.95 else "stable",
            "vol_ratio": forecast_vol / current_vol if current_vol > 0 else 1.0,
            "forecast_series": [float(np.sqrt(v)) for v in forecast_vols]
        }
    
    def signal(self) -> dict:
        """Trading signal based on volatility forecast."""
        fc = self.forecast()
        if fc is None:
            return {"action": "none", "reason": "model not fitted"}
        
        if fc["vol_ratio"] > 1.5:
            return {"action": "reduce_exposure", "vol_state": "rapid_expansion", **fc}
        elif fc["vol_ratio"] > 1.15:
            return {"action": "caution", "vol_state": "expanding", **fc}
        elif fc["vol_ratio"] < 0.85:
            return {"action": "opportunity", "vol_state": "contracting", **fc}
        else:
            return {"action": "normal", "vol_state": "stable", **fc}
```

**Refit frequency:** Every 500 new candles or daily, whichever comes first.

## Model 2: Ornstein-Uhlenbeck — Mean Reversion

**Purpose:** Volatility indices (R_75, R_100) maintain a target volatility, creating natural mean reversion. O-U models this mathematically.

**The process:** dX = θ(μ - X)dt + σdW
- θ = speed of reversion (higher = reverts faster)
- μ = equilibrium level (long-term mean)
- σ = volatility of the process
- Half-life = ln(2) / θ

```python
import numpy as np

class OrnsteinUhlenbeck:
    def __init__(self):
        self.theta = None  # Speed of reversion
        self.mu = None     # Equilibrium level
        self.sigma = None  # Process volatility
    
    def fit(self, prices: np.ndarray, dt: float = 1.0) -> dict:
        """Estimate O-U parameters via OLS regression."""
        x = np.array(prices, dtype=float)
        x_lag = x[:-1]
        x_lead = x[1:]
        
        # Linear regression: x[t+1] = a + b*x[t] + noise
        n = len(x_lag)
        b = (n * np.sum(x_lag * x_lead) - np.sum(x_lag) * np.sum(x_lead)) / \
            (n * np.sum(x_lag**2) - np.sum(x_lag)**2)
        a = np.mean(x_lead) - b * np.mean(x_lag)
        
        residuals = x_lead - (a + b * x_lag)
        
        if b <= 0 or b >= 1:
            # No mean reversion detected
            self.theta = 0
            self.mu = np.mean(x)
            self.sigma = np.std(np.diff(x))
        else:
            self.theta = -np.log(b) / dt
            self.mu = a / (1 - b)
            sigma_eq = np.std(residuals)
            self.sigma = sigma_eq * np.sqrt(-2 * np.log(b) / (dt * (1 - b**2)))
        
        half_life = np.log(2) / self.theta if self.theta > 0 else float('inf')
        
        return {
            "theta": self.theta,
            "mu": self.mu,
            "sigma": self.sigma,
            "half_life": half_life
        }
    
    def signal(self, current_price: float) -> dict:
        """Generate trading signal based on deviation from equilibrium."""
        if self.theta == 0:
            return {"signal": "NEUTRAL", "strength": 0, "reason": "no mean reversion"}
        
        deviation = (current_price - self.mu) / (self.sigma / np.sqrt(2 * self.theta))
        half_life = np.log(2) / self.theta
        
        # Expected price after half_life periods
        expected = self.mu + (current_price - self.mu) * np.exp(-self.theta * half_life)
        expected_return = (expected - current_price) / current_price
        
        if deviation > 2.0:
            return {"signal": "SELL", "strength": min(abs(deviation)/3, 1.0),
                    "deviation_sigma": deviation, "half_life": half_life,
                    "expected_return": expected_return}
        elif deviation < -2.0:
            return {"signal": "BUY", "strength": min(abs(deviation)/3, 1.0),
                    "deviation_sigma": deviation, "half_life": half_life,
                    "expected_return": expected_return}
        else:
            return {"signal": "NEUTRAL", "strength": 0,
                    "deviation_sigma": deviation, "half_life": half_life}
```

**Refit frequency:** Every 200 candles. Use at least 500 candles for fitting.

## Model 3: Weibull — Spike Prediction for Crash/Boom

**Purpose:** Crash 1000 has spikes every ~1000 ticks on average. The probability of a spike INCREASES as more ticks pass without one (unlike Poisson where it's constant).

```python
from scipy import stats
import numpy as np

class WeibullSpikeModel:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.shape = None   # Weibull shape (>1 means increasing hazard)
        self.scale = None   # Weibull scale
        self.mean = None
        self.std = None
    
    def fit(self, intervals: list[int]):
        """Fit Weibull distribution to historical spike intervals."""
        arr = np.array(intervals, dtype=float)
        self.shape, _, self.scale = stats.weibull_min.fit(arr, floc=0)
        self.mean = np.mean(arr)
        self.std = np.std(arr)
        return {
            "shape": self.shape,
            "scale": self.scale,
            "mean_interval": self.mean,
            "std_interval": self.std,
            "increasing_hazard": self.shape > 1  # True if prob increases with time
        }
    
    def hazard_rate(self, ticks_since_last: int) -> float:
        """Instantaneous probability of spike: h(t) = f(t)/S(t)"""
        t = float(ticks_since_last)
        pdf = stats.weibull_min.pdf(t, self.shape, loc=0, scale=self.scale)
        sf = stats.weibull_min.sf(t, self.shape, loc=0, scale=self.scale)
        return pdf / sf if sf > 0 else 1.0
    
    def prob_in_next_n(self, ticks_since_last: int, n: int = 100) -> float:
        """P(spike in next n ticks | already waited t ticks)"""
        t = float(ticks_since_last)
        sf_now = stats.weibull_min.sf(t, self.shape, loc=0, scale=self.scale)
        sf_future = stats.weibull_min.sf(t + n, self.shape, loc=0, scale=self.scale)
        return 1 - (sf_future / sf_now) if sf_now > 0 else 1.0
    
    def zone(self, ticks_since_last: int) -> str:
        """Classify spike probability zone."""
        cdf = stats.weibull_min.cdf(ticks_since_last, self.shape, loc=0, scale=self.scale)
        if cdf < 0.3: return "safe"
        elif cdf < 0.6: return "normal"
        elif cdf < 0.8: return "elevated"
        elif cdf < 0.95: return "hot"
        else: return "critical"
    
    def signal(self, ticks_since_last: int) -> dict:
        """Trading signal for Crash/Boom."""
        z = self.zone(ticks_since_last)
        prob100 = self.prob_in_next_n(ticks_since_last, 100)
        prob500 = self.prob_in_next_n(ticks_since_last, 500)
        hr = self.hazard_rate(ticks_since_last)
        
        return {
            "zone": z,
            "hazard_rate": hr,
            "prob_next_100": prob100,
            "prob_next_500": prob500,
            "ticks_since_spike": ticks_since_last,
            "mean_interval": self.mean,
            "recommendation": "trade_spike" if z in ("hot", "critical") else "wait"
        }
```

**Spike detection (for building training data):**
```python
def detect_spike(prices, threshold_sigma=4):
    """Detect if the last tick was a spike."""
    if len(prices) < 100:
        return False
    changes = np.abs(np.diff(prices[-100:])) / prices[-100:-1]
    std = np.std(changes[:-1])
    last_change = abs(prices[-1] - prices[-2]) / prices[-2]
    return last_change > threshold_sigma * std
```

## Model 4: Hidden Markov Model — Regime Detection

**Purpose:** Detect current market regime to choose the RIGHT strategy.

```python
from hmmlearn import hmm
import numpy as np

class RegimeDetector:
    REGIME_MAP = {0: "trending_up", 1: "trending_down", 
                  2: "ranging_tight", 3: "volatile_expansion"}
    
    def __init__(self):
        self.model = hmm.GaussianHMM(
            n_components=4, covariance_type="diag",
            n_iter=200, random_state=42
        )
        self.fitted = False
    
    def fit(self, returns: np.ndarray, volatility: np.ndarray):
        """Train on returns + volatility features. Need 500+ observations."""
        X = np.column_stack([returns, volatility])
        self.model.fit(X)
        self.fitted = True
        self._label_states()
    
    def _label_states(self):
        """Assign regime names based on learned state means."""
        means = self.model.means_
        ret_means = means[:, 0]
        vol_means = means[:, 1]
        
        mapping = {}
        mapping[int(np.argmax(ret_means))] = "trending_up"
        mapping[int(np.argmin(ret_means))] = "trending_down"
        remaining = [i for i in range(4) if i not in mapping]
        if len(remaining) >= 2:
            vols = [vol_means[r] for r in remaining]
            mapping[remaining[int(np.argmin(vols))]] = "ranging_tight"
            mapping[remaining[int(np.argmax(vols))]] = "volatile_expansion"
        self.REGIME_MAP = mapping
    
    def predict(self, returns: np.ndarray, volatility: np.ndarray) -> tuple[str, float]:
        """Returns (regime_name, confidence)."""
        if not self.fitted:
            return "unknown", 0.0
        X = np.column_stack([returns[-50:], volatility[-50:]])
        states = self.model.predict(X)
        probs = self.model.predict_proba(X)
        current = states[-1]
        confidence = float(probs[-1][current])
        return self.REGIME_MAP.get(current, "unknown"), confidence
```

**Refit frequency:** Daily (in nightly batch job). Needs 500+ observations.

## Hurst Exponent

```python
def hurst_exponent(prices: np.ndarray, max_lag: int = 100) -> float:
    """
    Estimate Hurst exponent.
    H < 0.5: Mean-reverting
    H = 0.5: Random walk (NO edge)
    H > 0.5: Trending
    """
    lags = range(2, min(max_lag, len(prices) // 2))
    tau = [np.std(np.subtract(prices[lag:], prices[:-lag])) for lag in lags]
    
    log_lags = np.log(list(lags))
    log_tau = np.log(tau)
    
    # Linear regression
    poly = np.polyfit(log_lags, log_tau, 1)
    return poly[0]  # Slope = Hurst exponent
```

**Interpretation for trading:**
- H < 0.45: Strong mean reversion → use O-U model
- 0.45 ≤ H ≤ 0.55: Random walk → REDUCE trading frequency, no edge
- H > 0.55: Trending → use momentum/breakout strategies

## Strategy Selection Matrix

| Regime | Hurst | Volatility | Strategy | Models |
|--------|-------|-----------|----------|--------|
| ranging_tight | < 0.45 | Stable | Mean reversion | O-U |
| ranging_tight | 0.45-0.55 | Stable | REDUCE trades | — |
| trending_up | > 0.55 | Stable | Buy dips | SMC + indicators |
| trending_down | > 0.55 | Stable | Sell rallies | SMC + indicators |
| volatile_expansion | Any | Expanding | STOP trading | GARCH alert |
| pre_spike (Crash/Boom) | Any | Any | Spike play | Weibull |
