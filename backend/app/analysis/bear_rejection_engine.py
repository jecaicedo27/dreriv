"""
Three Red Crows Engine v4 — Genetically Optimized

GA Results (50 generations, 272K candles):
- 54.6% WR, 21.4 trades/day, +$5,359/month estimated
- STABLE: January 54.0% / February 55.3% (1.3% diff)
- Key finding: EMA bearish (EMA21 < EMA50) is the REQUIRED filter
- Relaxed pattern gates: body tolerance 80%, wick 2.5x, gap 0.50
- Blocked hours: 0, 3, 8, 9, 12, 13, 18, 20

Strategy: more trades at slightly lower WR but higher volume = more profit.
21 trades/day × 54.6% WR × 0.95 payout = significant edge.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from app.analysis.base_engine import BaseAnalysisEngine


class ThreeRedCrowsEngine(BaseAnalysisEngine):
    name = "bear_reject_v1"
    version = "4.0"
    description = "Three Red Crows v4: GA-optimized bearish pattern (54.6% WR stable)"

    # GA-optimized pattern gates
    BODY_SIZE_TOLERANCE = 0.80      # Relaxed: bodies within 80%
    MAX_WICK_BODY_RATIO = 2.50      # Relaxed: bigger wicks OK
    MAX_GAP_PCT = 0.50              # Relaxed: gaps up to 50% ATR
    MIN_BODY_VS_ATR = 0.22          # Min body
    MAX_BODY_VS_ATR = 3.04          # Max body

    # GA-optimized filters
    BAD_HOURS = {0, 3, 8, 9, 12, 13, 18, 20}
    OPTIMAL_RSI = (15, 72)
    REQUIRE_EMA_BEAR = True         # KEY filter from GA

    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        reasoning = []

        if len(df) < 50:
            return self._hold_response(["Insufficient data"])
        if len(df) < 3:
            return self._hold_response(["Need 3+ candles"])

        c1 = df.iloc[-3]
        c2 = df.iloc[-2]
        c3 = df.iloc[-1]

        o1, h1, l1, cl1 = float(c1['open']), float(c1['high']), float(c1['low']), float(c1['close'])
        o2, h2, l2, cl2 = float(c2['open']), float(c2['high']), float(c2['low']), float(c2['close'])
        o3, h3, l3, cl3 = float(c3['open']), float(c3['high']), float(c3['low']), float(c3['close'])

        rsi = float(c3.get('rsi_14', 50) or 50)
        ema_21 = float(c3.get('ema_21', 0) or 0)
        ema_50 = float(c3.get('ema_50', 0) or 0)
        macd_hist = float(c3.get('macd_histogram', 0) or 0)
        bb_upper = float(c3.get('bollinger_upper', 0) or 0)
        bb_lower = float(c3.get('bollinger_lower', 0) or 0)
        bb_middle = float(c3.get('bollinger_middle', 0) or 0)
        hurst_fast = float(c3.get('hurst_fast', 0) or 0)
        hurst_slow = float(c3.get('hurst_exponent', 0) or 0)
        momentum_5 = float(c3.get('momentum_5', 0) or 0)
        atr = float(c3.get('atr_14', 0) or 0)

        hurst_value = hurst_fast if hurst_fast > 0 else hurst_slow
        if hurst_value == 0:
            hurst_value = 0.5

        if atr <= 0:
            recent_ranges = (df['high'].tail(14).astype(float) - df['low'].tail(14).astype(float))
            atr = float(recent_ranges.mean())
        if atr <= 0:
            atr = 1.0

        current_price = cl3

        # ===== HARD GATE 1: All 3 bearish =====
        if cl1 >= o1 or cl2 >= o2 or cl3 >= o3:
            return self._hold_response(["Not 3 bearish candles"])

        # ===== HARD GATE 2: Stepping down =====
        if cl2 >= cl1 or cl3 >= cl2:
            return self._hold_response(["Not stepping down"])

        # ===== HARD GATE 3: EMA bearish (KEY from GA) =====
        if self.REQUIRE_EMA_BEAR and ema_21 > 0 and ema_50 > 0:
            if ema_21 >= ema_50:
                return self._hold_response(["EMA not bearish (GA requirement)"])

        # ===== HARD GATE 4: Body sizes =====
        body1 = o1 - cl1
        body2 = o2 - cl2
        body3 = o3 - cl3

        min_body = atr * self.MIN_BODY_VS_ATR
        max_body = atr * self.MAX_BODY_VS_ATR
        if body1 < min_body or body2 < min_body or body3 < min_body:
            return self._hold_response(["Body too small"])
        if body1 > max_body or body2 > max_body or body3 > max_body:
            return self._hold_response(["Body too large"])

        # ===== HARD GATE 5: Body similarity =====
        avg_body = (body1 + body2 + body3) / 3
        max_dev = max(
            abs(body1 - avg_body) / avg_body,
            abs(body2 - avg_body) / avg_body,
            abs(body3 - avg_body) / avg_body,
        )
        if max_dev > self.BODY_SIZE_TOLERANCE:
            return self._hold_response([f"Bodies not equal (dev={max_dev:.0%})"])

        # ===== HARD GATE 6: No huge gaps =====
        gap_tolerance = atr * self.MAX_GAP_PCT
        gap1 = abs(o2 - cl1)
        gap2 = abs(o3 - cl2)
        if gap1 > gap_tolerance or gap2 > gap_tolerance:
            return self._hold_response(["Gap too large"])

        # ===== HARD GATE 7: Wick check =====
        def wick_ratio(ov, hv, lv, cv):
            bd = abs(cv - ov)
            uw = hv - max(ov, cv)
            lw = min(ov, cv) - lv
            return (uw + lw) / max(bd, 0.01)

        wr1 = wick_ratio(o1, h1, l1, cl1)
        wr2 = wick_ratio(o2, h2, l2, cl2)
        wr3 = wick_ratio(o3, h3, l3, cl3)
        if wr1 > self.MAX_WICK_BODY_RATIO or wr2 > self.MAX_WICK_BODY_RATIO or wr3 > self.MAX_WICK_BODY_RATIO:
            return self._hold_response(["Wicks too long"])

        # ===== HARD GATE 8: RSI range =====
        if rsi < self.OPTIMAL_RSI[0] or rsi > self.OPTIMAL_RSI[1]:
            return self._hold_response([f"RSI out of range ({rsi:.0f}, need {self.OPTIMAL_RSI[0]}-{self.OPTIMAL_RSI[1]})"])

        # ===== PATTERN DETECTED =====
        reasoning.append(f"🔴🔴🔴 3 Red Crows (dev={max_dev:.0%}, RSI={rsi:.0f}, EMA↓)")

        # ===== HOUR CHECK =====
        try:
            from datetime import timedelta
            current_time = c3['open_time']
            if hasattr(current_time, 'hour'):
                hour_col = (current_time - timedelta(hours=5)).hour
            else:
                hour_col = -1
        except:
            hour_col = -1

        if hour_col in self.BAD_HOURS:
            reasoning.append(f"❌ Blocked hour ({hour_col}:00)")
            return self._hold_response(reasoning)

        # ===== CONFIDENCE SCORING =====
        confidence = 0.65  # Base

        # RSI sweet spot (30-55)
        if 30 <= rsi <= 55:
            confidence += 0.03
            reasoning.append(f"✅ RSI sweet ({rsi:.0f})")

        # MACD negative (bonus, not required)
        if macd_hist < 0:
            confidence += 0.02
            reasoning.append("✅ MACD negative")

        # Price below EMA21 (bonus)
        if current_price < ema_21 and ema_21 > 0:
            confidence += 0.02
            reasoning.append("✅ Price < EMA21")

        # Body optimal range
        avg_body_atr = avg_body / atr
        if 0.3 <= avg_body_atr <= 1.5:
            confidence += 0.02

        # Hour quality
        best_hours = {1, 10, 14, 16}
        if hour_col in best_hours:
            confidence += 0.03
            reasoning.append(f"✅ Best hour ({hour_col}:00)")

        # Low body deviation = cleaner pattern
        if max_dev < 0.30:
            confidence += 0.02
            reasoning.append("✅ Clean pattern")

        confidence = min(confidence, 0.85)
        confidence = max(confidence, 0.62)
        confidence = round(confidence, 3)

        total_drop = o1 - cl3
        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle > 0 else 0

        reasoning.append(f"PUT conf={confidence:.3f} drop={total_drop:.2f}")

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
            "hurst_signal": {"hurst": round(hurst_value, 4), "regime": "TRENDING" if hurst_value > 0.5 else "MEAN_REVERTING"},
            "indicators": {
                "rsi_14": rsi,
                "ema_21": ema_21,
                "ema_50": ema_50,
                "macd_histogram": macd_hist,
                "bb_width": round(bb_width, 5),
                "momentum_5": momentum_5,
                "body1": round(body1, 2),
                "body2": round(body2, 2),
                "body3": round(body3, 2),
                "total_drop": round(total_drop, 2),
                "avg_body_atr": round(avg_body_atr, 2),
                "body_dev": round(max_dev * 100, 1),
            }
        }

    def _hold_response(self, reasoning: list) -> Dict[str, Any]:
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
