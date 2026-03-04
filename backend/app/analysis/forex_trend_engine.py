"""
Forex Trend Engine v1 — EMA Triple Alignment for EUR/USD

Philosophy: Only trade when ALL three EMAs are aligned AND during
active Forex sessions (London/NY overlap has the best liquidity).

Adapted for Forex pip scale (~1.0800–1.1200):
- ATR is typically 0.0003–0.0015 per 1-minute candle
- Momentum/slope thresholds scaled accordingly
- Session filter replaces hour blocks used in synthetic engines
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from app.analysis.base_engine import BaseAnalysisEngine


# UTC hours of active Forex sessions (best liquidity)
# London:            07:00–16:00 UTC
# New York:          13:00–22:00 UTC
# London+NY overlap: 13:00–16:00 UTC (prime time)
LONDON_OPEN_UTC  = 7
LONDON_CLOSE_UTC = 16
NY_OPEN_UTC      = 13
NY_CLOSE_UTC     = 22


class ForexTrendEngine(BaseAnalysisEngine):
    name        = "forex_trend_v1"
    version     = "1.0"
    description = "Forex Trend v1: EMA 9/21/50 alignment + session filter (EUR/USD)"

    DURATION_CANDLES = 5    # 5-min trades (forex moves slower than synthetics)
    COOLDOWN_CANDLES = 3
    ALLOW_OVERLAP    = False
    HURST_MIN        = 0.52

    def analyze(self, df: pd.DataFrame, symbol: str = "frxEURUSD", **kwargs) -> Dict[str, Any]:
        reasoning = []

        if len(df) < 100:
            return self._hold("Insufficient data")

        curr = df.iloc[-1]
        c1   = float(curr['close'])
        o1   = float(curr['open'])

        # === SESSION FILTER ===
        # Only trade during London or NY session (UTC)
        from datetime import datetime, timezone
        utc_hour = datetime.now(timezone.utc).hour
        in_london = LONDON_OPEN_UTC <= utc_hour < LONDON_CLOSE_UTC
        in_ny     = NY_OPEN_UTC <= utc_hour < NY_CLOSE_UTC
        if not (in_london or in_ny):
            return self._hold(f"Outside active sessions (UTC {utc_hour:02d}:xx — London:{LONDON_OPEN_UTC}-{LONDON_CLOSE_UTC}, NY:{NY_OPEN_UTC}-{NY_CLOSE_UTC})")

        session = "London+NY" if (in_london and in_ny) else ("London" if in_london else "NY")
        reasoning.append(f"✅ Active session: {session} (UTC {utc_hour:02d}:xx)")

        # === INDICATORS ===
        ema_9  = float(curr.get('ema_9',  0) or 0)
        ema_21 = float(curr.get('ema_21', 0) or 0)
        ema_50 = float(curr.get('ema_50', 0) or 0)
        rsi    = float(curr.get('rsi_14', 50) or 50)
        macd_h = float(curr.get('macd_histogram', 0) or 0)
        mom5   = float(curr.get('momentum_5', 0) or 0)
        hurst  = float(curr.get('hurst_fast', 0) or curr.get('hurst_exponent', 0) or 0.5)
        atr    = float(curr.get('atr_14', 0) or 0)
        adx    = float(curr.get('adx_14', 0) or 0)

        if atr <= 0:
            atr = float((df['high'].tail(14).astype(float) - df['low'].tail(14).astype(float)).mean())
        if atr <= 0:
            atr = 0.0005  # Typical EURUSD 1-min ATR fallback

        # === GATE: Hurst ===
        if hurst < self.HURST_MIN:
            return self._hold(f"Non-trending market (Hurst={hurst:.2f} < {self.HURST_MIN})")

        # === GATE: ADX (trend strength) — ADX > 20 required ===
        if adx > 0 and adx < 20:
            return self._hold(f"Weak trend (ADX={adx:.1f} < 20)")

        # === SIGNAL: Triple EMA Alignment ===
        if ema_9 > 0 and ema_21 > 0 and ema_50 > 0:
            bullish_align = ema_9 > ema_21 > ema_50 and c1 > ema_9
            bearish_align = ema_9 < ema_21 < ema_50 and c1 < ema_9
        else:
            return self._hold("EMAs not computed yet")

        signal     = "HOLD"
        confidence = 0.0

        if bullish_align:
            signal     = "CALL"
            confidence = 0.63
            reasoning.append(f"✅ EMA9({ema_9:.5f}) > EMA21({ema_21:.5f}) > EMA50({ema_50:.5f})")

            # EMA separation (trending strongly if EMAs are spreading)
            ema_spread = (ema_9 - ema_50) / atr if atr > 0 else 0
            if ema_spread > 1.5:
                confidence += 0.04
                reasoning.append(f"✅ EMA spread strong ({ema_spread:.1f}× ATR)")

            if rsi > 45 and rsi < 70:
                confidence += 0.03
                reasoning.append(f"✅ RSI bullish range ({rsi:.0f})")
            elif rsi >= 70:
                confidence -= 0.04  # Overbought
                reasoning.append(f"⚠️ RSI overbought ({rsi:.0f})")
            if macd_h > 0:
                confidence += 0.03
                reasoning.append("✅ MACD confirms bullish")
            if c1 > o1:
                confidence += 0.02
                reasoning.append("✅ Bullish candle close")
            if mom5 > 0:
                confidence += 0.02
            if in_london and in_ny:
                confidence += 0.03
                reasoning.append("✅ London+NY overlap (peak liquidity)")
            if hurst > 0.60:
                confidence += 0.02

        elif bearish_align:
            signal     = "PUT"
            confidence = 0.63
            reasoning.append(f"✅ EMA9({ema_9:.5f}) < EMA21({ema_21:.5f}) < EMA50({ema_50:.5f})")

            ema_spread = (ema_50 - ema_9) / atr if atr > 0 else 0
            if ema_spread > 1.5:
                confidence += 0.04
                reasoning.append(f"✅ EMA spread strong ({ema_spread:.1f}× ATR)")

            if rsi < 55 and rsi > 30:
                confidence += 0.03
                reasoning.append(f"✅ RSI bearish range ({rsi:.0f})")
            elif rsi <= 30:
                confidence -= 0.04  # Oversold
            if macd_h < 0:
                confidence += 0.03
                reasoning.append("✅ MACD confirms bearish")
            if c1 < o1:
                confidence += 0.02
                reasoning.append("✅ Bearish candle close")
            if mom5 < 0:
                confidence += 0.02
            if in_london and in_ny:
                confidence += 0.03
            if hurst > 0.60:
                confidence += 0.02

        else:
            return self._hold(f"No EMA alignment (EMA9={ema_9:.5f}, EMA21={ema_21:.5f}, EMA50={ema_50:.5f})")

        confidence = round(min(confidence, 0.88), 3)
        reasoning.append(f"→ {signal} conf={confidence:.3f} hurst={hurst:.2f} adx={adx:.1f}")

        bb_upper = float(curr.get('bollinger_upper', 0) or 0)
        bb_lower = float(curr.get('bollinger_lower', 0) or 0)
        bb_mid   = float(curr.get('bollinger_middle', 0) or 0)
        bb_width = (bb_upper - bb_lower) / (bb_mid + 1e-10) if bb_mid > 0 else 0

        return {
            "signal": signal, "final_signal": signal,
            "confidence": confidence, "final_confidence": confidence,
            "contract_type": signal if signal != "HOLD" else None,
            "suggested_stake_multiplier": 1.0,
            "duration": self.duration_seconds,
            "entry_price": c1,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": round(hurst, 4), "regime": "TRENDING" if hurst > 0.5 else "MEAN_REVERTING"},
            "indicators": {
                "rsi_14": rsi, "ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50,
                "macd_histogram": macd_h, "bb_width": round(bb_width, 6), "momentum_5": mom5,
            }
        }

    def _hold(self, reason: str) -> Dict[str, Any]:
        return {
            "signal": "HOLD", "final_signal": "HOLD",
            "confidence": 0.0, "final_confidence": 0.0,
            "contract_type": None, "suggested_stake_multiplier": 1.0,
            "duration": self.duration_seconds, "entry_price": 0,
            "reasoning": reason,
            "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
            "indicators": {}
        }
