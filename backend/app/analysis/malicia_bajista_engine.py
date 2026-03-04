"""
Malicia Bajista Engine v1 — Trend-Riding PUT Machine

Philosophy: The bearish mirror of "Malicia Indígena" — street-smart intuition
to recognize when the market is CLEARLY going down and ride the wave with PUT.

Strategy:
- PUT ONLY — never CALL, never fight the downtrend
- Detects strong downtrends via INVERTED EMA alignment + negative momentum
- Trades EVERY qualifying minute candle during downtrend (aggressive)
- Stops immediately when trend weakens (risk management)
- No complicated patterns — just pure bearish trend reading

Gates (all must pass):
1. EMA9 < EMA21 < EMA50 (triple EMA downtrend alignment)
2. Current price below EMA21 (in the downtrend, not above it)
3. EMA gap meaningful (EMA21 - EMA9 > threshold)
4. Momentum_5 negative (recent acceleration DOWN)
5. Current candle must be bearish or neutral (not fighting the trend)
6. RSI between 15-55 (not oversold=bounce risk, not overbought=no downtrend)
7. MACD histogram negative (momentum confirmation)
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from app.analysis.base_engine import BaseAnalysisEngine


class MaliciaBajistaEngine(BaseAnalysisEngine):
    name = "malicia_bajista_v1"
    version = "1.0"
    description = "Malicia Bajista: PUT agresivo en tendencia bajista (ride the bear wave)"

    # === Aggressive timing for trend riding ===
    DURATION_CANDLES = 2   # 2-min trades (short bursts in downtrend)
    COOLDOWN_CANDLES = 1   # 1-min cooldown between entries
    ALLOW_OVERLAP = True   # Can fire new trade while previous is still open

    # Downtrend detection thresholds (INVERTED from bullish)
    RSI_MIN = 15       # Below 15 = extreme oversold (bounce risk)
    RSI_MAX = 40       # Above 40 = no downtrend (RSI 40-55 lost -$58K in 194d)
    RSI_SWEET = (20, 30)  # Sweet spot for bearish (50.9% WR, breakeven)

    # Minimum EMA gap (as fraction of ATR) to confirm trend
    MIN_EMA_GAP_ATR = 0.05  # EMA21-EMA9 gap must be > 5% of ATR

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

        # ===== GATE 1: INVERTED EMA ALIGNMENT (EMA50 > EMA21 > EMA9) =====
        # Core bearish signal — EMAs stacked downward
        if ema_9 <= 0 or ema_21 <= 0 or ema_50 <= 0:
            return self._hold_response(["EMAs not computed"])

        if not (ema_50 > ema_21 > ema_9):
            return self._hold_response(["No downtrend (EMA50>21>9 failed)"])

        # ===== GATE 2: Price below EMA21 =====
        # We must be IN the downtrend, not bouncing above
        if current_price > ema_21:
            return self._hold_response(["Price above EMA21 (not in downtrend)"])

        # ===== GATE 3: EMA spread filter (LA MALICIA BAJISTA) =====
        # EMA21 - EMA9 = how far EMA9 has dropped below EMA21
        # Sweet spot: 3.0-5.0 pts (spread 4.0 = 53.6% WR, +$8.9/trade)
        ema_spread_abs = ema_21 - ema_9  # absolute points (bearish = positive)
        MIN_EMA_SPREAD = 3.0   # below = EMAs converging, trend dying
        MAX_EMA_SPREAD = 5.0   # above = overextended, bounce risk
        
        if ema_spread_abs < MIN_EMA_SPREAD:
            return self._hold_response([f"EMAs too close ({ema_spread_abs:.1f} pts < {MIN_EMA_SPREAD})"])
        if ema_spread_abs > MAX_EMA_SPREAD:
            return self._hold_response([f"EMAs overextended ({ema_spread_abs:.1f} pts > {MAX_EMA_SPREAD})"])
        
        ema_gap_21_9 = ema_spread_abs / atr  # keep for confidence scoring

        # ===== GATE 4: Momentum NEGATIVE =====
        # Price must be accelerating DOWN
        if momentum_5 >= 0:
            return self._hold_response(["Momentum positive (downtrend weakening)"])

        # ===== GATE 5: Current candle NOT strong bullish reversal =====
        # Small green candles in downtrend are normal bounces — only block big reversals
        if c1 > o1:
            body_bull = (c1 - o1) / atr
            if body_bull > 0.8:
                # Big bullish candle = possible reversal, HOLD
                return self._hold_response([f"Strong bullish candle ({body_bull:.2f} ATR)"])

        # ===== GATE 6: RSI in downtrend range =====
        if rsi < self.RSI_MIN:
            return self._hold_response([f"RSI extreme oversold ({rsi:.0f}) — bounce risk"])
        if rsi > self.RSI_MAX:
            return self._hold_response([f"RSI too high ({rsi:.0f}) — no downtrend"])

        # ===== GATE 7: MACD confirmation (must be negative for bearish) =====
        if macd_hist > 0.3 * atr:
            return self._hold_response([f"MACD too positive ({macd_hist:.3f}) — bullish momentum"])

        # ===== ALL GATES PASSED — PUT SIGNAL! =====
        ema_gap_21_50 = (ema_50 - ema_21) / atr
        reasoning.append(f"🐻 BAJISTA: Downtrend confirmed (EMA gap={ema_gap_21_9:.2f}σ)")

        # ===== CONFIDENCE SCORING =====
        confidence = 0.66  # Base confidence

        # Stronger EMA separation = stronger downtrend
        if ema_gap_21_9 > 0.15:
            confidence += 0.03
            reasoning.append(f"✅ Strong EMA21-9 gap ({ema_gap_21_9:.2f})")
        if ema_gap_21_50 > 0.10:
            confidence += 0.02
            reasoning.append(f"✅ EMA50-21 gap ({ema_gap_21_50:.2f})")

        # RSI sweet spot for bearish (30-45 is ideal downtrend territory)
        if self.RSI_SWEET[0] <= rsi <= self.RSI_SWEET[1]:
            confidence += 0.03
            reasoning.append(f"✅ RSI bearish sweet ({rsi:.0f})")

        # Bearish candle bonus
        if c1 < o1:
            body_atr = (o1 - c1) / atr
            if body_atr > 0.3:
                confidence += 0.02
                reasoning.append(f"✅ Bearish candle ({body_atr:.2f}ATR)")

        # MACD deepening (acceleration of decline)
        prev_macd = float(prev.get('macd_histogram', 0) or 0)
        if macd_hist < prev_macd < 0:
            confidence += 0.02
            reasoning.append("✅ MACD accelerating down")

        # Momentum double confirm (5 AND 10 negative)
        if momentum_10 is not None and momentum_10 < 0:
            confidence += 0.02
            reasoning.append("✅ Momentum 5+10 negative")

        # Hurst trending = more predictable
        if hurst_value > 0.55:
            confidence += 0.02
            reasoning.append(f"✅ Hurst trending ({hurst_value:.2f})")

        # BB position: price in lower half = healthy downtrend
        if bb_upper > 0 and bb_lower > 0:
            bb_pos = (current_price - bb_lower) / (bb_upper - bb_lower + 1e-10)
            if 0.15 < bb_pos < 0.5:
                confidence += 0.02
                reasoning.append(f"✅ BB lower half ({bb_pos:.2f})")

        confidence = min(confidence, 0.88)
        confidence = max(confidence, 0.63)
        confidence = round(confidence, 3)

        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle > 0 else 0

        reasoning.append(f"PUT conf={confidence:.3f}")

        return {
            "signal": "PUT",
            "final_signal": "PUT",
            "confidence": confidence,
            "final_confidence": confidence,
            "contract_type": "PUT",
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
                "ema_gap_21_9": round(ema_gap_21_9, 4),
                "ema_gap_50_21": round(ema_gap_21_50, 4),
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
