"""
Smart Money Engine v2 — Institutional Order Flow Trading (Optimized)

Changes from v1:
- Removed confidence floor (was 0.63 min → too many weak entries)
- Strict Hurst gate: only trend markets (Hurst > 0.52)
- EMA trend alignment gate: ChoCh direction must match EMA9/21/50 bias
- Tighter OB zone tolerance (0.8 ATR instead of 1.5)
- Stricter ChoCh recency window (15 candles vs 30)
- ALLOW_OVERLAP = False (no more stacking trades)
- COOLDOWN_CANDLES = 5 (was 2)
- Strong move detection requires 2.0×ATR (was 1.5) — only quality impulses
- ATR spike guard: do not enter if current ATR > 2.5× baseline (erratic market)
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from app.analysis.base_engine import BaseAnalysisEngine


class SmartMoneyEngine(BaseAnalysisEngine):
    name = "smart_money_v1"
    version = "2.0"
    description = "Smart Money v2: ChoCh+OB/FVG con alineación multi-EMA y gate Hurst"

    DURATION_CANDLES = 3    # 3-min trades
    COOLDOWN_CANDLES = 5    # Stricter cooldown (was 2)
    ALLOW_OVERLAP = False   # No stacking trades (was True)

    # Structural detection parameters (tightened)
    OB_LOOKBACK     = 40    # How far back to look for OBs (was 50)
    FVG_LOOKBACK    = 20    # How far back for FVGs (was 30)
    CHOCH_LOOKBACK  = 60    # Swing search window (was 80)
    CHOCH_MAX_AGE   = 15    # ChoCh must be within last N candles (was 30)
    ATR_MULTIPLIER  = 2.0   # Impulse must be >= 2× ATR (was 1.5) — quality filter
    OB_ZONE_ATR     = 0.8   # Price must be within 0.8 ATR of OB center (was 1.5)
    HURST_MIN       = 0.52  # Only trade in trending markets

    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        reasoning = []

        if len(df) < 100:
            return self._hold_response(["Insufficient data"])

        curr = df.iloc[-1]
        c1   = float(curr['close'])
        o1   = float(curr['open'])

        # === INDICATORS ===
        ema_9      = float(curr.get('ema_9', 0) or 0)
        ema_21     = float(curr.get('ema_21', 0) or 0)
        ema_50     = float(curr.get('ema_50', 0) or 0)
        rsi        = float(curr.get('rsi_14', 50) or 50)
        macd_hist  = float(curr.get('macd_histogram', 0) or 0)
        momentum_5 = float(curr.get('momentum_5', 0) or 0)
        hurst_fast = float(curr.get('hurst_fast', 0) or 0)
        hurst_slow = float(curr.get('hurst_exponent', 0) or 0)
        bb_upper   = float(curr.get('bollinger_upper', 0) or 0)
        bb_lower   = float(curr.get('bollinger_lower', 0) or 0)
        bb_middle  = float(curr.get('bollinger_middle', 0) or 0)
        atr        = float(curr.get('atr_14', 0) or 0)

        hurst_value = hurst_fast if hurst_fast > 0 else hurst_slow
        if hurst_value == 0:
            hurst_value = 0.5

        if atr <= 0:
            atr = float((df['high'].tail(14).astype(float) - df['low'].tail(14).astype(float)).mean())
        if atr <= 0:
            atr = 1.0

        # === GATE 1: Hurst trending filter ===
        if hurst_value < self.HURST_MIN:
            return self._hold_response([f"Market not trending (Hurst={hurst_value:.2f} < {self.HURST_MIN})"])

        # === GATE 2: ATR spike guard — skip erratic candles ===
        baseline_atr = float(df['atr_14'].dropna().tail(50).mean()) if 'atr_14' in df.columns else atr
        if baseline_atr > 0 and atr > 2.5 * baseline_atr:
            return self._hold_response([f"ATR spike detected ({atr:.2f} > 2.5× baseline {baseline_atr:.2f})"])

        # === SWING STRUCTURE ===
        highs  = df['high'].astype(float).values
        lows   = df['low'].astype(float).values
        opens  = df['open'].astype(float).values
        closes = df['close'].astype(float).values
        n      = len(df)

        # Find swing highs/lows
        start = max(0, n - self.CHOCH_LOOKBACK)
        swing_highs, swing_lows = [], []

        for i in range(start + 2, n - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append((i, highs[i]))
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append((i, lows[i]))

        # Detect ChoCh
        last_choch_type = None
        last_choch_idx  = -1
        trend = 0
        last_sh_price = 0
        last_sl_price = float('inf')

        all_swings = [(idx, price, 'high') for idx, price in swing_highs]
        all_swings += [(idx, price, 'low') for idx, price in swing_lows]
        all_swings.sort(key=lambda x: x[0])

        for idx, price, stype in all_swings:
            if stype == 'high':
                if last_sh_price > 0 and price > last_sh_price:
                    if trend == -1:
                        last_choch_type = 'bullish'
                        last_choch_idx  = idx
                    trend = 1
                last_sh_price = price
            else:
                if last_sl_price < float('inf') and price < last_sl_price:
                    if trend == 1:
                        last_choch_type = 'bearish'
                        last_choch_idx  = idx
                    trend = -1
                last_sl_price = price

        # === GATE 3: Require recent ChoCh (tighter window) ===
        choch_age = (n - 1 - last_choch_idx)
        if last_choch_idx < 0 or choch_age > self.CHOCH_MAX_AGE:
            return self._hold_response([f"No recent ChoCh (age={choch_age} > {self.CHOCH_MAX_AGE})"])

        reasoning.append(f"📊 ChoCh {last_choch_type} [{choch_age} candles ago]")

        # === GATE 4: Multi-EMA trend alignment ===
        # ChoCh direction must agree with EMA structure
        if last_choch_type == 'bullish':
            # Require price above EMA21 and EMA9 not strongly below EMA21
            if ema_21 > 0 and c1 < ema_21 * 0.998:
                return self._hold_response(["Bullish ChoCh but price still below EMA21 — trend not confirmed"])
        elif last_choch_type == 'bearish':
            if ema_21 > 0 and c1 > ema_21 * 1.002:
                return self._hold_response(["Bearish ChoCh but price still above EMA21 — trend not confirmed"])

        # === FIND ORDER BLOCKS (quality filter: 2×ATR impulse required) ===
        ob_start = max(0, n - self.OB_LOOKBACK)
        bullish_obs, bearish_obs = [], []

        for i in range(ob_start + 3, n):
            move_up   = closes[i] - closes[i-3]
            move_down = closes[i-3] - closes[i]

            if move_up > self.ATR_MULTIPLIER * atr:
                for j in range(i-1, max(i-5, ob_start), -1):
                    if closes[j] < opens[j]:  # Bearish candle = bullish OB
                        bullish_obs.append((j, lows[j], highs[j]))
                        break

            elif move_down > self.ATR_MULTIPLIER * atr:
                for j in range(i-1, max(i-5, ob_start), -1):
                    if closes[j] > opens[j]:  # Bullish candle = bearish OB
                        bearish_obs.append((j, lows[j], highs[j]))
                        break

        # === FIND FVGs ===
        bullish_fvgs, bearish_fvgs = [], []
        fvg_start = max(0, n - self.FVG_LOOKBACK)

        for i in range(fvg_start + 2, n):
            if lows[i] > highs[i-2]:    # Bullish FVG
                bullish_fvgs.append((i, highs[i-2], lows[i]))
            elif highs[i] < lows[i-2]:  # Bearish FVG
                bearish_fvgs.append((i, highs[i], lows[i-2]))

        # === DECISION LOGIC ===
        signal     = "HOLD"
        confidence = 0.0

        if last_choch_type == 'bullish':
            in_ob_zone, in_fvg_zone = False, False

            # Tighter OB zone: must be within OB_ZONE_ATR of OB center
            for idx, ob_low, ob_high in bullish_obs:
                ob_center = (ob_low + ob_high) / 2
                if abs(c1 - ob_center) <= self.OB_ZONE_ATR * atr and ob_low <= c1 <= ob_high + atr * 0.5:
                    in_ob_zone = True
                    reasoning.append(f"✅ In Bullish OB zone ({ob_low:.1f}–{ob_high:.1f})")
                    break

            for idx, fvg_low, fvg_high in bullish_fvgs:
                if fvg_low - atr * 0.2 <= c1 <= fvg_high + atr * 0.2:
                    in_fvg_zone = True
                    reasoning.append(f"✅ In Bullish FVG zone ({fvg_low:.1f}–{fvg_high:.1f})")
                    break

            if in_ob_zone or in_fvg_zone:
                # === GATE 5: Candle close confirmation ===
                # Current OR previous candle must close bullish (close > open)
                # — confirms buyers are stepping in at the zone, not still falling
                prev_c = df.iloc[-2] if len(df) >= 2 else curr
                curr_bullish = c1 > o1
                prev_bullish = float(prev_c['close']) > float(prev_c['open'])
                if not curr_bullish and not prev_bullish:
                    return self._hold_response(["Bullish OB/FVG touched but no bullish close confirmation (still falling)"])
                reasoning.append(f"✅ Candle close confirms bullish ({'+' if curr_bullish else 'prev +'})") 
                signal     = "CALL"
                confidence = 0.63  # Base confidence (no more min-floor enforcement)

                if in_ob_zone and in_fvg_zone:
                    confidence += 0.06
                    reasoning.append("✅ OB + FVG confluence!")
                if ema_9 > ema_21 > ema_50:
                    confidence += 0.05
                    reasoning.append("✅ EMA9 > 21 > 50 (full alignment)")
                elif ema_9 > ema_21:
                    confidence += 0.02
                if rsi > 40 and rsi < 60:
                    confidence += 0.03
                    reasoning.append(f"✅ RSI neutral-bullish ({rsi:.0f})")
                elif rsi < 35:
                    confidence -= 0.03  # Oversold → momentum exhausted
                if momentum_5 > 0 and macd_hist > 0:
                    confidence += 0.03
                    reasoning.append("✅ Momentum + MACD confirm")
                if c1 > o1:
                    confidence += 0.02
                    reasoning.append("✅ Bullish close at OB")
                if hurst_value > 0.60:
                    confidence += 0.03
                    reasoning.append(f"✅ Hurst strong ({hurst_value:.2f})")
                if choch_age <= 5:
                    confidence += 0.03
                    reasoning.append(f"✅ Fresh ChoCh ({choch_age} candles)")

            else:
                return self._hold_response([f"Bullish ChoCh but price not at OB/FVG (price={c1:.1f})"])

        elif last_choch_type == 'bearish':
            in_ob_zone, in_fvg_zone = False, False

            for idx, ob_low, ob_high in bearish_obs:
                ob_center = (ob_low + ob_high) / 2
                if abs(c1 - ob_center) <= self.OB_ZONE_ATR * atr and ob_low - atr * 0.5 <= c1 <= ob_high:
                    in_ob_zone = True
                    reasoning.append(f"✅ In Bearish OB zone ({ob_low:.1f}–{ob_high:.1f})")
                    break

            for idx, fvg_low, fvg_high in bearish_fvgs:
                if fvg_low - atr * 0.2 <= c1 <= fvg_high + atr * 0.2:
                    in_fvg_zone = True
                    reasoning.append(f"✅ In Bearish FVG zone ({fvg_low:.1f}–{fvg_high:.1f})")
                    break

            if in_ob_zone or in_fvg_zone:
                # === GATE 5: Candle close confirmation ===
                # Current OR previous candle must close bearish (close < open)
                # — confirms sellers are stepping in at the zone, not still rising
                prev_c = df.iloc[-2] if len(df) >= 2 else curr
                curr_bearish = c1 < o1
                prev_bearish = float(prev_c['close']) < float(prev_c['open'])
                if not curr_bearish and not prev_bearish:
                    return self._hold_response(["Bearish OB/FVG touched but no bearish close confirmation (still rising)"])
                reasoning.append(f"✅ Candle close confirms bearish ({'-' if curr_bearish else 'prev -'})")

                signal     = "PUT"
                confidence = 0.63


                if in_ob_zone and in_fvg_zone:
                    confidence += 0.06
                    reasoning.append("✅ OB + FVG confluence!")
                if ema_9 < ema_21 < ema_50:
                    confidence += 0.05
                    reasoning.append("✅ EMA9 < 21 < 50 (full bearish alignment)")
                elif ema_9 < ema_21:
                    confidence += 0.02
                if rsi > 40 and rsi < 60:
                    confidence += 0.03
                    reasoning.append(f"✅ RSI neutral-bearish ({rsi:.0f})")
                elif rsi > 65:
                    confidence -= 0.03  # Overbought but already extended
                if momentum_5 < 0 and macd_hist < 0:
                    confidence += 0.03
                    reasoning.append("✅ Momentum + MACD confirm bearish")
                if c1 < o1:
                    confidence += 0.02
                    reasoning.append("✅ Bearish close at OB")
                if hurst_value > 0.60:
                    confidence += 0.03
                    reasoning.append(f"✅ Hurst strong ({hurst_value:.2f})")
                if choch_age <= 5:
                    confidence += 0.03
                    reasoning.append(f"✅ Fresh ChoCh ({choch_age} candles)")

            else:
                return self._hold_response([f"Bearish ChoCh but price not at OB/FVG (price={c1:.1f})"])

        # Cap confidence — no artificial floor
        confidence = round(min(confidence, 0.90), 3)

        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle > 0 else 0
        reasoning.append(f"→ {signal} conf={confidence:.3f} hurst={hurst_value:.2f}")

        return {
            "signal":                    signal,
            "final_signal":              signal,
            "confidence":                confidence,
            "final_confidence":          confidence,
            "contract_type":             signal if signal != "HOLD" else None,
            "suggested_stake_multiplier": 1.0,
            "duration":                  self.duration_seconds,
            "entry_price":               c1,
            "reasoning":                 " | ".join(reasoning),
            "hurst_signal":              {"hurst": round(hurst_value, 4), "regime": "TRENDING" if hurst_value > 0.5 else "MEAN_REVERTING"},
            "indicators": {
                "rsi_14":         rsi,
                "ema_9":          ema_9,
                "ema_21":         ema_21,
                "ema_50":         ema_50,
                "macd_histogram": macd_hist,
                "bb_width":       round(bb_width, 5),
                "momentum_5":     momentum_5,
            }
        }

    def _hold_response(self, reasoning: list) -> Dict[str, Any]:
        return {
            "signal": "HOLD", "final_signal": "HOLD",
            "confidence": 0.0, "final_confidence": 0.0,
            "contract_type": None, "suggested_stake_multiplier": 1.0,
            "duration": self.duration_seconds, "entry_price": 0,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
            "indicators": {}
        }
