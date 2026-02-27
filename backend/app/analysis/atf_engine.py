"""
Adaptive Trend Flow Engine v1 — ATF-based trend following

Based on the QuantAlgo "Adaptive Trend Flow" indicator:
- Dual EMA basis (fast=10, slow=14) creates an adaptive centerline
- Volatility bands (stddev * 2.0) filter noise during consolidation
- Trend state (+1/-1) persists until opposite band is breached
- Slope of basis confirms momentum direction and strength

Trades BOTH directions (CALL and PUT) based on ATF trend + confirmations.

All indicators are READ from pre-computed DataFrame columns (pipeline-computed).
No internal indicator computation — compliant with engine contract.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from loguru import logger

from app.analysis.base_engine import BaseAnalysisEngine


class AdaptiveTrendFlowEngine(BaseAnalysisEngine):
    """
    ATF v1: Adaptive Trend Flow — volatility-adjusted trend following
    
    Philosophy: "Stay on the right side of the adaptive flow"
    - Uses ATF bands to detect confirmed trends (close breaks above/below)
    - Slope of ATF basis confirms momentum direction
    - RSI confirms trend is not exhausted
    - MACD histogram aligns with trend direction
    - Hurst confirms trending regime
    """
    
    name = "atf_v1"
    version = "1.0"
    description = "ATF v1: Adaptive Trend Flow — dual-direction trend following"
    
    # Minimum bars the ATF trend must persist before trading
    MIN_TREND_BARS = 3
    
    # Slope thresholds (% per 3 bars)
    MIN_SLOPE_STRENGTH = 0.01  # Minimum slope to confirm momentum
    
    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """Main analysis — returns CALL, PUT, or HOLD based on ATF trend"""
        
        hurst_min = kwargs.get('hurst_min', 0.45)
        hurst_max = kwargs.get('hurst_max', 0.80)
        
        reasoning = []
        
        # Need minimum data
        if len(df) < 100:
            return self._hold_response(["Insufficient data"])
        
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        
        # ===== ATF INDICATORS (pre-computed by pipeline) =====
        atf_basis = float(latest.get('atf_basis', 0) or 0)
        atf_upper = float(latest.get('atf_upper', 0) or 0)
        atf_lower = float(latest.get('atf_lower', 0) or 0)
        atf_trend = int(latest.get('atf_trend', 0) or 0)
        atf_slope = float(latest.get('atf_slope', 0) or 0)
        
        # ===== GATE 1: ATF data must be available =====
        if atf_basis == 0 or atf_upper == 0:
            reasoning.append("ATF data not available — waiting for pipeline")
            return self._hold_response(reasoning)
        
        # ===== GATE 2: HURST — need trending regime =====
        hurst_fast_val = float(latest.get('hurst_fast', 0) or 0)
        hurst_slow_val = float(latest.get('hurst_exponent', 0) or 0)
        hurst_value = hurst_fast_val if hurst_fast_val > 0 else hurst_slow_val
        if hurst_value == 0:
            hurst_value = 0.5
        
        if hurst_fast_val > 0 and hurst_fast_val < 0.40:
            reasoning.append(f"Hurst_fast too low ({hurst_fast_val:.3f}) — mean-reverting, skip")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ Hurst OK (fast={hurst_fast_val:.3f}, slow={hurst_slow_val:.3f})")
        
        # ===== SUPPORTING INDICATORS =====
        ema_21 = float(latest.get('ema_21', 0) or 0)
        ema_50 = float(latest.get('ema_50', 0) or 0)
        rsi = float(latest.get('rsi_14', 50) or 50)
        macd_hist = float(latest.get('macd_histogram', 0) or 0)
        momentum_5 = float(latest.get('momentum_5', 0) or 0)
        bb_upper = float(latest.get('bollinger_upper', 0) or 0)
        bb_lower = float(latest.get('bollinger_lower', 0) or 0)
        bb_middle = float(latest.get('bollinger_middle', 0) or 0)
        adx = float(latest.get('adx_14', 0) or 0)
        
        # ===== ATF BAND WIDTH (measures volatility state) =====
        atf_band_width = (atf_upper - atf_lower) / (atf_basis + 1e-10)
        reasoning.append(f"ATF: trend={atf_trend:+d} | slope={atf_slope:.3f}% | bands={atf_band_width:.4f}")
        
        # ===== GATE 3: ATF must have a clear trend =====
        if atf_trend == 0:
            reasoning.append("ATF neutral — no confirmed trend direction")
            return self._hold_response(reasoning)
        
        # Count how long ATF trend has persisted
        trend_duration = 0
        for i in range(len(df) - 1, -1, -1):
            if int(df.iloc[i].get('atf_trend', 0) or 0) == atf_trend:
                trend_duration += 1
            else:
                break
        
        if trend_duration < self.MIN_TREND_BARS:
            reasoning.append(f"ATF trend too young ({trend_duration} < {self.MIN_TREND_BARS} bars)")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ ATF trend persisted {trend_duration} bars")
        
        # ===== TREND QUALITY SCORING (0-100) =====
        quality = 0.0
        
        # Factor 1: Slope alignment (0-25 pts)
        slope_aligned = (atf_trend == 1 and atf_slope > 0) or (atf_trend == -1 and atf_slope < 0)
        if slope_aligned:
            slope_mag = abs(atf_slope)
            quality += min(slope_mag / 0.05, 1.0) * 25  # Max 25 pts
            reasoning.append(f"✅ Slope aligned ({atf_slope:+.3f}%)")
        else:
            reasoning.append(f"⚠️ Slope diverging from trend ({atf_slope:+.3f}%)")
            quality += 5
        
        # Factor 2: Price position relative to ATF basis (0-20 pts)
        if atf_trend == 1 and current_price > atf_basis:
            quality += 20
        elif atf_trend == -1 and current_price < atf_basis:
            quality += 20
        else:
            quality += 5  # Price on wrong side of basis
            reasoning.append(f"⚠️ Price on wrong side of ATF basis")
        
        # Factor 3: RSI confirmation (0-20 pts)
        if atf_trend == 1:  # BULLISH
            if 45 <= rsi <= 70:
                quality += 20  # Sweet spot for bull
            elif 35 <= rsi <= 80:
                quality += 10
            else:
                quality += 3
        else:  # BEARISH
            if 30 <= rsi <= 55:
                quality += 20  # Sweet spot for bear
            elif 20 <= rsi <= 65:
                quality += 10
            else:
                quality += 3
        
        # Factor 4: MACD alignment (0-20 pts)
        macd_aligned = (atf_trend == 1 and macd_hist > 0) or (atf_trend == -1 and macd_hist < 0)
        if macd_aligned:
            quality += 20
            reasoning.append(f"✅ MACD aligned ({macd_hist:.4f})")
        else:
            quality += 3
            reasoning.append(f"⚠️ MACD against trend ({macd_hist:.4f})")
        
        # Factor 5: EMA structure (0-15 pts)
        ema_aligned = (atf_trend == 1 and ema_21 > ema_50) or (atf_trend == -1 and ema_21 < ema_50)
        if ema_aligned and ema_50 > 0:
            quality += 15
            reasoning.append(f"✅ EMAs aligned (21={ema_21:.2f} vs 50={ema_50:.2f})")
        else:
            quality += 3
        
        reasoning.append(f"Trend Quality: {quality:.0f}/100")
        
        # ===== MINIMUM QUALITY GATE =====
        if quality < 35:
            reasoning.append(f"Quality too low ({quality:.0f} < 35) — HOLD")
            return self._hold_response(reasoning)
        
        # ===== EXHAUSTION SAFETY CHECKS =====
        if atf_trend == 1:
            # Bullish exhaustion
            if rsi > 78:
                reasoning.append(f"RSI overbought ({rsi:.1f}) — exhaustion risk")
                return self._hold_response(reasoning)
            # Price too far above upper band
            if current_price > atf_upper * 1.005:
                reasoning.append("Price overextended above ATF upper band")
                return self._hold_response(reasoning)
        else:
            # Bearish exhaustion
            if rsi < 22:
                reasoning.append(f"RSI oversold ({rsi:.1f}) — bounce risk")
                return self._hold_response(reasoning)
            # Price too far below lower band
            if current_price < atf_lower * 0.995:
                reasoning.append("Price overextended below ATF lower band")
                return self._hold_response(reasoning)
        
        # ===== CONFIDENCE CALCULATION =====
        direction = "CALL" if atf_trend == 1 else "PUT"
        
        base_conf = 0.58
        quality_bonus = ((quality - 35) / 65) * 0.20
        trend_duration_bonus = min((trend_duration - self.MIN_TREND_BARS) / 15, 0.08)
        slope_bonus = min(abs(atf_slope) / 0.10, 0.06)
        
        confidence = base_conf + quality_bonus + trend_duration_bonus + slope_bonus
        confidence = min(confidence, 0.88)
        confidence = round(confidence, 3)
        
        emoji = "🟢" if direction == "CALL" else "🔴"
        reasoning.append(f"{emoji} {direction} signal | conf={confidence:.3f} | quality={quality:.0f} | duration={trend_duration}")
        
        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle else 0
        
        return {
            "signal": direction,
            "final_signal": direction,
            "confidence": confidence,
            "final_confidence": confidence,
            "contract_type": direction,
            "suggested_stake_multiplier": 1.0,
            "duration": 300,
            "entry_price": current_price,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": round(hurst_value, 4), "regime": "TRENDING"},
            "indicators": {
                "ema_21": ema_21,
                "ema_50": ema_50,
                "rsi_14": rsi,
                "macd_histogram": macd_hist,
                "bb_width": round(bb_width, 5),
                "momentum_5": momentum_5,
                "atf_trend": atf_trend,
                "atf_slope": round(atf_slope, 4),
                "atf_band_width": round(atf_band_width, 5),
                "trend_duration": trend_duration,
                "trend_quality": round(quality, 1),
            }
        }
    
    def _hold_response(self, reasoning: list) -> Dict[str, Any]:
        """Standard HOLD response"""
        return {
            "signal": "HOLD",
            "final_signal": "HOLD",
            "confidence": 0.0,
            "final_confidence": 0.0,
            "contract_type": None,
            "suggested_stake_multiplier": 1.0,
            "duration": 300,
            "entry_price": 0,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
            "indicators": {}
        }
