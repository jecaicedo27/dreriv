"""
Adaptive Trend Flow Engine v4 — Hour-Filtered CALL-Only

DATA MINING (444 trades from ATF v3):
  Overall:         444T  50.9% WR  -$907
  Good hours only: 272T  58.1% WR  +$4,494  ← MASSIVE EDGE!
  
DEADLY HOURS (Colombia time):
  H11: 21.4% WR  -$1,113
  H23: 22.2% WR  -$1,377
  H15: 33.3% WR  -$966
  H18: 37.5% WR  -$283
  H02: 42.9% WR  -$350
  H07: 45.5% WR  -$351
  H09: 44.4% WR  -$337
  H10: 41.2% WR  -$439
  H13: 50.0% WR  -$93
  H20: 50.0% WR  -$89

BEST HOURS:
  H06: 72.7% WR  +$687
  H12: 68.8% WR  +$692
  H19: 62.5% WR  +$677
  H03: 60.0% WR  +$316

Changes from v3:
1. Block deadly hours: 2,7,9,10,11,13,15,18,20,23
2. Slope sweet spot: 0.05% - 0.20% (too weak or too strong = bad)
3. Bands width gate: skip wide bands (>0.011 = high volatility = bad)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from loguru import logger

from app.analysis.base_engine import BaseAnalysisEngine


class AdaptiveTrendFlowV4Engine(BaseAnalysisEngine):
    """
    ATF v4: Hour-Filtered CALL-Only — trades only in profitable hours
    
    Based on data mining 444 ATF v3 trades:
    - Same logic as v3 (CALL-only, all confirmations required)
    - Blocks 10 deadly hours that consistently lose
    - Slope range: 0.05-0.20% (sweet spot from data mining)
    - Band width < 0.011 (skip high-volatility periods)
    """
    
    name = "atf_v4"
    version = "4.0"
    description = "ATF v4: Hour-Filtered CALL — only trades in profitable hours"
    
    MIN_TREND_BARS = 3
    MAX_TREND_BARS = 50
    MIN_SLOPE = 0.05     # Tighter lower bound (was 0.04)
    MAX_SLOPE = 0.20     # Upper cap — too steep = reversal risk
    MIN_QUALITY = 60
    MAX_BAND_WIDTH = 0.011  # Skip high-volatility periods
    
    # Hours to block (Colombia time, UTC-5)
    # These hours have WR < 50% with >10 trades each
    BLOCKED_HOURS = {2, 7, 9, 10, 11, 13, 15, 18, 20, 23}
    
    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """Main analysis — CALL or HOLD, with hour filter"""
        
        reasoning = []
        
        if len(df) < 100:
            return self._hold_response(["Insufficient data"])
        
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        
        # ===== GATE 0: HOUR FILTER (Colombia time) =====
        open_time = latest.get('open_time')
        if open_time is not None:
            try:
                if hasattr(open_time, 'hour'):
                    utc_hour = open_time.hour
                else:
                    utc_hour = pd.Timestamp(open_time).hour
                col_hour = (utc_hour - 5) % 24
                if col_hour in self.BLOCKED_HOURS:
                    reasoning.append(f"⛔ Hora bloqueada ({col_hour}h COL) — stats negativas")
                    return self._hold_response(reasoning)
            except:
                pass  # If we can't determine hour, proceed
        
        # ===== ATF INDICATORS =====
        atf_basis = float(latest.get('atf_basis', 0) or 0)
        atf_upper = float(latest.get('atf_upper', 0) or 0)
        atf_lower = float(latest.get('atf_lower', 0) or 0)
        atf_trend = int(latest.get('atf_trend', 0) or 0)
        atf_slope = float(latest.get('atf_slope', 0) or 0)
        
        if atf_basis == 0 or atf_upper == 0:
            return self._hold_response(["ATF data not available"])
        
        # ===== GATE 1: BULLISH ONLY =====
        if atf_trend != 1:
            reasoning.append(f"ATF trend={atf_trend:+d} — only trade bullish")
            return self._hold_response(reasoning)
        
        # ===== GATE 2: HURST =====
        hurst_fast_val = float(latest.get('hurst_fast', 0) or 0)
        hurst_slow_val = float(latest.get('hurst_exponent', 0) or 0)
        hurst_value = hurst_fast_val if hurst_fast_val > 0 else hurst_slow_val
        if hurst_value == 0:
            hurst_value = 0.5
        
        if hurst_fast_val > 0 and hurst_fast_val < 0.42:
            reasoning.append(f"Hurst too low ({hurst_fast_val:.3f})")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ Hurst ({hurst_fast_val:.3f})")
        
        # ===== SUPPORTING INDICATORS =====
        ema_21 = float(latest.get('ema_21', 0) or 0)
        ema_50 = float(latest.get('ema_50', 0) or 0)
        rsi = float(latest.get('rsi_14', 50) or 50)
        macd_hist = float(latest.get('macd_histogram', 0) or 0)
        momentum_5 = float(latest.get('momentum_5', 0) or 0)
        bb_upper = float(latest.get('bollinger_upper', 0) or 0)
        bb_lower = float(latest.get('bollinger_lower', 0) or 0)
        bb_middle = float(latest.get('bollinger_middle', 0) or 0)
        adx = float(latest.get('adx_14', 0) or 0)
        
        atf_band_width = (atf_upper - atf_lower) / (atf_basis + 1e-10)
        reasoning.append(f"ATF: slope={atf_slope:.3f}% | bands={atf_band_width:.4f}")
        
        # ===== GATE 3: BAND WIDTH — skip high volatility =====
        if atf_band_width > self.MAX_BAND_WIDTH:
            reasoning.append(f"⛔ Bands too wide ({atf_band_width:.4f} > {self.MAX_BAND_WIDTH}) — high volatility")
            return self._hold_response(reasoning)
        
        # ===== Count trend duration =====
        trend_duration = 0
        for i in range(len(df) - 1, -1, -1):
            if int(df.iloc[i].get('atf_trend', 0) or 0) == 1:
                trend_duration += 1
            else:
                break
        
        # ===== GATE 4: Trend age limits =====
        if trend_duration < self.MIN_TREND_BARS:
            reasoning.append(f"Trend too young ({trend_duration})")
            return self._hold_response(reasoning)
        if trend_duration > self.MAX_TREND_BARS:
            reasoning.append(f"⛔ Trend exhausted ({trend_duration} > {self.MAX_TREND_BARS})")
            return self._hold_response(reasoning)
        
        reasoning.append(f"✅ Trend age ({trend_duration} bars)")
        
        # ===== GATE 5: SLOPE SWEET SPOT =====
        if atf_slope < self.MIN_SLOPE:
            reasoning.append(f"⛔ Slope too weak ({atf_slope:.3f}% < {self.MIN_SLOPE}%)")
            return self._hold_response(reasoning)
        if atf_slope > self.MAX_SLOPE:
            reasoning.append(f"⛔ Slope too steep ({atf_slope:.3f}% > {self.MAX_SLOPE}%) — reversal risk")
            return self._hold_response(reasoning)
        reasoning.append(f"✅ Slope in zone ({atf_slope:+.3f}%)")
        
        # ===== GATE 6: PRICE ABOVE BASIS =====
        if current_price < atf_basis:
            reasoning.append(f"⛔ Price below basis")
            return self._hold_response(reasoning)
        
        # ===== GATE 7: MACD POSITIVE =====
        if macd_hist <= 0:
            reasoning.append(f"⛔ MACD not positive ({macd_hist:.4f})")
            return self._hold_response(reasoning)
        reasoning.append(f"✅ MACD+ ({macd_hist:.4f})")
        
        # ===== GATE 8: ADX =====
        if adx > 0 and adx < 18:
            reasoning.append(f"⛔ ADX low ({adx:.1f})")
            return self._hold_response(reasoning)
        
        # ===== QUALITY SCORE =====
        quality = 0.0
        quality += min(abs(atf_slope) / 0.10, 1.0) * 25
        
        price_above_pct = (current_price - atf_basis) / atf_basis * 100
        quality += min(price_above_pct / 0.3, 1.0) * 20
        
        if 50 <= rsi <= 65:
            quality += 20
        elif 45 <= rsi <= 70:
            quality += 12
        elif 40 <= rsi <= 75:
            quality += 6
        
        if ema_21 > ema_50 and ema_50 > 0:
            quality += 20
        else:
            quality += 5
        
        if momentum_5 > 0:
            quality += 15
        else:
            quality += 3
        
        reasoning.append(f"Quality: {quality:.0f}/100")
        
        if quality < self.MIN_QUALITY:
            reasoning.append(f"Quality too low ({quality:.0f})")
            return self._hold_response(reasoning)
        
        # ===== EXHAUSTION =====
        if rsi > 75:
            reasoning.append(f"RSI overbought ({rsi:.1f})")
            return self._hold_response(reasoning)
        if current_price > atf_upper * 1.003:
            reasoning.append("Overextended above band")
            return self._hold_response(reasoning)
        
        # ===== CONFIDENCE =====
        base_conf = 0.62
        quality_bonus = ((quality - self.MIN_QUALITY) / (100 - self.MIN_QUALITY)) * 0.18
        trend_bonus = min((trend_duration - self.MIN_TREND_BARS) / 20, 0.04)
        slope_bonus = min(atf_slope / 0.15, 0.04)
        
        confidence = base_conf + quality_bonus + trend_bonus + slope_bonus
        confidence = min(confidence, 0.88)
        confidence = round(confidence, 3)
        
        reasoning.append(f"🟢 CALL | conf={confidence:.3f} | quality={quality:.0f} | age={trend_duration}")
        
        bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle else 0
        
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
            "hurst_signal": {"hurst": round(hurst_value, 4), "regime": "TRENDING"},
            "indicators": {
                "ema_21": ema_21, "ema_50": ema_50,
                "rsi_14": rsi, "macd_histogram": macd_hist,
                "bb_width": round(bb_width, 5), "momentum_5": momentum_5,
                "atf_trend": atf_trend, "atf_slope": round(atf_slope, 4),
                "atf_band_width": round(atf_band_width, 5),
                "trend_duration": trend_duration,
                "trend_quality": round(quality, 1),
            }
        }
    
    def _hold_response(self, reasoning: list) -> Dict[str, Any]:
        return {
            "signal": "HOLD", "final_signal": "HOLD",
            "confidence": 0.0, "final_confidence": 0.0,
            "contract_type": None, "suggested_stake_multiplier": 1.0,
            "duration": 300, "entry_price": 0,
            "reasoning": " | ".join(reasoning),
            "hurst_signal": {"hurst": 0, "regime": "UNKNOWN"},
            "indicators": {}
        }
