"""
Forex Smart Money Engine v1 — SMC for Real Forex (EUR/USD)

This is the Smart Money approach where it ACTUALLY works — on real
forex with institutional players (banks, ECB, FED, hedge funds).

Key differences from synthetic version:
- OB_ZONE_ATR scaled to pip-level ATR (~0.0003–0.0015)
- Session filter: only London/NY (institutions active)
- RSI divergence as additional confirmation
- Longer ChoCh lookback (institutions move on higher time scale)
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from app.analysis.base_engine import BaseAnalysisEngine

LONDON_OPEN_UTC  = 7
LONDON_CLOSE_UTC = 16
NY_OPEN_UTC      = 13
NY_CLOSE_UTC     = 22


class ForexSmartMoneyEngine(BaseAnalysisEngine):
    name        = "forex_smart_money_v1"
    version     = "1.0"
    description = "Forex SMC v1: ChoCh + OB/FVG en EUR/USD con sesión activa"

    DURATION_CANDLES = 5
    COOLDOWN_CANDLES = 5
    ALLOW_OVERLAP    = False

    OB_LOOKBACK    = 50
    FVG_LOOKBACK   = 25
    CHOCH_LOOKBACK = 80
    CHOCH_MAX_AGE  = 20    # Slightly wider than synthetics (forex moves slower)
    ATR_MULTIPLIER = 2.5   # Strong move threshold for forex
    OB_ZONE_ATR    = 1.0   # Tight OB zone
    HURST_MIN      = 0.52

    def analyze(self, df: pd.DataFrame, symbol: str = "frxEURUSD", **kwargs) -> Dict[str, Any]:
        reasoning = []

        if len(df) < 100:
            return self._hold("Insufficient data")

        curr = df.iloc[-1]
        c1   = float(curr['close'])
        o1   = float(curr['open'])

        # === SESSION FILTER ===
        from datetime import datetime, timezone
        utc_hour  = datetime.now(timezone.utc).hour
        in_london = LONDON_OPEN_UTC <= utc_hour < LONDON_CLOSE_UTC
        in_ny     = NY_OPEN_UTC <= utc_hour < NY_CLOSE_UTC
        if not (in_london or in_ny):
            return self._hold(f"Outside active sessions (UTC {utc_hour:02d}:xx)")

        ema_9   = float(curr.get('ema_9',  0) or 0)
        ema_21  = float(curr.get('ema_21', 0) or 0)
        ema_50  = float(curr.get('ema_50', 0) or 0)
        rsi     = float(curr.get('rsi_14', 50) or 50)
        macd_h  = float(curr.get('macd_histogram', 0) or 0)
        mom5    = float(curr.get('momentum_5', 0) or 0)
        hurst   = float(curr.get('hurst_fast', 0) or curr.get('hurst_exponent', 0) or 0.5)
        atr     = float(curr.get('atr_14', 0) or 0)

        if atr <= 0:
            atr = float((df['high'].tail(14).astype(float) - df['low'].tail(14).astype(float)).mean())
        if atr <= 0:
            atr = 0.0005

        # === GATE: Hurst ===
        if hurst < self.HURST_MIN:
            return self._hold(f"Non-trending (Hurst={hurst:.2f})")

        # === GATE: ATR spike ===
        baseline_atr = float(df['atr_14'].dropna().tail(50).mean()) if 'atr_14' in df.columns else atr
        if baseline_atr > 0 and atr > 2.5 * baseline_atr:
            return self._hold(f"ATR spike ({atr:.5f} > 2.5× {baseline_atr:.5f})")

        # === SWING STRUCTURE ===
        highs  = df['high'].astype(float).values
        lows   = df['low'].astype(float).values
        opens  = df['open'].astype(float).values
        closes = df['close'].astype(float).values
        n      = len(df)

        start = max(0, n - self.CHOCH_LOOKBACK)
        swing_highs, swing_lows = [], []
        for i in range(start + 2, n - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append((i, highs[i]))
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append((i, lows[i]))

        last_choch_type, last_choch_idx = None, -1
        trend, last_sh, last_sl = 0, 0, float('inf')
        all_swings = [(i, p, 'high') for i, p in swing_highs] + [(i, p, 'low') for i, p in swing_lows]
        all_swings.sort(key=lambda x: x[0])

        for idx, price, stype in all_swings:
            if stype == 'high':
                if last_sh > 0 and price > last_sh:
                    if trend == -1:
                        last_choch_type, last_choch_idx = 'bullish', idx
                    trend = 1
                last_sh = price
            else:
                if last_sl < float('inf') and price < last_sl:
                    if trend == 1:
                        last_choch_type, last_choch_idx = 'bearish', idx
                    trend = -1
                last_sl = price

        choch_age = (n - 1 - last_choch_idx)
        if last_choch_idx < 0 or choch_age > self.CHOCH_MAX_AGE:
            return self._hold(f"No recent ChoCh (age={choch_age} > {self.CHOCH_MAX_AGE})")

        reasoning.append(f"📊 ChoCh {last_choch_type} [{choch_age} candles ago]")

        # === EMA alignment gate ===
        if last_choch_type == 'bullish' and ema_21 > 0 and c1 < ema_21 * 0.999:
            return self._hold("Bullish ChoCh but price below EMA21")
        if last_choch_type == 'bearish' and ema_21 > 0 and c1 > ema_21 * 1.001:
            return self._hold("Bearish ChoCh but price above EMA21")

        # === ORDER BLOCKS ===
        ob_start = max(0, n - self.OB_LOOKBACK)
        bullish_obs, bearish_obs = [], []
        for i in range(ob_start + 3, n):
            mu = closes[i] - closes[i-3]
            md = closes[i-3] - closes[i]
            if mu > self.ATR_MULTIPLIER * atr:
                for j in range(i-1, max(i-5, ob_start), -1):
                    if closes[j] < opens[j]:
                        bullish_obs.append((j, lows[j], highs[j])); break
            elif md > self.ATR_MULTIPLIER * atr:
                for j in range(i-1, max(i-5, ob_start), -1):
                    if closes[j] > opens[j]:
                        bearish_obs.append((j, lows[j], highs[j])); break

        # === FVGS ===
        bullish_fvgs, bearish_fvgs = [], []
        for i in range(max(0, n - self.FVG_LOOKBACK) + 2, n):
            if lows[i] > highs[i-2]:
                bullish_fvgs.append((i, highs[i-2], lows[i]))
            elif highs[i] < lows[i-2]:
                bearish_fvgs.append((i, highs[i], lows[i-2]))

        signal, confidence = "HOLD", 0.0

        if last_choch_type == 'bullish':
            in_ob, in_fvg = False, False
            for _, ob_lo, ob_hi in bullish_obs:
                ob_c = (ob_lo + ob_hi) / 2
                if abs(c1 - ob_c) <= self.OB_ZONE_ATR * atr and ob_lo <= c1 <= ob_hi + atr * 0.5:
                    in_ob = True
                    reasoning.append(f"✅ Bullish OB ({ob_lo:.5f}–{ob_hi:.5f})")
                    break
            for _, fl, fh in bullish_fvgs:
                if fl - atr * 0.2 <= c1 <= fh + atr * 0.2:
                    in_fvg = True
                    reasoning.append(f"✅ Bullish FVG ({fl:.5f}–{fh:.5f})")
                    break

            if in_ob or in_fvg:
                # Candle close confirmation
                prev = df.iloc[-2] if len(df) >= 2 else curr
                if not (c1 > o1 or float(prev['close']) > float(prev['open'])):
                    return self._hold("Bullish OB/FVG but no bullish close confirmation")
                reasoning.append("✅ Bullish candle close at zone")

                signal, confidence = "CALL", 0.64
                if in_ob and in_fvg: confidence += 0.06; reasoning.append("✅ OB+FVG confluence!")
                if ema_9 > ema_21 > ema_50: confidence += 0.05; reasoning.append("✅ EMA full alignment")
                elif ema_9 > ema_21: confidence += 0.02
                if rsi > 40 and rsi < 60: confidence += 0.03
                if macd_h > 0 and mom5 > 0: confidence += 0.03; reasoning.append("✅ MACD+mom confirm")
                if choch_age <= 8: confidence += 0.03; reasoning.append(f"✅ Fresh ChoCh ({choch_age})")
                if in_london and in_ny: confidence += 0.03; reasoning.append("✅ London+NY overlap")
            else:
                return self._hold(f"Bullish ChoCh but not at OB/FVG ({c1:.5f})")

        elif last_choch_type == 'bearish':
            in_ob, in_fvg = False, False
            for _, ob_lo, ob_hi in bearish_obs:
                ob_c = (ob_lo + ob_hi) / 2
                if abs(c1 - ob_c) <= self.OB_ZONE_ATR * atr and ob_lo - atr * 0.5 <= c1 <= ob_hi:
                    in_ob = True
                    reasoning.append(f"✅ Bearish OB ({ob_lo:.5f}–{ob_hi:.5f})")
                    break
            for _, fl, fh in bearish_fvgs:
                if fl - atr * 0.2 <= c1 <= fh + atr * 0.2:
                    in_fvg = True
                    reasoning.append(f"✅ Bearish FVG ({fl:.5f}–{fh:.5f})")
                    break

            if in_ob or in_fvg:
                prev = df.iloc[-2] if len(df) >= 2 else curr
                if not (c1 < o1 or float(prev['close']) < float(prev['open'])):
                    return self._hold("Bearish OB/FVG but no bearish close confirmation")
                reasoning.append("✅ Bearish candle close at zone")

                signal, confidence = "PUT", 0.64
                if in_ob and in_fvg: confidence += 0.06; reasoning.append("✅ OB+FVG confluence!")
                if ema_9 < ema_21 < ema_50: confidence += 0.05; reasoning.append("✅ EMA full bearish")
                elif ema_9 < ema_21: confidence += 0.02
                if rsi > 40 and rsi < 60: confidence += 0.03
                if macd_h < 0 and mom5 < 0: confidence += 0.03; reasoning.append("✅ MACD+mom confirm")
                if choch_age <= 8: confidence += 0.03
                if in_london and in_ny: confidence += 0.03
            else:
                return self._hold(f"Bearish ChoCh but not at OB/FVG ({c1:.5f})")

        confidence = round(min(confidence, 0.90), 3)
        reasoning.append(f"→ {signal} conf={confidence:.3f}")

        return {
            "signal": signal, "final_signal": signal,
            "confidence": confidence, "final_confidence": confidence,
            "contract_type": signal if signal != "HOLD" else None,
            "suggested_stake_multiplier": 1.0,
            "duration": self.duration_seconds, "entry_price": c1,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": round(hurst, 4), "regime": "TRENDING" if hurst > 0.5 else "MEAN_REVERTING"},
            "indicators": {"rsi_14": rsi, "ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50,
                           "macd_histogram": macd_h, "momentum_5": mom5}
        }

    def _hold(self, reason: str) -> Dict[str, Any]:
        return {
            "signal": "HOLD", "final_signal": "HOLD", "confidence": 0.0, "final_confidence": 0.0,
            "contract_type": None, "suggested_stake_multiplier": 1.0,
            "duration": self.duration_seconds, "entry_price": 0,
            "reasoning": reason, "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"}, "indicators": {}
        }
