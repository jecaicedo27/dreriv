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
        hurst_min = kwargs.get('hurst_min', 0.60) # Stricter default
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
        
        # ===== GATE 1: EMA ALIGNMENT (Perfect Bullish) =====
        if not (current_price > ema_50 and ema_9 > ema_21 and ema_21 > ema_50):
            reasoning.append(f"EMAs not perfectly aligned (P={current_price:.1f}, E9={ema_9:.1f}, E21={ema_21:.1f}, E50={ema_50:.1f})")
            return self._hold_response(reasoning)
            
        reasoning.append(f"✅ EMA Perfect Alignment")
        
        # Removed ema_diverging constraint because it rejects valid pullbacks
        # if not ema_diverging or ema_gap_rate < 0:
        #     reasoning.append("EMAs are converging, trend losing steam")
        #     return self._hold_response(reasoning)
            
        # ===== GATE 2: MOMENTUM (MACD + RSI) =====
        if macd_hist <= 0:
            reasoning.append(f"MACD Histogram negative ({macd_hist:.4f})")
            return self._hold_response(reasoning)
            
        if rsi < 50 or rsi > 72:
            reasoning.append(f"RSI out of sweet spot (RSI={rsi:.1f}, want 50-72)")
            return self._hold_response(reasoning)
            
        if momentum_5 <= 0:
            reasoning.append(f"Short-term momentum negative ({momentum_5:.3f})")
            return self._hold_response(reasoning)
            
        reasoning.append(f"✅ Strong Momentum (RSI={rsi:.1f}, MACD={macd_hist:.4f})")
        
        # ===== GATE 3: ENTRY PULLBACK QUALITY =====
        # We want the price to be relatively close to the EMA_9 or EMA_21, not sky-high touching upper BB
        dist_to_ema9_pct = (current_price - ema_9) / ema_9 * 100
        
        if current_price >= bb_upper:
            reasoning.append(f"Price piercing upper Bollinger Band — overextended")
            return self._hold_response(reasoning)
            
        if dist_to_ema9_pct > 1.0:  # Too far away from the fast moving average
            reasoning.append(f"Price too far from EMA_9 (+{dist_to_ema9_pct:.2f}%) — wait for dip")
            return self._hold_response(reasoning)
            
        reasoning.append(f"✅ Good Entry Proximity (dist EMA9={dist_to_ema9_pct:.2f}%)")
        
        # ===== SCORING AND CONFIDENCE =====
        # Base confidence for clearing all strict gates
        confidence = 0.65
        
        # Bonus for RSI in the absolute prime zone
        if 55 <= rsi <= 65:
            confidence += 0.05
            
        # Bonus for a very clean pullback (touching or slightly below EMA 9 but above EMA 21)
        if dist_to_ema9_pct <= 0.2 and current_price > ema_21:
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
