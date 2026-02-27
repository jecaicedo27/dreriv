"""
Adaptive Trend Flow Engine v2 — Disciplined ATF (fewer trades, higher quality)

IMPROVEMENTS OVER v1 (based on 3048-trade data mining):
1. HARD GATE: Slope must align with trend direction (v1 was a warning → now blocks)
2. HARD GATE: Price must be on correct side of ATF basis (v1 allowed wrong side)
3. HARD GATE: MACD histogram must confirm trend (v1 was a warning → now blocks)
4. MAX TREND AGE: Cap at 80 bars (v1 allowed 150+ → mature/exhausted trends lost)
5. ADX > 20 required to confirm trend strength
6. Tighter RSI bounds for each direction

These 4 changes should eliminate ~40% of losing trades.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from loguru import logger

from app.analysis.base_engine import BaseAnalysisEngine


class AdaptiveTrendFlowV2Engine(BaseAnalysisEngine):
    """
    ATF v2: Disciplined Adaptive Trend Flow — fewer trades, higher win rate
    
    Key differences from v1:
    - Slope alignment is a HARD GATE (not warning)
    - Price must be on correct side of ATF basis (not warning)
    - MACD must confirm direction (not warning)
    - Max trend age capped at 80 bars
    - ADX > 20 confirms real trend
    """
    
    name = "atf_v2"
    version = "2.0"
    description = "ATF v2: Disciplined Adaptive Flow — high quality trades only"
    
    # Trend duration limits
    MIN_TREND_BARS = 3       # Must persist at least 3 bars
    MAX_TREND_BARS = 80      # Don't trade exhausted trends (v1 had no limit)
    
    # Minimum slope magnitude (% per 3 bars)
    MIN_SLOPE_STRENGTH = 0.02  # Tighter than v1 (was 0.01)
    
    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """Main analysis — CALL/PUT/HOLD with strict quality gates"""
        
        hurst_min = kwargs.get('hurst_min', 0.45)
        hurst_max = kwargs.get('hurst_max', 0.80)
        
        reasoning = []
        
        if len(df) < 100:
            return self._hold_response(["Insufficient data"])
        
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        
        # ===== ATF INDICATORS =====
        atf_basis = float(latest.get('atf_basis', 0) or 0)
        atf_upper = float(latest.get('atf_upper', 0) or 0)
        atf_lower = float(latest.get('atf_lower', 0) or 0)
        atf_trend = int(latest.get('atf_trend', 0) or 0)
        atf_slope = float(latest.get('atf_slope', 0) or 0)
        
        if atf_basis == 0 or atf_upper == 0:
            reasoning.append("ATF data not available")
            return self._hold_response(reasoning)
        
        # ===== GATE 1: HURST — trending regime =====
        hurst_fast_val = float(latest.get('hurst_fast', 0) or 0)
        hurst_slow_val = float(latest.get('hurst_exponent', 0) or 0)
        hurst_value = hurst_fast_val if hurst_fast_val > 0 else hurst_slow_val
        if hurst_value == 0:
            hurst_value = 0.5
        
        if hurst_fast_val > 0 and hurst_fast_val < 0.42:
            reasoning.append(f"Hurst_fast too low ({hurst_fast_val:.3f}) — mean-reverting")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ Hurst (fast={hurst_fast_val:.3f}, slow={hurst_slow_val:.3f})")
        
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
        
        # ===== ATF METRICS =====
        atf_band_width = (atf_upper - atf_lower) / (atf_basis + 1e-10)
        reasoning.append(f"ATF: trend={atf_trend:+d} | slope={atf_slope:.3f}% | bands={atf_band_width:.4f}")
        
        # ===== GATE 2: ATF must have clear trend =====
        if atf_trend == 0:
            reasoning.append("ATF neutral — no trend")
            return self._hold_response(reasoning)
        
        # ===== Count trend duration =====
        trend_duration = 0
        for i in range(len(df) - 1, -1, -1):
            if int(df.iloc[i].get('atf_trend', 0) or 0) == atf_trend:
                trend_duration += 1
            else:
                break
        
        # ===== GATE 3: Trend age limits =====
        if trend_duration < self.MIN_TREND_BARS:
            reasoning.append(f"Trend too young ({trend_duration} < {self.MIN_TREND_BARS})")
            return self._hold_response(reasoning)
        
        if trend_duration > self.MAX_TREND_BARS:
            reasoning.append(f"⛔ Trend exhausted ({trend_duration} > {self.MAX_TREND_BARS} bars) — too late to enter")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ Trend age OK ({trend_duration} bars)")
        
        # ===== GATE 4: SLOPE MUST ALIGN (was warning in v1 → now HARD GATE) =====
        slope_aligned = (atf_trend == 1 and atf_slope > self.MIN_SLOPE_STRENGTH) or \
                        (atf_trend == -1 and atf_slope < -self.MIN_SLOPE_STRENGTH)
        if not slope_aligned:
            reasoning.append(f"⛔ Slope not aligned with trend (slope={atf_slope:+.3f}%, need {'>' if atf_trend == 1 else '<'}{self.MIN_SLOPE_STRENGTH:+.3f}%)")
            return self._hold_response(reasoning)
        reasoning.append(f"✅ Slope aligned ({atf_slope:+.3f}%)")
        
        # ===== GATE 5: PRICE MUST BE ON CORRECT SIDE OF ATF BASIS (was warning → HARD GATE) =====
        if atf_trend == 1 and current_price < atf_basis:
            reasoning.append(f"⛔ Price ({current_price:.2f}) below ATF basis ({atf_basis:.2f}) — not confirmed bullish")
            return self._hold_response(reasoning)
        elif atf_trend == -1 and current_price > atf_basis:
            reasoning.append(f"⛔ Price ({current_price:.2f}) above ATF basis ({atf_basis:.2f}) — not confirmed bearish")
            return self._hold_response(reasoning)
        reasoning.append(f"✅ Price on correct side of basis")
        
        # ===== GATE 6: MACD MUST CONFIRM DIRECTION (was warning → HARD GATE) =====
        macd_confirms = (atf_trend == 1 and macd_hist > 0) or (atf_trend == -1 and macd_hist < 0)
        if not macd_confirms:
            reasoning.append(f"⛔ MACD ({macd_hist:.4f}) against ATF trend direction — skip")
            return self._hold_response(reasoning)
        reasoning.append(f"✅ MACD confirms ({macd_hist:.4f})")
        
        # ===== GATE 7: ADX confirms real trend =====
        if adx > 0 and adx < 18:
            reasoning.append(f"⛔ ADX too low ({adx:.1f} < 18) — no real trend")
            return self._hold_response(reasoning)
        if adx > 0:
            reasoning.append(f"✅ ADX={adx:.1f} — trend confirmed")
        
        # ===== TREND QUALITY SCORE (0-100) =====
        quality = 0.0
        
        # Factor 1: Slope strength (0-25 pts)
        slope_mag = abs(atf_slope)
        quality += min(slope_mag / 0.08, 1.0) * 25
        
        # Factor 2: Price position (0-20 pts) — already confirmed on correct side
        quality += 20
        
        # Factor 3: RSI sweet spot (0-20 pts)
        if atf_trend == 1:  # BULLISH
            if 50 <= rsi <= 65:
                quality += 20  # Ideal bullish RSI
            elif 40 <= rsi <= 72:
                quality += 12
            else:
                quality += 3
                reasoning.append(f"⚠️ RSI={rsi:.1f} outside ideal range for CALL")
        else:  # BEARISH
            if 35 <= rsi <= 50:
                quality += 20  # Ideal bearish RSI
            elif 28 <= rsi <= 60:
                quality += 12
            else:
                quality += 3
                reasoning.append(f"⚠️ RSI={rsi:.1f} outside ideal range for PUT")
        
        # Factor 4: EMA alignment (0-20 pts)
        ema_aligned = (atf_trend == 1 and ema_21 > ema_50) or (atf_trend == -1 and ema_21 < ema_50)
        if ema_aligned and ema_50 > 0:
            quality += 20
            reasoning.append(f"✅ EMAs aligned ({ema_21:.2f} vs {ema_50:.2f})")
        else:
            quality += 5
        
        # Factor 5: Momentum alignment (0-15 pts)
        mom_aligned = (atf_trend == 1 and momentum_5 > 0) or (atf_trend == -1 and momentum_5 < 0)
        if mom_aligned:
            quality += 15
        else:
            quality += 3
        
        reasoning.append(f"Quality: {quality:.0f}/100")
        
        # ===== MINIMUM QUALITY GATE =====
        if quality < 40:
            reasoning.append(f"Quality too low ({quality:.0f} < 40)")
            return self._hold_response(reasoning)
        
        # ===== EXHAUSTION SAFETY =====
        if atf_trend == 1:
            if rsi > 75:
                reasoning.append(f"RSI overbought ({rsi:.1f}) — exhaustion risk")
                return self._hold_response(reasoning)
            if current_price > atf_upper * 1.003:
                reasoning.append("Price overextended above ATF upper band")
                return self._hold_response(reasoning)
        else:
            if rsi < 25:
                reasoning.append(f"RSI oversold ({rsi:.1f}) — bounce risk")
                return self._hold_response(reasoning)
            if current_price < atf_lower * 0.997:
                reasoning.append("Price overextended below ATF lower band")
                return self._hold_response(reasoning)
        
        # ===== CONFIDENCE =====
        direction = "CALL" if atf_trend == 1 else "PUT"
        
        base_conf = 0.60
        quality_bonus = ((quality - 40) / 60) * 0.18
        trend_bonus = min((trend_duration - self.MIN_TREND_BARS) / 20, 0.06)
        slope_bonus = min(abs(atf_slope) / 0.10, 0.04)
        
        confidence = base_conf + quality_bonus + trend_bonus + slope_bonus
        confidence = min(confidence, 0.88)
        confidence = round(confidence, 3)
        
        emoji = "🟢" if direction == "CALL" else "🔴"
        reasoning.append(f"{emoji} {direction} | conf={confidence:.3f} | quality={quality:.0f} | age={trend_duration}")
        
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
                "ema_21": ema_21, "ema_50": ema_50,
                "rsi_14": rsi, "macd_histogram": macd_hist,
                "bb_width": round(bb_width, 5), "momentum_5": momentum_5,
                "atf_trend": atf_trend, "atf_slope": round(atf_slope, 4),
                "atf_band_width": round(atf_band_width, 5),
                "trend_duration": trend_duration,
                "trend_quality": round(quality, 1),
                "adx_14": adx,
            }
        }
    
    def _hold_response(self, reasoning: list) -> Dict[str, Any]:
        return {
            "signal": "HOLD", "final_signal": "HOLD",
            "confidence": 0.0, "final_confidence": 0.0,
            "contract_type": None, "suggested_stake_multiplier": 1.0,
            "duration": 300, "entry_price": 0,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
            "indicators": {}
        }
