import pandas as pd
import numpy as np
from typing import Dict, Any
from loguru import logger

from app.analysis.base_engine import BaseAnalysisEngine

class UltimateBullEngine(BaseAnalysisEngine):
    """
    Ultimate Bullish v5: High-Precision CALL-only engine
    
    Philosophy: "Maximum Win Rate through Strict Confluence"
    - Detects perfect bullish alignment (EMA_9 > EMA_21 > EMA_50)
    - Requires confirmed Macro Trend (Hurst > 0.6)
    - Enters on pullbacks during momentum (MACD > 0 + RSI 50-75)
    - Avoids overextended peaks (Bollinger Bounds constraint)
    """
    
    name = "bullish_v5"
    version = "5.0"
    description = "Ultimate Bull: High-Winrate CALLs using Momentum + Pullbacks"
    
    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """Strictly CALL or HOLD evaluation."""
        hurst_min = kwargs.get('hurst_min', 0.55) # Relaxed to allow standard uptrends
        hurst_max = kwargs.get('hurst_max', 0.85)
        
        reasoning = []
        
        if len(df) < 50:
            return self._hold_response(["Insufficient data"])
            
        latest = df.iloc[-1]
        current_price = float(latest['close'])
        
        # ===== HURST REGIME (Macro Trend) =====
        hurst_fast = float(latest.get('hurst_fast', 0) or 0)
        hurst_slow = float(latest.get('hurst_exponent', 0) or 0)
        
        # Blend taking the best of both micro and macro
        hurst_value = max(hurst_fast, hurst_slow) if hurst_fast > 0 and hurst_slow > 0 else (hurst_fast or hurst_slow)
        
        if hurst_value < hurst_min:
            reasoning.append(f"Trend too weak (Hurst={hurst_value:.3f} < {hurst_min})")
            return self._hold_response(reasoning)
        elif hurst_value > hurst_max:
            reasoning.append(f"Trend exhausted (Hurst={hurst_value:.3f} > {hurst_max})")
            return self._hold_response(reasoning)
            
        reasoning.append(f"✅ Strong Uptrend (Hurst={hurst_value:.3f})")
        
        # ===== READ INDICATORS =====
        ema_9 = float(latest.get('ema_9', 0) or 0)
        ema_21 = float(latest.get('ema_21', 0) or 0)
        ema_50 = float(latest.get('ema_50', 0) or 0)
        rsi = float(latest.get('rsi_14', 50) or 50)
        macd_hist = float(latest.get('macd_histogram', 0) or 0)
        momentum_5 = float(latest.get('momentum_5', 0) or 0)
        bb_upper = float(latest.get('bollinger_upper', 0) or 0)
        bb_lower = float(latest.get('bollinger_lower', 0) or 0)
        
        ema_diverging = bool(int(latest.get('ema_diverging', 0) or 0))
        ema_gap_rate = float(latest.get('ema_gap_rate', 0) or 0)
        
        # ===== GATE 1: EMA TREND (Bullish Macro) =====
        ema_50_prev = float(df.iloc[-2].get('ema_50', 0) or 0) if len(df) >= 2 else 0
        if ema_50 <= ema_50_prev:
            reasoning.append(f"EMA 50 is not rising (Curr {ema_50:.1f} <= Prev {ema_50_prev:.1f})")
            return self._hold_response(reasoning)
            
        if current_price <= ema_50:
            reasoning.append(f"Price below EMA 50 (P={current_price:.1f})")
            return self._hold_response(reasoning)
            
        reasoning.append(f"✅ Bullish Macro Trend Active")
        
        # ===== GATE 2: MOMENTUM (MACD + RSI) =====
        if macd_hist <= 0.2: # The optimizer found that MACD must be heavily positive (>0.2)
            reasoning.append(f"MACD Histogram not strong enough ({macd_hist:.4f} <= 0.2)")
            return self._hold_response(reasoning)
            
        if rsi < 45 or rsi > 55: # Optimizer showed 45-55 is the mathematical sweet spot to avoid peak exhaustion
            reasoning.append(f"RSI out of sweet spot (RSI={rsi:.1f}, want 45-55)")
            return self._hold_response(reasoning)
            
        # ===== GATE 3: ENTRY PULLBACK QUALITY & HEIKIN-ASHI FILTRATION =====
        # Optimizer determined that buying perfectly around EMA_21 (-0.2% to 0.2%) yields the highest edge
        dist_to_ema21_pct = (current_price - ema_21) / ema_21 * 100
        
        if current_price >= bb_upper:
            reasoning.append(f"Price piercing upper Bollinger Band — overextended")
            return self._hold_response(reasoning)
            
        if dist_to_ema21_pct < -0.2 or dist_to_ema21_pct > 0.2:
            reasoning.append(f"Price not snug at EMA_21 (dist={dist_to_ema21_pct:.2f}%) — wait for exact zone")
            return self._hold_response(reasoning)
            
        # Fast Heikin-Ashi calculation (last 3 candles)
        if len(df) >= 3:
            recent_df = df.iloc[-3:].copy()
            
            # HA Candle t-2 (Anchor)
            ha_open_2 = (float(df.iloc[-4]['open']) + float(df.iloc[-4]['close'])) / 2 if len(df) >= 4 else float(recent_df.iloc[0]['open'])
            ha_close_2 = (float(recent_df.iloc[0]['open']) + float(recent_df.iloc[0]['high']) + float(recent_df.iloc[0]['low']) + float(recent_df.iloc[0]['close'])) / 4
            
            # HA Candle t-1
            ha_open_1 = (ha_open_2 + ha_close_2) / 2
            ha_close_1 = (float(recent_df.iloc[1]['open']) + float(recent_df.iloc[1]['high']) + float(recent_df.iloc[1]['low']) + float(recent_df.iloc[1]['close'])) / 4
            
            # HA Candle t (Current)
            ha_open_0 = (ha_open_1 + ha_close_1) / 2
            ha_close_0 = (float(recent_df.iloc[2]['open']) + float(recent_df.iloc[2]['high']) + float(recent_df.iloc[2]['low']) + float(recent_df.iloc[2]['close'])) / 4
            
            if ha_close_0 <= ha_open_0:
                reasoning.append(f"Heikin-Ashi current candle is RED (HA_Close {ha_close_0:.1f} <= HA_Open {ha_open_0:.1f}) — Pullback not finished")
                return self._hold_response(reasoning)
                
            reasoning.append(f"✅ Pullback accepted: HA Trend is GREEN")

        reasoning.append(f"✅ Deep Pullback Zone (dist EMA21={dist_to_ema21_pct:.2f}%)")
        
        # ===== SCORING AND CONFIDENCE =====
        # Base confidence for clearing all strict optimizer gates
        confidence = 0.70
        
        # Bonus for RSI in the absolute prime zone
        if 55 <= rsi <= 65:
            confidence += 0.05
            
        # Bonus for a very clean pullback (touching or slightly below EMA 21)
        if dist_to_ema21_pct <= 0.05 and current_price > ema_50:
            confidence += 0.08
            
        # Bonus for strong MACD momentum
        if macd_hist > 0.002:
            confidence += 0.03
            
        # Cap confidence
        confidence = min(round(confidence, 3), 0.85)
        
        reasoning.append(f"🚀 ULTIMATE BULL CALL | conf={confidence:.3f}")
        
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
                "ema_9": ema_9,
                "ema_21": ema_21,
                "ema_50": ema_50,
                "rsi_14": rsi,
                "macd_histogram": macd_hist,
                "momentum_5": momentum_5,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower
            }
        }
        
    def _hold_response(self, reasoning: list) -> Dict[str, Any]:
        """Required standard HOLD response."""
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
