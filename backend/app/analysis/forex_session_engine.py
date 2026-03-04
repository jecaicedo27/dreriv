"""
Forex Session Engine v1 — London Opening Range Breakout (EUR/USD)

Classic, time-tested Forex strategy:
1. Identify the range established in the first 30 minutes of London session (07:00–07:30 UTC)
2. Wait for a breakout above/below that range
3. Trade in the breakout direction

This works because:
- London open brings institutional order flow (banks starting their day)
- First 30 minutes set the initial balance/range
- Breakouts from this range often have strong follow-through
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
from app.analysis.base_engine import BaseAnalysisEngine
from datetime import datetime, timezone, timedelta


LONDON_OPEN_UTC  = 7    # 07:00 UTC = London open
LONDON_OB_MINS   = 30   # "Opening Balance" period: 07:00–07:30 UTC
NY_OPEN_UTC      = 13
NY_CLOSE_UTC     = 22


class ForexSessionEngine(BaseAnalysisEngine):
    name        = "forex_session_v1"
    version     = "1.0"
    description = "Forex Session v1: London Opening Range Breakout (EUR/USD)"

    DURATION_CANDLES = 5
    COOLDOWN_CANDLES = 10   # Longer cooldown — only a few good setups per day
    ALLOW_OVERLAP    = False
    HURST_MIN        = 0.50

    # Breakout must be at least this many ATR beyond the range boundary
    BREAKOUT_ATR_MIN = 0.5
    # Range must be at least 0.3× ATR wide to be meaningful
    RANGE_MIN_ATR    = 0.3
    # Range must not be wider than 3× ATR (abnormally wide = volatile open)
    RANGE_MAX_ATR    = 3.0

    def analyze(self, df: pd.DataFrame, symbol: str = "frxEURUSD", **kwargs) -> Dict[str, Any]:
        reasoning = []

        if len(df) < 50:
            return self._hold("Insufficient data")

        curr = df.iloc[-1]
        c1   = float(curr['close'])
        o1   = float(curr['open'])

        # Only trade after the opening balance period, during London+NY
        utc_now  = datetime.now(timezone.utc)
        utc_hour = utc_now.hour
        utc_min  = utc_now.minute

        # Must be after 07:30 UTC (London OB established) and before NY close
        if utc_hour < LONDON_OPEN_UTC or (utc_hour == LONDON_OPEN_UTC and utc_min < LONDON_OB_MINS):
            return self._hold(f"London OB not yet established (UTC {utc_hour:02d}:{utc_min:02d}, need 07:30+)")
        if utc_hour >= NY_CLOSE_UTC:
            return self._hold(f"NY session closed (UTC {utc_hour:02d}:xx)")

        hurst = float(curr.get('hurst_fast', 0) or curr.get('hurst_exponent', 0) or 0.5)
        atr   = float(curr.get('atr_14', 0) or 0)
        rsi   = float(curr.get('rsi_14', 50) or 50)
        macd_h = float(curr.get('macd_histogram', 0) or 0)
        ema_21 = float(curr.get('ema_21', 0) or 0)
        ema_50 = float(curr.get('ema_50', 0) or 0)

        if atr <= 0:
            atr = float((df['high'].tail(14).astype(float) - df['low'].tail(14).astype(float)).mean())
        if atr <= 0:
            atr = 0.0005

        # === FIND LONDON OPENING BALANCE (07:00–07:30 UTC candles) ===
        ob_high, ob_low = self._find_london_ob(df)
        if ob_high is None:
            return self._hold("Could not find London Opening Balance candles")

        ob_range = ob_high - ob_low
        if ob_range < self.RANGE_MIN_ATR * atr:
            return self._hold(f"London OB too tight ({ob_range:.5f} < {self.RANGE_MIN_ATR * atr:.5f})")
        if ob_range > self.RANGE_MAX_ATR * atr:
            return self._hold(f"London OB too wide ({ob_range:.5f} > {self.RANGE_MAX_ATR * atr:.5f} — volatile open)")

        reasoning.append(f"📐 London OB: {ob_low:.5f}–{ob_high:.5f} (range={ob_range:.5f})")

        # === BREAKOUT CHECK ===
        signal, confidence = "HOLD", 0.0
        breakout_above = c1 > ob_high + self.BREAKOUT_ATR_MIN * atr
        breakout_below = c1 < ob_low  - self.BREAKOUT_ATR_MIN * atr

        if breakout_above:
            signal = "CALL"
            confidence = 0.63
            excess = (c1 - ob_high) / atr
            reasoning.append(f"📈 Breakout ABOVE London OB ({excess:.1f}× ATR above range top)")

            # Confirmations
            if ema_21 > 0 and c1 > ema_21: confidence += 0.04; reasoning.append("✅ Price > EMA21")
            if ema_50 > 0 and ema_21 > ema_50: confidence += 0.03; reasoning.append("✅ EMA21 > EMA50")
            if rsi > 50 and rsi < 75: confidence += 0.03; reasoning.append(f"✅ RSI bullish ({rsi:.0f})")
            if macd_h > 0: confidence += 0.03; reasoning.append("✅ MACD positive")
            if c1 > o1: confidence += 0.02  # current candle bullish close
            if 1.0 <= excess <= 2.5: confidence += 0.02  # ideal breakout distance
            if hurst > 0.55: confidence += 0.02
            if 13 <= utc_hour < 16: confidence += 0.04; reasoning.append("✅ London+NY overlap")

        elif breakout_below:
            signal = "PUT"
            confidence = 0.63
            excess = (ob_low - c1) / atr
            reasoning.append(f"📉 Breakout BELOW London OB ({excess:.1f}× ATR below range bottom)")

            if ema_21 > 0 and c1 < ema_21: confidence += 0.04; reasoning.append("✅ Price < EMA21")
            if ema_50 > 0 and ema_21 < ema_50: confidence += 0.03; reasoning.append("✅ EMA21 < EMA50")
            if rsi < 50 and rsi > 25: confidence += 0.03; reasoning.append(f"✅ RSI bearish ({rsi:.0f})")
            if macd_h < 0: confidence += 0.03; reasoning.append("✅ MACD negative")
            if c1 < o1: confidence += 0.02
            if 1.0 <= excess <= 2.5: confidence += 0.02
            if hurst > 0.55: confidence += 0.02
            if 13 <= utc_hour < 16: confidence += 0.04; reasoning.append("✅ London+NY overlap")

        else:
            return self._hold(
                f"Price ({c1:.5f}) inside or near London OB ({ob_low:.5f}–{ob_high:.5f}) — waiting for breakout"
            )

        confidence = round(min(confidence, 0.88), 3)
        reasoning.append(f"→ {signal} conf={confidence:.3f} hurst={hurst:.2f}")

        bb_up  = float(curr.get('bollinger_upper',  0) or 0)
        bb_lo  = float(curr.get('bollinger_lower',  0) or 0)
        bb_mid = float(curr.get('bollinger_middle', 0) or 0)
        bb_w   = (bb_up - bb_lo) / (bb_mid + 1e-10) if bb_mid > 0 else 0

        return {
            "signal": signal, "final_signal": signal,
            "confidence": confidence, "final_confidence": confidence,
            "contract_type": signal if signal != "HOLD" else None,
            "suggested_stake_multiplier": 1.0,
            "duration": self.duration_seconds, "entry_price": c1,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": round(hurst, 4), "regime": "TRENDING" if hurst > 0.5 else "MEAN_REVERTING"},
            "indicators": {
                "rsi_14": rsi, "ema_21": ema_21, "ema_50": ema_50,
                "macd_histogram": macd_h, "bb_width": round(bb_w, 6),
                "london_ob_high": ob_high, "london_ob_low": ob_low,
            }
        }

    def _find_london_ob(self, df: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
        """Find high/low of London Opening Balance candles (07:00–07:30 UTC)."""
        try:
            if 'open_time' not in df.columns:
                return None, None

            today_utc = datetime.now(timezone.utc).date()
            london_open = datetime(today_utc.year, today_utc.month, today_utc.day,
                                   LONDON_OPEN_UTC, 0, 0, tzinfo=timezone.utc)
            london_ob_end = london_open + timedelta(minutes=LONDON_OB_MINS)

            # Filter to London OB candles
            times = pd.to_datetime(df['open_time'])
            if times.dt.tz is None:
                times = times.dt.tz_localize('UTC')
            mask = (times >= london_open) & (times < london_ob_end)
            ob_candles = df[mask]

            if len(ob_candles) < 1:
                return None, None

            return float(ob_candles['high'].astype(float).max()), float(ob_candles['low'].astype(float).min())
        except Exception:
            return None, None

    def _hold(self, reason: str) -> Dict[str, Any]:
        return {
            "signal": "HOLD", "final_signal": "HOLD", "confidence": 0.0, "final_confidence": 0.0,
            "contract_type": None, "suggested_stake_multiplier": 1.0,
            "duration": self.duration_seconds, "entry_price": 0,
            "reasoning": reason, "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"}, "indicators": {}
        }
