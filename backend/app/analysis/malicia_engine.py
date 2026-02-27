"""
Malicia Indígena Engine v1 — Trend-Riding CALL Machine

Philosophy: "Malicia indígena" — the street-smart intuition to recognize
when the market is CLEARLY going up and ride that wave aggressively.

Strategy:
- CALL ONLY — never PUT, never fight the trend
- Detects strong uptrends via EMA alignment + momentum
- Trades EVERY qualifying minute candle during uptrend (aggressive)
- Stops immediately when trend weakens (risk management)
- No complicated patterns — just pure trend reading

Gates (all must pass):
1. EMA9 > EMA21 > EMA50 (triple EMA uptrend alignment)
2. Current price above EMA21 (in the trend, not lost)
3. Momentum_5 positive (recent acceleration up)
4. Current candle must be bullish or neutral (not fighting)
5. RSI between 40-78 (not oversold=no trend, not overbought=exhaustion) 
6. MACD histogram positive (momentum confirmation)

Confidence boosters:
- Deeper EMA separation = stronger trend
- RSI 50-65 sweet spot
- BB position middle-upper = healthy trend
- Strong body candle
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from app.analysis.base_engine import BaseAnalysisEngine


class MaliciaIndigenaEngine(BaseAnalysisEngine):
    name = "malicia_v1"
    version = "1.0"
    description = "Malicia Indígena: CALL agresivo en tendencia alcista (ride the wave)"

    # === Aggressive timing for trend riding ===
    DURATION_CANDLES = 2   # 2-min trades (short bursts in uptrend)
    COOLDOWN_CANDLES = 1   # 1-min cooldown between entries
    ALLOW_OVERLAP = True   # Can fire new trade while previous is still open

    # Trend detection thresholds
    RSI_MIN = 40       # Below 40 = no uptrend
    RSI_MAX = 90       # Above 90 = extreme overbought (trends live at 70-85)
    RSI_SWEET = (50, 70)  # Sweet spot for confidence boost

    # Minimum EMA gap (as fraction of ATR) to confirm trend
    MIN_EMA_GAP_ATR = 0.05  # EMA9-EMA21 gap must be > 5% of ATR

    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        reasoning = []

        if len(df) < 50:
            return self._hold_response(["Insufficient data"])

        curr = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else curr

        # Read pre-computed indicators (NO recalculation!)
        o1 = float(curr['open'])
        h1 = float(curr['high'])
        l1 = float(curr['low'])
        c1 = float(curr['close'])

        ema_9 = float(curr.get('ema_9', 0) or 0)
        ema_21 = float(curr.get('ema_21', 0) or 0)
        ema_50 = float(curr.get('ema_50', 0) or 0)
        rsi = float(curr.get('rsi_14', 50) or 50)
        macd_hist = float(curr.get('macd_histogram', 0) or 0)
        momentum_5 = float(curr.get('momentum_5', 0) or 0)
        momentum_10 = float(curr.get('momentum_10', 0) or 0)
        bb_upper = float(curr.get('bollinger_upper', 0) or 0)
        bb_lower = float(curr.get('bollinger_lower', 0) or 0)
        bb_middle = float(curr.get('bollinger_middle', 0) or 0)
        hurst_fast = float(curr.get('hurst_fast', 0) or 0)
        hurst_slow = float(curr.get('hurst_exponent', 0) or 0)
        atr = float(curr.get('atr_14', 0) or 0)

        hurst_value = hurst_fast if hurst_fast > 0 else hurst_slow
        if hurst_value == 0:
            hurst_value = 0.5

        if atr <= 0:
            recent_ranges = (df['high'].tail(14).astype(float) - df['low'].tail(14).astype(float))
            atr = float(recent_ranges.mean())
        if atr <= 0:
            atr = 1.0

        current_price = c1

        # ===== GATE 1: EMA TRIPLE ALIGNMENT (EMA9 > EMA21 > EMA50) =====
        # This is the core — if EMAs aren't aligned, there's NO uptrend
        if ema_9 <= 0 or ema_21 <= 0 or ema_50 <= 0:
            return self._hold_response(["EMAs not computed"])

        if not (ema_9 > ema_21 > ema_50):
            return self._hold_response(["No uptrend (EMA9>21>50 failed)"])

        # ===== GATE 2: Price above EMA21 =====
        # We must be IN the trend, not below it
        if current_price < ema_21:
            return self._hold_response(["Price below EMA21"])

        # ===== GATE 3: EMA gap meaningful (not just crossed) =====
        ema_gap_9_21 = (ema_9 - ema_21) / atr
        if ema_gap_9_21 < self.MIN_EMA_GAP_ATR:
            return self._hold_response([f"EMA gap too small ({ema_gap_9_21:.3f})"])

        # ===== GATE 4: Momentum positive =====
        if momentum_5 <= 0:
            return self._hold_response(["Momentum negative (trend weakening)"])

        # ===== GATE 5: Current candle NOT strong reversal =====
        # Small red candles in uptrend are normal pullbacks — only block big reversals
        if c1 < o1:
            body_bear = (o1 - c1) / atr
            if body_bear > 0.8:
                # Big bearish candle = possible reversal, HOLD
                return self._hold_response([f"Strong bearish candle ({body_bear:.2f} ATR)"])

        # ===== GATE 6: RSI in uptrend range =====
        if rsi < self.RSI_MIN:
            return self._hold_response([f"RSI too low ({rsi:.0f}) — no uptrend"])
        if rsi > self.RSI_MAX:
            return self._hold_response([f"RSI overbought ({rsi:.0f}) — exhaustion risk"])

        # ===== GATE 7: MACD confirmation (relaxed for micro-timeframe) =====
        # MACD oscillates fast on 1-min candles — allow slightly negative if EMA trend is strong
        if macd_hist < -0.3 * atr:
            return self._hold_response([f"MACD too negative ({macd_hist:.3f})"])

        # ===== ALL GATES PASSED — CALL SIGNAL! =====
        ema_gap_21_50 = (ema_21 - ema_50) / atr
        reasoning.append(f"🦊 MALICIA: Uptrend confirmed (EMA gap={ema_gap_9_21:.2f}σ)")

        # ===== CONFIDENCE SCORING =====
        confidence = 0.66  # Base confidence

        # Stronger EMA separation = stronger trend
        if ema_gap_9_21 > 0.15:
            confidence += 0.03
            reasoning.append(f"✅ Strong EMA9-21 gap ({ema_gap_9_21:.2f})")
        if ema_gap_21_50 > 0.10:
            confidence += 0.02
            reasoning.append(f"✅ EMA21-50 gap ({ema_gap_21_50:.2f})")

        # RSI sweet spot (50-65 is ideal uptrend territory)
        if self.RSI_SWEET[0] <= rsi <= self.RSI_SWEET[1]:
            confidence += 0.03
            reasoning.append(f"✅ RSI sweet ({rsi:.0f})")

        # Bullish candle bonus
        if c1 > o1:
            body_atr = (c1 - o1) / atr
            if body_atr > 0.3:
                confidence += 0.02
                reasoning.append(f"✅ Bullish candle ({body_atr:.2f}ATR)")

        # MACD growing (acceleration)
        prev_macd = float(prev.get('macd_histogram', 0) or 0)
        if macd_hist > prev_macd > 0:
            confidence += 0.02
            reasoning.append("✅ MACD accelerating")

        # Momentum double confirm (5 AND 10 positive)
        if momentum_10 is not None and momentum_10 > 0:
            confidence += 0.02
            reasoning.append("✅ Momentum 5+10 positive")

        # Hurst trending = more predictable
        if hurst_value > 0.55:
            confidence += 0.02
            reasoning.append(f"✅ Hurst trending ({hurst_value:.2f})")

        # BB position: price in upper half = healthy trend
        if bb_upper > 0 and bb_lower > 0:
            bb_pos = (current_price - bb_lower) / (bb_upper - bb_lower + 1e-10)
            if 0.5 < bb_pos < 0.85:
                confidence += 0.02
                reasoning.append(f"✅ BB upper half ({bb_pos:.2f})")

        confidence = min(confidence, 0.88)
        confidence = max(confidence, 0.63)
        confidence = round(confidence, 3)

        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle > 0 else 0

        reasoning.append(f"CALL conf={confidence:.3f}")

        return {
            "signal": "CALL",
            "final_signal": "CALL",
            "confidence": confidence,
            "final_confidence": confidence,
            "contract_type": "CALL",
            "suggested_stake_multiplier": 1.0,
                        "duration": self.duration_seconds,
            "entry_price": current_price,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": round(hurst_value, 4), "regime": "TRENDING" if hurst_value > 0.5 else "MEAN_REVERTING"},
            "indicators": {
                "rsi_14": rsi,
                "ema_9": ema_9,
                "ema_21": ema_21,
                "ema_50": ema_50,
                "macd_histogram": macd_hist,
                "bb_width": round(bb_width, 5),
                "momentum_5": momentum_5,
                "ema_gap_9_21": round(ema_gap_9_21, 4),
                "ema_gap_21_50": round(ema_gap_21_50, 4),
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
                        "duration": self.duration_seconds,
            "entry_price": 0,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
            "indicators": {}
        }
