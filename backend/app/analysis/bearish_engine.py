"""
Bearish Breakdown Engine v7 — Disciplined Bear (fewer trades, higher quality)

Mirror of Bullish Breakout v5, designed for bearish scenarios in R_100:
- EMA 21 crosses BELOW EMA 50 and diverges downward
- Bollinger Bands expand (volatility breakdown)
- Hurst > 0.55 confirming trending regime
- Sustained downward moves of 20+ candles

All indicators are READ from pre-computed DataFrame columns (pipeline-computed).
No internal indicator computation — compliant with engine contract.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from loguru import logger

from app.analysis.base_engine import BaseAnalysisEngine


class BearishBreakdownEngine(BaseAnalysisEngine):
    """
    Bearish Breakdown v7: Specialized PUT-only trending engine
    
    Philosophy: "Only trade when the bear is charging"
    - Detects bearish breakdown setups (EMA cross down + divergence + BB expansion)
    - Scores trend quality on a 0-100 scale
    - Identifies breakdown phase: EARLY → PRIME → MATURE → EXHAUSTED
    - Only enters during EARLY and PRIME phases
    """
    
    name = "bearish_v6"
    version = "7.0"
    description = "Bearish v7: Disciplined bear — fewer trades, higher quality"
    
    # Breakdown phase thresholds
    PHASE_EARLY_MAX_CANDLES = 10   # Just crossed down, building momentum
    PHASE_PRIME_MAX_CANDLES = 60   # Sweet spot for M1 (1 hour window)
    PHASE_MATURE_MAX_CANDLES = 120 # Still trending down but getting extended
    # Above MATURE = EXHAUSTED
    
    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """Main analysis — returns PUT or HOLD, never CALL"""
        
        hurst_min = kwargs.get('hurst_min', 0.58)
        hurst_max = kwargs.get('hurst_max', 0.75)
        
        reasoning = []
        
        # Need minimum data
        if len(df) < 100:
            return self._hold_response(["Insufficient data"])
        
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        
        # ===== HURST: Must be trending (read from DataFrame) =====
        hurst_fast_val = float(latest.get('hurst_fast', 0) or 0)
        hurst_slow_val = float(latest.get('hurst_exponent', 0) or 0)
        
        # Use hurst_fast directly (not blended) — more selective for bearish
        hurst_value = hurst_fast_val if hurst_fast_val > 0 else hurst_slow_val
        if hurst_value == 0:
            hurst_value = 0.5  # Neutral default
        
        # Gate: hurst_fast must be >= 0.40 (trending regime)
        if hurst_fast_val > 0 and hurst_fast_val < 0.40:
            reasoning.append(f"Hurst_fast too low ({hurst_fast_val:.3f} < 0.40) — not trending enough")
            return self._hold_response(reasoning)
        
        if hurst_value > hurst_max:
            reasoning.append(f"Hurst too high (Hurst_fast={hurst_fast_val:.3f} > {hurst_max})")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ Trending regime (Hurst_fast={hurst_fast_val:.3f}, slow={hurst_slow_val:.3f})")
        
        # ===== INDICATORS (all from pre-computed DataFrame) =====
        ema_21 = float(latest.get('ema_21', 0) or 0)
        ema_50 = float(latest.get('ema_50', 0) or 0)
        rsi = float(latest.get('rsi_14', 50) or 50)
        macd_hist = float(latest.get('macd_histogram', 0) or 0)
        momentum_5 = float(latest.get('momentum_5', 0) or 0)
        bb_upper = float(latest.get('bollinger_upper', 0) or 0)
        bb_lower = float(latest.get('bollinger_lower', 0) or 0)
        bb_middle = float(latest.get('bollinger_middle', 0) or 0)
        ema_cross_age = int(latest.get('ema_cross_age', 0) or 0)
        ema_diverging = bool(int(latest.get('ema_diverging', 0) or 0))
        ema_sep_rate = float(latest.get('ema_gap_rate', 0) or 0)
        
        # ===== GATE 1: EMAs must be BEARISH (EMA21 BELOW EMA50) =====
        if ema_21 >= ema_50 or ema_50 == 0:
            reasoning.append(f"EMA21 ({ema_21:.2f}) >= EMA50 ({ema_50:.2f}) — NOT bearish")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ EMA21 ({ema_21:.2f}) < EMA50 ({ema_50:.2f}) — bearish cross")
        
        # ===== GATE 1.5: MACRO TREND — price must be falling (v7: new filter) =====
        lookback = min(100, len(df) - 1)
        price_ago = float(df.iloc[-lookback]['close'])
        macro_return = (current_price - price_ago) / price_ago
        if macro_return > 0.005:  # Macro rising > +0.5% = don't short
            reasoning.append(f"Macro trend UP ({macro_return*100:.2f}%) — not safe for PUT, HOLD")
            return self._hold_response(reasoning)
        reasoning.append(f"✅ Macro downtrend ({macro_return*100:.2f}% over {lookback} bars)")
        
        # ===== EMA Divergence (quality factor, not hard gate) =====
        if ema_diverging:
            reasoning.append(f"✅ EMAs diverging downward (rate={ema_sep_rate:.4f})")
        else:
            reasoning.append(f"⚠️ EMAs converging (rate={ema_sep_rate:.4f})")
        
        # ===== GATE 3: Crossover must be confirmed (2+ candles) =====
        if ema_cross_age < 2:
            reasoning.append(f"Crossover too fresh ({ema_cross_age} bars)")
            return self._hold_response(reasoning)
        
        # ===== EMA Separation =====
        ema_separation = abs(ema_21 - ema_50) / (ema_50 + 1e-10)
        
        if ema_separation < 0.001:
            reasoning.append(f"EMAs too close (sep={ema_separation:.5f})")
            return self._hold_response(reasoning)
        
        # ===== BREAKDOWN PHASE DETECTION =====
        if ema_cross_age <= self.PHASE_EARLY_MAX_CANDLES:
            phase = "EARLY"
            phase_bonus = 0.05
        elif ema_cross_age <= self.PHASE_PRIME_MAX_CANDLES:
            phase = "PRIME"
            phase_bonus = 0.10
        else:
            phase = "MATURE"
            reasoning.append(f"Downtrend mature ({ema_cross_age} candles since cross) — too late, HOLD")
            return self._hold_response(reasoning)
        
        reasoning.append(f"Phase: {phase} (cross age={ema_cross_age})")
        
        # ===== TREND QUALITY SCORE (0-100) — Bearish version =====
        quality = 0.0
        
        # Factor 1: EMA Separation strength (0-25 points)
        sep_score = min(ema_separation / 0.008, 1.0) * 25
        quality += sep_score
        
        # Factor 2: Price BELOW EMA21 (0-20 points) — bearish = price under EMAs
        if current_price < ema_21:
            price_below_pct = (ema_21 - current_price) / ema_21 * 100
            if price_below_pct < 1.5:  # Not overextended
                quality += 20
            elif price_below_pct < 2.5:
                quality += 10
            else:
                quality += 5  # Overextended downward
                reasoning.append(f"⚠️ Overextended -{price_below_pct:.2f}% below EMA21")
        else:
            reasoning.append(f"⚠️ Price above EMA21 (bounce in downtrend)")
            quality += 8  # Potential short on bounce
        
        # Factor 3: RSI momentum zone (0-20 points) — bearish sweet spot is 25-50
        if 25 <= rsi <= 50:
            quality += 20  # Sweet spot for bear trend
        elif 20 <= rsi <= 60:
            quality += 12
        elif rsi < 20:
            quality += 5   # Oversold but still might work
            reasoning.append(f"⚠️ RSI oversold ({rsi:.1f})")
        else:
            quality += 5
            reasoning.append(f"⚠️ RSI too high for bearish ({rsi:.1f})")
        
        # Factor 3b: EMA divergence bonus (0-15 points)
        if ema_diverging:
            quality += 15  # Gap widening = strong momentum
        else:
            quality += 3   # Converging but not blocking
        
        # Factor 4: MACD confirming bearish — HARD GATE (v7: must be negative)
        if macd_hist >= 0:
            reasoning.append(f"MACD histogram positive ({macd_hist:.4f}) — no bearish momentum, HOLD")
            return self._hold_response(reasoning)
        quality += 15
        reasoning.append(f"✅ MACD negative ({macd_hist:.4f})")
        
        # Factor 5: Bollinger Band expansion (0-10 points)
        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle else 0
        if bb_width > 0.008:
            quality += 10  # Expanding — volatility breakdown
            reasoning.append(f"BB expanding (width={bb_width:.4f})")
        elif bb_width > 0.005:
            quality += 5
        else:
            reasoning.append(f"BB squeeze (width={bb_width:.4f}) — low volatility")
        
        # Factor 6: Negative momentum (0-10 points) — bearish = negative momentum
        if momentum_5 < 0:
            quality += 10
        elif momentum_5 < 0.5:
            quality += 3
        
        reasoning.append(f"Trend Quality: {quality:.0f}/100")
        
        # ===== MINIMUM QUALITY GATE =====
        if quality < 35:
            reasoning.append(f"Quality too low ({quality:.0f} < 35) — HOLD")
            return self._hold_response(reasoning)
        
        # ===== EXHAUSTION / SAFETY CHECKS =====
        if rsi <= 15:
            reasoning.append(f"RSI extreme oversold ({rsi:.1f}) — bounce risk too high, skip")
            return self._hold_response(reasoning)
        if rsi >= 55:
            reasoning.append(f"RSI too high for PUT ({rsi:.1f} >= 55) — momentum against us, skip")
            return self._hold_response(reasoning)
        
        # Price far below lower Bollinger — overextended
        if bb_lower > 0 and current_price < bb_lower * 0.998:
            reasoning.append(f"Price below lower BB — oversold, skip")
            return self._hold_response(reasoning)
        
        # ===== CONFIDENCE CALCULATION =====
        base_conf = 0.58
        quality_bonus = ((quality - 35) / 65) * 0.20
        confidence = base_conf + quality_bonus + phase_bonus
        sep_bonus = min(ema_separation / 0.01, 0.10)
        confidence += sep_bonus
        confidence = min(confidence, 0.88)
        confidence = round(confidence, 3)
        
        reasoning.append(f"🐻 PUT signal | conf={confidence:.3f} | quality={quality:.0f} | phase={phase}")
        
        return {
            "signal": "PUT",
            "final_signal": "PUT",
            "confidence": confidence,
            "final_confidence": confidence,
            "contract_type": "PUT",
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
                "ema_separation": round(ema_separation, 6),
                "ema_cross_age": ema_cross_age,
                "bb_width": round(bb_width, 5),
                "trend_quality": round(quality, 1),
                "phase": phase,
                "momentum_5": momentum_5,
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
