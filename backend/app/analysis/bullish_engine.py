"""
Bullish Breakout Engine v5 — Disciplined Bull (fewer trades, higher quality)

Designed around the recurring bullish breakout pattern in R_100:
- EMA 21 crosses above EMA 50 and diverges
- Bollinger Bands expand (volatility breakout)
- Hurst > 0.55 confirming trending regime (blended fast+slow)
- Pullback-buy logic: enters near EMA21 dips, not at peaks

All indicators are READ from pre-computed DataFrame columns (pipeline-computed).
No internal indicator computation — compliant with engine contract.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from loguru import logger

from app.analysis.base_engine import BaseAnalysisEngine


class BullishBreakoutEngine(BaseAnalysisEngine):
    """
    Bullish Breakout v5: Specialized CALL-only trending engine
    
    Philosophy: "Only trade when the bull is charging"
    - Detects bullish breakout setups (EMA cross + divergence + BB expansion)
    - Scores trend quality on a 0-100 scale
    - Identifies breakout phase: EARLY → PRIME → MATURE → EXHAUSTED
    - Only enters during EARLY and PRIME phases
    """
    
    name = "bullish_v4"
    version = "5.0"
    description = "Bullish v5: Disciplined bull — fewer trades, higher quality"
    
    # Breakout phase thresholds
    PHASE_EARLY_MAX_CANDLES = 6    # Just crossed, building momentum
    PHASE_PRIME_MAX_CANDLES = 30   # Sweet spot, strong divergence
    PHASE_MATURE_MAX_CANDLES = 60  # Still trending but getting extended
    # Above MATURE = EXHAUSTED
    
    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """Main analysis — returns CALL or HOLD, never PUT"""
        
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
        
        # Blend fast + slow: fast detects micro-regime, slow confirms macro
        if hurst_fast_val > 0 and hurst_slow_val > 0:
            hurst_value = hurst_fast_val * 0.4 + hurst_slow_val * 0.6
        elif hurst_fast_val > 0:
            hurst_value = hurst_fast_val
        elif hurst_slow_val > 0:
            hurst_value = hurst_slow_val
        else:
            hurst_value = 0.5  # Neutral default
        
        if hurst_value < hurst_min:
            reasoning.append(f"Not trending (Hurst_fast={hurst_fast_val:.3f}, slow={hurst_slow_val:.3f} < {hurst_min})")
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
        
        # ===== GATE 0: MACRO TREND — price must be clearly rising =====
        lookback = min(100, len(df) - 1)
        price_ago = float(df.iloc[-lookback]['close'])
        macro_return = (current_price - price_ago) / price_ago
        if macro_return < 0.002:  # Require positive macro trend (+0.2%)
            reasoning.append(f"Macro trend not bullish enough ({macro_return*100:.2f}% over {lookback} candles) — HOLD")
            return self._hold_response(reasoning)
        reasoning.append(f"✅ Macro uptrend ({macro_return*100:.2f}% over {lookback} bars)")
        
        # ===== GATE 1: EMAs must be bullish =====
        if ema_21 <= ema_50 or ema_50 == 0:
            reasoning.append(f"EMA21 ({ema_21:.2f}) ≤ EMA50 ({ema_50:.2f}) — NOT bullish")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ EMA21 ({ema_21:.2f}) > EMA50 ({ema_50:.2f})")
        
        # ===== GATE 2: Must be diverging =====
        if not ema_diverging:
            reasoning.append(f"EMAs converging (rate={ema_sep_rate:.4f}) — trend weakening")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ EMAs diverging (rate={ema_sep_rate:.4f})")
        
        # ===== GATE 3: Crossover must be confirmed (2+ candles) =====
        if ema_cross_age < 2:
            reasoning.append(f"Crossover too fresh ({ema_cross_age} bars)")
            return self._hold_response(reasoning)
        
        # ===== EMA Separation =====
        ema_separation = abs(ema_21 - ema_50) / (ema_50 + 1e-10)
        
        if ema_separation < 0.001:
            reasoning.append(f"EMAs too close (sep={ema_separation:.5f})")
            return self._hold_response(reasoning)
        
        # ===== BREAKOUT PHASE DETECTION =====
        if ema_cross_age <= self.PHASE_EARLY_MAX_CANDLES:
            phase = "EARLY"
            phase_bonus = 0.05  # Fresh breakout, good entry
        elif ema_cross_age <= self.PHASE_PRIME_MAX_CANDLES:
            phase = "PRIME"
            phase_bonus = 0.10  # Best phase — momentum confirmed
        else:
            phase = "MATURE"
            reasoning.append(f"Trend too mature ({ema_cross_age} candles since cross) — too late, HOLD")
            return self._hold_response(reasoning)
        
        reasoning.append(f"Phase: {phase} (cross age={ema_cross_age})")
        
        # ===== TREND QUALITY SCORE (0-100) =====
        quality = 0.0
        
        # Factor 1: EMA Separation strength (0-25 points)
        sep_score = min(ema_separation / 0.008, 1.0) * 25
        quality += sep_score
        
        # Factor 2: Price proximity to EMA21 (0-25 points) — CLOSER = BETTER
        price_above_pct = (current_price - ema_21) / ema_21 * 100
        if price_above_pct < 0:  # Below EMA21 = pullback dip
            quality += 25  # Best entry zone
            reasoning.append(f"✅ Pullback below EMA21 ({price_above_pct:.2f}%)")
        elif price_above_pct < 0.2:  # Touching EMA21
            quality += 22
            reasoning.append(f"✅ Near EMA21 ({price_above_pct:.2f}%)")
        elif price_above_pct < 0.5:  # Close to EMA21
            quality += 15
        elif price_above_pct < 1.5:
            quality += 8
        else:
            # Too far above EMA21 — HARD REJECT
            reasoning.append(f"Too far above EMA21 (+{price_above_pct:.2f}%) — wait for pullback")
            return self._hold_response(reasoning)
        
        # Factor 3: RSI momentum zone (0-20 points)
        if 45 <= rsi <= 70:
            quality += 20  # Sweet spot for bull trend
        elif 35 <= rsi <= 80:
            quality += 10
        elif rsi > 80:
            quality += 0
            reasoning.append(f"⚠️ RSI overbought ({rsi:.1f})")
        else:
            quality += 5
            reasoning.append(f"⚠️ RSI low for bullish ({rsi:.1f})")
        
        # Factor 4: MACD must be positive (HARD GATE)
        if macd_hist <= 0:
            reasoning.append(f"MACD histogram negative ({macd_hist:.4f}) — no momentum")
            return self._hold_response(reasoning)
        quality += 15
        reasoning.append(f"✅ MACD positive ({macd_hist:.4f})")
        
        # Factor 5: Bollinger Band expansion (0-10 points)
        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle else 0
        if bb_width > 0.008:
            quality += 10  # Expanding — volatility breakout
            reasoning.append(f"BB expanding (width={bb_width:.4f})")
        elif bb_width > 0.005:
            quality += 5
        else:
            reasoning.append(f"BB squeeze (width={bb_width:.4f}) — low volatility")
        
        # Factor 6: Positive momentum (0-10 points)
        if momentum_5 > 0:
            quality += 10
            reasoning.append(f"✅ Positive momentum ({momentum_5:.3f})")
        elif momentum_5 > -0.5:
            quality += 3
        
        reasoning.append(f"Trend Quality: {quality:.0f}/100")
        
        # ===== MINIMUM QUALITY GATE (v5: raised for discipline) =====
        if quality < 65:
            reasoning.append(f"Quality too low ({quality:.0f} < 65) — HOLD")
            return self._hold_response(reasoning)
        
        # ===== EXHAUSTION / SAFETY CHECKS (v5: strict RSI discipline) =====
        if rsi >= 82:
            reasoning.append(f"RSI overbought ({rsi:.1f}) — skip")
            return self._hold_response(reasoning)
        if rsi <= 55:
            reasoning.append(f"RSI too weak for bull ({rsi:.1f} <= 55) — no momentum, skip")
            return self._hold_response(reasoning)
        
        # Price far above upper Bollinger — only block if trend is weak
        if bb_upper > 0 and current_price > bb_upper * 1.005:
            if ema_separation < 0.004:
                reasoning.append(f"Price above upper BB with weak trend — overextended")
                return self._hold_response(reasoning)
            else:
                reasoning.append(f"Above upper BB but strong trend (sep={ema_separation:.5f}) — allowing")
        
        # ===== CONFIDENCE CALCULATION (v5: moderated) =====
        base_conf = 0.55
        quality_bonus = ((quality - 35) / 80) * 0.15
        confidence = base_conf + quality_bonus + phase_bonus
        sep_bonus = min(ema_separation / 0.01, 0.05)
        confidence += sep_bonus
        confidence = min(confidence, 0.78)
        confidence = round(confidence, 3)
        
        reasoning.append(f"🐂 CALL signal | conf={confidence:.3f} | quality={quality:.0f} | phase={phase}")
        
        return {
            "signal": "CALL",
            "final_signal": "CALL",
            "confidence": confidence,
            "final_confidence": confidence,
            "contract_type": "CALL",
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
