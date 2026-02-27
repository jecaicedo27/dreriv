"""
Base Analysis Engine Interface

All analysis engines must extend this class and implement the analyze() method.
This enables pluggable, swappable analysis engines that can be selected
at runtime for both simulation and live trading.

Includes a data validation layer (safe_analyze) that ensures engines
never receive NULL indicators — computes missing ones on-the-fly.
"""
from typing import Dict, Any, List
import pandas as pd
from abc import ABC, abstractmethod
from loguru import logger


# Indicators that MUST be present (non-null) for any engine to work reliably
REQUIRED_INDICATORS = [
    'ema_21', 'ema_50', 'rsi_14',
    'macd', 'macd_signal', 'macd_histogram',
    'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
    'momentum_5',
]

# Optional but highly desired — warn if missing
DESIRED_INDICATORS = [
    'hurst_fast', 'hurst_exponent', 'log_returns',
    'volume_delta', 'price_position',
    'garch_volatility_forecast',
    'ema_cross_age', 'ema_gap_rate', 'ema_diverging',
]


class BaseAnalysisEngine(ABC):
    """
    Interface that all analysis engines must implement.
    
    Each engine receives a DataFrame with OHLC + pre-computed indicators
    and returns a standardized signal dict.
    
    Use safe_analyze() instead of analyze() directly to ensure
    data quality validation and on-the-fly indicator computation.
    """
    
    name: str = "base"
    version: str = "0.0"
    description: str = "Base engine (do not use directly)"
    
    # === Trade timing (source of truth for sim + live) ===
    DURATION_CANDLES: int = 5     # How many 1-min candles the trade lasts (5 = 5 min)
    COOLDOWN_CANDLES: int = 3     # Min candles between trade entries
    ALLOW_OVERLAP: bool = False   # If True, cooldown starts from ENTRY (trades can overlap)
                                  # If False, cooldown starts from EXIT (sequential trades)

    @property
    def duration_seconds(self) -> int:
        """Duration in seconds for Deriv API (DURATION_CANDLES * 60)."""
        return self.DURATION_CANDLES * 60
    
    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """
        Analyze candle data and return trading signal.
        
        Args:
            df: DataFrame with OHLC + indicators (last 250 candles)
            symbol: Trading symbol
            **kwargs: Engine-specific params (e.g. hurst_min, hurst_max)
            
        Returns:
            Dict with keys:
                - signal: 'CALL', 'PUT', or 'HOLD'
                - confidence: float 0.0-1.0
                - contract_type: 'CALL', 'PUT', or None
                - stake_multiplier: float
                - duration: int (seconds)
                - reasoning: str
                
            May also include engine-specific keys like:
                - hurst_signal, ou_signal, garch_signal, etc.
        """
        raise NotImplementedError
    
    def safe_analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """
        Wrapper around analyze() that validates indicator data quality.
        
        1. Checks if required indicators are present and non-null in the last row
        2. If missing, computes them on-the-fly via TechnicalIndicators
        3. Logs warnings for missing desired indicators
        4. Calls analyze() with the validated/enriched DataFrame
        
        ALL callers (live bot, simulation, battles) should use this instead of analyze().
        """
        if len(df) < 50:
            return self.analyze(df, symbol, **kwargs)
        
        latest = df.iloc[-1]
        missing_required = []
        missing_desired = []
        
        # Check required indicators
        for col in REQUIRED_INDICATORS:
            if col not in df.columns or pd.isna(latest.get(col)):
                missing_required.append(col)
        
        # Check desired indicators
        for col in DESIRED_INDICATORS:
            if col not in df.columns or pd.isna(latest.get(col)):
                missing_desired.append(col)
        
        # If any indicators are missing (required OR desired), compute on-the-fly
        needs_computation = missing_required or missing_desired
        if needs_computation:
            try:
                from app.analysis.indicators import TechnicalIndicators
                window = df.tail(200) if len(df) >= 200 else df
                enriched = TechnicalIndicators.calculate_all(window)
                
                # Fill ALL missing columns (required + desired) from enriched
                all_missing = missing_required + missing_desired
                df = df.copy()
                for col in all_missing:
                    if col in enriched.columns:
                        df.loc[enriched.index, col] = enriched[col]
                
                filled = [c for c in all_missing if c in enriched.columns]
                still_missing_req = [c for c in missing_required if c not in enriched.columns]
                
                if filled:
                    logger.debug(
                        f"📊 [{self.name}] Computed {len(filled)} missing indicators on-the-fly: "
                        f"{', '.join(filled)}"
                    )
                if still_missing_req:
                    logger.warning(
                        f"⛔ [{self.name}] BLOCKED — indicators unavailable: {', '.join(still_missing_req)}"
                    )
                    return {
                        "signal": "HOLD", "final_signal": "HOLD",
                        "confidence": 0.0, "final_confidence": 0.0,
                        "contract_type": None, "suggested_stake_multiplier": 1.0,
                        "duration": 300, "entry_price": 0,
                        "reasoning": f"⛔ Blocked: missing indicators: {', '.join(still_missing_req)}",
                        "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
                        "indicators": {},
                        "data_quality": f"BLOCKED — {len(still_missing_req)} required indicators unavailable",
                    }
                
                # Update missing lists after computation
                missing_required = still_missing_req
                missing_desired = [c for c in missing_desired if c not in enriched.columns]
                
            except Exception as e:
                if missing_required:
                    logger.warning(f"⛔ [{self.name}] Failed to compute missing indicators — BLOCKED: {e}")
                    return {
                        "signal": "HOLD", "final_signal": "HOLD",
                        "confidence": 0.0, "final_confidence": 0.0,
                        "contract_type": None, "suggested_stake_multiplier": 1.0,
                        "duration": 300, "entry_price": 0,
                        "reasoning": f"⛔ Blocked: failed to compute indicators: {e}",
                        "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
                        "indicators": {},
                        "data_quality": "BLOCKED — indicator computation failed",
                    }
                else:
                    logger.debug(f"📊 [{self.name}] Could not compute desired indicators: {e}")
        
        # Add data quality metadata to kwargs
        kwargs['_data_quality'] = {
            'required_missing': len(missing_required),
            'required_computed': len(missing_required) - len([
                c for c in missing_required 
                if c not in df.columns or pd.isna(df.iloc[-1].get(c))
            ]),
            'desired_missing': len(missing_desired),
        }
        
        result = self.analyze(df, symbol, **kwargs)
        
        # Annotate result with data quality info if there were issues
        if missing_required or missing_desired:
            quality_note = []
            if missing_required:
                quality_note.append(f"computed {len(missing_required)} indicators on-the-fly")
            if missing_desired:
                quality_note.append(f"{len(missing_desired)} desired indicators missing")
            result['data_quality'] = " | ".join(quality_note)
        
        return result
    
    def get_info(self) -> Dict[str, str]:
        """Return engine metadata for UI display."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
        }
