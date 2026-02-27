"""
Three White Soldiers Engine — Data-Driven Bullish CALL Pattern

Inverse of Three Red Crows. Detects 3 consecutive bullish candles
stepping UP with equal bodies and small wicks.

Brute-force results (272K candles):
- Best hours CALL: 1, 14, 15, 19, 20, 21
- Bad hours CALL: 5, 7, 10, 13, 16, 22, 23
- MACD positive = key bullish filter (+3% WR)
- Price above EMA21 = bullish confirmation
- Body 0.3-1.5 ATR = optimal
- At best hours with emaBear + macdPos = 63% WR (contrarian bounce)

Tiered system same as Three Red Crows.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from app.analysis.base_engine import BaseAnalysisEngine


class ThreeWhiteSoldiersEngine(BaseAnalysisEngine):
    name = "bull_soldiers_v1"
    version = "1.0"
    description = "Three White Soldiers: 3 bullish candles equal bodies stepping up"

    # Pattern gates
    BODY_SIZE_TOLERANCE = 0.30
    MAX_WICK_BODY_RATIO = 1.0
    MAX_GAP_PCT = 0.15
    MIN_BODY_VS_ATR = 0.20
    MAX_BODY_VS_ATR = 2.0

    # Data-driven optimal filters (from brute force)
    GOOD_HOURS = {0, 1, 6, 14, 15, 19, 20, 21}
    BEST_HOURS = {1, 14, 19}
    BAD_HOURS = {5, 7, 10, 13, 16, 22, 23}
    OPTIMAL_RSI = (30, 60)

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

        # ===== HARD GATE 1: All 3 BULLISH (close > open) =====
        if cl1 <= o1 or cl2 <= o2 or cl3 <= o3:
            return self._hold_response(["Not 3 bullish candles"])

        # ===== HARD GATE 2: Stepping UP =====
        if cl2 <= cl1 or cl3 <= cl2:
            return self._hold_response(["Not stepping up"])

        # ===== HARD GATE 3: Body sizes =====
        body1 = cl1 - o1  # All positive since bullish
        body2 = cl2 - o2
        body3 = cl3 - o3

        min_body = atr * self.MIN_BODY_VS_ATR
        max_body = atr * self.MAX_BODY_VS_ATR
        if body1 < min_body or body2 < min_body or body3 < min_body:
            return self._hold_response(["Body too small"])
        if body1 > max_body or body2 > max_body or body3 > max_body:
            return self._hold_response(["Body too large"])

        # ===== HARD GATE 4: Body similarity =====
        avg_body = (body1 + body2 + body3) / 3
        max_dev = max(
            abs(body1 - avg_body) / avg_body,
            abs(body2 - avg_body) / avg_body,
            abs(body3 - avg_body) / avg_body,
        )
        if max_dev > self.BODY_SIZE_TOLERANCE:
            return self._hold_response([f"Bodies not equal (dev={max_dev:.0%})"])

        # ===== HARD GATE 5: No big gaps =====
        gap_tolerance = atr * self.MAX_GAP_PCT
        gap1 = abs(o2 - cl1)
        gap2 = abs(o3 - cl2)
        if gap1 > gap_tolerance or gap2 > gap_tolerance:
            return self._hold_response(["Gap too large"])

        # ===== HARD GATE 6: Small wicks =====
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

        # ===== PATTERN DETECTED =====
        reasoning.append(f"🟢🟢🟢 3 White Soldiers (bodies={body1:.2f},{body2:.2f},{body3:.2f}, dev={max_dev:.0%})")

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
            reasoning.append(f"❌ Bad hour ({hour_col}:00)")
            return self._hold_response(reasoning)

        is_good_hour = hour_col in self.GOOD_HOURS
        is_best_hour = hour_col in self.BEST_HOURS

        # ===== TIERED CONFIDENCE =====
        confidence = 0.62

        # RSI optimal
        rsi_optimal = self.OPTIMAL_RSI[0] <= rsi <= self.OPTIMAL_RSI[1]
        if rsi_optimal:
            confidence += 0.04
            reasoning.append(f"✅ RSI optimal ({rsi:.0f})")
        elif rsi > 80:
            reasoning.append(f"⚠️ RSI overbought ({rsi:.0f})")
            confidence -= 0.03
        else:
            reasoning.append(f"RSI: {rsi:.0f}")

        # MACD positive — KEY filter for CALL
        if macd_hist > 0:
            confidence += 0.04
            reasoning.append("✅ MACD positive")

        # Price above EMA21
        price_above_ema = current_price > ema_21 if ema_21 > 0 else False
        if price_above_ema:
            confidence += 0.02
            reasoning.append("✅ Price above EMA21")

        # EMA structure
        ema_bullish = ema_21 > ema_50 if (ema_21 > 0 and ema_50 > 0) else False
        if ema_bullish:
            confidence += 0.02
            reasoning.append("✅ EMA bullish")

        # Body in optimal range
        avg_body_atr = avg_body / atr
        if 0.3 <= avg_body_atr <= 1.5:
            confidence += 0.02
            reasoning.append(f"✅ Body optimal ({avg_body_atr:.1f}x ATR)")

        # Hour bonus
        if is_best_hour:
            confidence += 0.04
            reasoning.append(f"✅ Best hour ({hour_col}:00)")
        elif is_good_hour:
            confidence += 0.02
            reasoning.append(f"✅ Good hour ({hour_col}:00)")

        # Tier
        filters_hit = sum([rsi_optimal, macd_hist > 0, price_above_ema, ema_bullish])
        if is_best_hour and filters_hit >= 3:
            tier = 1
        elif is_good_hour and filters_hit >= 2:
            tier = 2
        else:
            tier = 3

        # Exhaustion guard
        if rsi >= 85:
            reasoning.append(f"RSI extreme overbought ({rsi:.1f})")
            return self._hold_response(reasoning)

        # Final
        confidence = min(confidence, 0.88)
        confidence = max(confidence, 0.60)
        confidence = round(confidence, 3)

        total_rise = cl3 - o1
        tier_labels = {1: "TIER-1 🔥", 2: "TIER-2 ✅", 3: "TIER-3 🟡"}
        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle > 0 else 0

        reasoning.append(f"{tier_labels.get(tier, 'T3')} → CALL | conf={confidence:.3f} | rise={total_rise:.2f}")

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
                "total_rise": round(total_rise, 2),
                "quality": round(confidence * 100, 1),
                "tier": tier,
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
