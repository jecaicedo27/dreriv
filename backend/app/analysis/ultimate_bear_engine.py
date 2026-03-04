"""                    
Ultimate Bear Engine v5 — Sell-the-Rally PUT Engine

Strategy: "Sell the rally" — when price rallies above SMA5
and prints a clean bearish candle, short it.

Sweep-optimized (2,016 combos, full dataset, cooldown=3):
- 55.8% WR, 936 trades (~34/day), +$82 PnL (0.95 payout)
- Key: body≥0.33, wick≤0.80, RSI 40-75, rally≥0.1σ
- No hour/day blocking — R_100 trades 24/7
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from app.analysis.base_engine import BaseAnalysisEngine


class UltimateBearEngine(BaseAnalysisEngine):
    name = "bearish_v5"
    version = "5.0"
    description = "Ultimate Bear v5: Sell-the-rally PUT (mirror of bullish_v5)"

    # Sweep-optimized parameters (champion from 2,016 combos)
    MIN_BODY_ATR = 0.33   # Relaxed for more volume
    MAX_BODY_ATR = 3.23
    MAX_WICK_RATIO = 0.80  # Tightest filter — only clean rejections
    OPTIMAL_RSI = (40, 75)  # Narrowed — sweet spot
    MIN_RALLY_SIGMA = 0.1  # Minimum rally depth above SMA5 in ATR units

    # No hour blocking — R_100 trades 24/7

    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        reasoning = []

        if len(df) < 50:
            return self._hold_response(["Insufficient data"])

        curr = df.iloc[-1]

        o1 = float(curr['open'])
        h1 = float(curr['high'])
        l1 = float(curr['low'])
        c1 = float(curr['close'])

        rsi = float(curr.get('rsi_14', 50) or 50)
        ema_21 = float(curr.get('ema_21', 0) or 0)
        ema_50 = float(curr.get('ema_50', 0) or 0)
        macd_hist = float(curr.get('macd_histogram', 0) or 0)
        bb_upper = float(curr.get('bollinger_upper', 0) or 0)
        bb_lower = float(curr.get('bollinger_lower', 0) or 0)
        bb_middle = float(curr.get('bollinger_middle', 0) or 0)
        hurst_fast = float(curr.get('hurst_fast', 0) or 0)
        hurst_slow = float(curr.get('hurst_exponent', 0) or 0)
        momentum_5 = float(curr.get('momentum_5', 0) or 0)
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

        # ===== GATE 1: Must be BEARISH candle (mirror: C < O) =====
        if c1 >= o1:
            return self._hold_response(["Not bearish"])

        body = o1 - c1  # Bearish body = open - close
        body_atr = body / atr

        # ===== GATE 2: Body in range (0.33-3.23 ATR) =====
        if body_atr < self.MIN_BODY_ATR or body_atr > self.MAX_BODY_ATR:
            return self._hold_response([f"Body out of range ({body_atr:.2f})"])

        # ===== GATE 3: Wick ratio (max 1.61) =====
        uw = h1 - o1   # Upper wick for bearish = high - open
        lw = c1 - l1   # Lower wick for bearish = close - low
        wick_rat = (uw + lw) / max(body, 0.01)
        if wick_rat > self.MAX_WICK_RATIO:
            return self._hold_response(["Wicks too large"])

        # ===== GATE 4: TREND_5 UP (KEY — selling the rally!) =====
        # Price must be ABOVE its 5-period SMA = short-term rally
        closes = df['close'].tail(6).astype(float).values
        if len(closes) >= 6:
            sma5 = closes[-6:-1].mean()  # SMA of previous 5 candles
            if current_price <= sma5:
                return self._hold_response(["No rally (price below SMA5)"])
            # Check minimum rally depth
            rally_sigma = (current_price - sma5) / atr
            if rally_sigma < self.MIN_RALLY_SIGMA:
                return self._hold_response([f"Rally too weak ({rally_sigma:.2f}σ < {self.MIN_RALLY_SIGMA})"])
        else:
            return self._hold_response(["Not enough data for SMA5"])

        # ===== GATE 5: RSI range =====
        if rsi < self.OPTIMAL_RSI[0] or rsi > self.OPTIMAL_RSI[1]:
            return self._hold_response([f"RSI {rsi:.0f} out of range"])

        # ===== PATTERN DETECTED — PUT! =====
        rally_pct = (current_price - sma5) / atr
        reasoning.append(f"🔴 Sell-the-Rally (body={body_atr:.2f}ATR, rally={rally_pct:.1f}σ, RSI={rsi:.0f})")

        # ===== CONFIDENCE SCORING (mirrored) =====
        confidence = 0.65

        # Deeper rally = higher confidence
        if rally_pct > 0.5:
            confidence += 0.03
            reasoning.append(f"✅ Deep rally ({rally_pct:.1f}σ)")

        # EMA bearish structure bonus (mirror: ema_21 < ema_50)
        if ema_21 < ema_50 and ema_21 > 0 and ema_50 > 0:
            confidence += 0.02
            reasoning.append("✅ EMA bearish")

        # MACD negative bonus (mirror)
        if macd_hist < 0:
            confidence += 0.02
            reasoning.append("✅ MACD-")

        # RSI overbought (mirror: RSI > 60)
        if rsi > 60:
            confidence += 0.03
            reasoning.append(f"✅ RSI overbought ({rsi:.0f})")

        # Momentum turning negative (mirror)
        if momentum_5 < 0:
            confidence += 0.02

        # Near BB upper band (mirror)
        if bb_lower > 0 and bb_upper > 0:
            bb_pos = (current_price - bb_lower) / (bb_upper - bb_lower + 1e-10)
            if bb_pos > 0.7:
                confidence += 0.03
                reasoning.append("✅ Near BB upper")

        confidence = min(confidence, 0.85)
        confidence = max(confidence, 0.62)
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
                "body_atr": round(body_atr, 3),
                "wick_ratio": round(wick_rat, 2),
                "rally_sigma": round(rally_pct, 2),
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
