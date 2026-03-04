"""
Forex Buy-the-Dip Engine v1 — Adapted from UltimateBullEngine (bullish_v5)

The bullish_v5 engine for R_100 synthetics achieves 54.4% WR with a
"buy the dip" strategy: detect a short-term dip (price below SMA5)
with a bullish bounce candle, and go CALL.

This Forex adaptation:
- CALL ONLY: Expert in buying dips (sell-the-rally will be a separate engine)
- Session filter: Only trades during London (07-16 UTC) or NY (13-22 UTC)
- Same GA-optimized gates: body ATR 0.33-3.23, wick max 1.61, RSI 18-70
- ATR fallback scaled for Forex pips (0.0005 vs 1.0)
- Hurst gate ≥ 0.50 (needs some trending behavior)
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from app.analysis.base_engine import BaseAnalysisEngine


# UTC hours of active Forex sessions
LONDON_OPEN_UTC  = 7
LONDON_CLOSE_UTC = 16
NY_OPEN_UTC      = 13
NY_CLOSE_UTC     = 22


class ForexBuyDipEngine(BaseAnalysisEngine):
    name = "forex_buydip_v1"
    version = "1.0"
    description = "Forex Buy-Dip v1: Buy-the-dip CALL expert (EUR/USD)"

    # GA-optimized parameters (from bullish_v5)
    MIN_BODY_ATR = 0.33
    MAX_BODY_ATR = 3.23
    MAX_WICK_RATIO = 1.61
    OPTIMAL_RSI = (18, 70)

    # Trade timing
    DURATION_CANDLES = 5    # 5 min trades
    COOLDOWN_CANDLES = 7    # 7 candles between entries (same as bullish_v5)
    HURST_MIN = 0.50

    def analyze(self, df: pd.DataFrame, symbol: str = "frxEURUSD", **kwargs) -> Dict[str, Any]:
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
            atr = 0.0005  # Typical EURUSD 1-min ATR fallback

        current_price = c1

        # ===== GATE 1: SESSION FILTER =====
        try:
            current_time = curr['open_time']
            if hasattr(current_time, 'hour'):
                hour_utc = current_time.hour
            else:
                hour_utc = -1
        except Exception:
            hour_utc = -1

        if hour_utc >= 0:
            in_london = LONDON_OPEN_UTC <= hour_utc < LONDON_CLOSE_UTC
            in_ny = NY_OPEN_UTC <= hour_utc < NY_CLOSE_UTC
            if not (in_london or in_ny):
                return self._hold_response([f"Outside active sessions (UTC {hour_utc:02d}:xx)"])
            session = "London+NY" if (in_london and in_ny) else ("London" if in_london else "NY")
        else:
            in_london, in_ny = False, False
            session = "Unknown"

        # ===== GATE 2: MUST BE BULLISH CANDLE =====
        if c1 <= o1:
            return self._hold_response(["Not bullish"])

        body = c1 - o1
        body_atr = body / atr

        # ===== GATE 3: BODY IN RANGE (0.33–3.23 ATR) =====
        if body_atr < self.MIN_BODY_ATR or body_atr > self.MAX_BODY_ATR:
            return self._hold_response([f"Body out of range ({body_atr:.2f} ATR)"])

        # ===== GATE 4: WICK RATIO (max 1.61) =====
        uw = h1 - c1
        lw = o1 - l1
        wick_rat = (uw + lw) / max(body, 1e-10)
        if wick_rat > self.MAX_WICK_RATIO:
            return self._hold_response(["Wicks too large"])

        # ===== GATE 5: TREND_5 DOWN — BUYING THE DIP! =====
        # Price must be below its 5-period SMA = short-term dip
        closes = df['close'].tail(6).astype(float).values
        if len(closes) >= 6:
            sma5 = closes[-6:-1].mean()  # SMA of previous 5 candles
            if current_price >= sma5:
                return self._hold_response(["No dip (price above SMA5)"])
        else:
            return self._hold_response(["Not enough data for SMA5"])

        # ===== GATE 6: HURST MINIMUM =====
        if hurst_value < self.HURST_MIN:
            return self._hold_response([f"Non-trending (Hurst={hurst_value:.2f} < {self.HURST_MIN})"])

        # ===== GATE 7: RSI RANGE =====
        if rsi < self.OPTIMAL_RSI[0] or rsi > self.OPTIMAL_RSI[1]:
            return self._hold_response([f"RSI {rsi:.0f} out of range"])

        # ===== PATTERN DETECTED — CALL! =====
        dip_pct = (sma5 - current_price) / atr
        reasoning.append(f"🟢 Buy-the-Dip (body={body_atr:.2f}ATR, dip={dip_pct:.1f}σ, RSI={rsi:.0f})")
        reasoning.append(f"📍 Session: {session}")

        # ===== CONFIDENCE SCORING =====
        confidence = 0.65

        # Deeper dip = higher confidence
        if dip_pct > 0.5:
            confidence += 0.03
            reasoning.append(f"✅ Deep dip ({dip_pct:.1f}σ)")

        # EMA bullish structure bonus
        if ema_21 > ema_50 and ema_21 > 0 and ema_50 > 0:
            confidence += 0.02
            reasoning.append("✅ EMA bullish")

        # MACD positive bonus
        if macd_hist > 0:
            confidence += 0.02
            reasoning.append("✅ MACD+")

        # RSI oversold recovery
        if rsi < 40:
            confidence += 0.03
            reasoning.append(f"✅ RSI oversold ({rsi:.0f})")

        # Momentum turning positive
        if momentum_5 > 0:
            confidence += 0.02

        # Near BB lower band
        if bb_lower > 0 and bb_upper > 0:
            bb_pos = (current_price - bb_lower) / (bb_upper - bb_lower + 1e-10)
            if bb_pos < 0.3:
                confidence += 0.03
                reasoning.append("✅ Near BB lower")

        # Session overlap bonus (peak Forex liquidity)
        if in_london and in_ny:
            confidence += 0.03
            reasoning.append("✅ London+NY overlap")

        # Hurst trending bonus
        if hurst_value > 0.60:
            confidence += 0.02

        confidence = min(confidence, 0.85)
        confidence = max(confidence, 0.62)
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
                "ema_21": ema_21,
                "ema_50": ema_50,
                "macd_histogram": macd_hist,
                "bb_width": round(bb_width, 6),
                "momentum_5": momentum_5,
                "body_atr": round(body_atr, 3),
                "wick_ratio": round(wick_rat, 2),
                "dip_sigma": round(dip_pct, 2),
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
