"""
Layer 2: Groq AI Decision Engine
Meta-analysis layer that reads Layer 1 signals and applies LLM reasoning
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from loguru import logger

from app.services.groq_client import get_groq_engine
from app.prompts.trading_system_prompt import get_system_prompt
from app.analysis.meta_confidence import get_meta_confidence


class Layer2GroqEngine:
    """
    AI-powered meta-analysis layer
    
    Reads Layer 1 statistical signals and applies:
    - Chain-of-thought reasoning
    - Confluence detection
    - Regime-aware decision making
    - Self-calibrated confidence
    """
    
    def __init__(self):
        self.groq = get_groq_engine()
        self.system_prompt = get_system_prompt()
        self.meta_confidence = get_meta_confidence()
        
        logger.info("🧠 Layer 2 Groq Engine initialized")
    
    async def analyze(
        self,
        layer1_signal: Dict[str, Any],
        candles: List[Any] = None,
        db: Any = None
    ) -> Dict[str, Any]:
        """
        Analyze market using Groq AI
        
        Args:
            layer1_signal: Output from layer1_engine.analyze()
            candles: Recent candles for context (optional)
            db: Database session for logging (optional)
            
        Returns:
            Enhanced decision with Groq reasoning
        """
        try:
            # Format market context for LLM
            market_context = self._format_market_context(layer1_signal, candles)
            
            # Get Groq decision
            groq_decision = await self.groq.get_decision(
                system_prompt=self.system_prompt,
                market_context=market_context
            )
            
            # Apply meta-confidence adjustment
            groq_decision = self._apply_meta_confidence(groq_decision)
            
            # Groq is the FINAL decision maker
            # L1 warnings (RSI, momentum, etc.) are in the reasoning text that Groq reads
            # No guard needed — Groq has its own safeguards (counter-arguments, meta-confidence)
            l1_signal = layer1_signal.get('final_signal', 'HOLD')
            groq_sig = groq_decision.get('decision', 'HOLD')
            groq_conf = groq_decision.get('confidence', 0.0)
            
            if l1_signal != groq_sig:
                logger.info(f"🔄 Groq overrides L1: L1={l1_signal} → Groq={groq_sig} (conf={groq_conf:.2f})")
            
            
            # Merge with Layer 1 for logging
            final_decision = self._merge_decisions(layer1_signal, groq_decision)
            
            # Save to Database if session provided
            if db:
                try:
                    from app.models.models import GroqDecisionLog
                    import json
                    import math
                    
                    def sanitize_for_json(obj):
                        """Recursively replace Infinity/NaN with None for JSON compliance"""
                        if isinstance(obj, float):
                            if math.isinf(obj) or math.isnan(obj):
                                return None
                            return obj
                        elif isinstance(obj, dict):
                            return {k: sanitize_for_json(v) for k, v in obj.items()}
                        elif isinstance(obj, list):
                            return [sanitize_for_json(v) for v in obj]
                        return obj
                    
                    # Sanitize inputs
                    safe_l1 = sanitize_for_json(layer1_signal)
                    safe_groq = sanitize_for_json(groq_decision)
                    
                    log_entry = GroqDecisionLog(
                        layer1_signals=safe_l1,
                        layer2_patterns={}, # Placeholder
                        market_context={"text": market_context},
                        groq_raw_response=json.dumps(safe_groq),
                        groq_parsed_decision=safe_groq,
                        decision=final_decision['decision'],
                        confidence=final_decision['confidence'],
                        reasoning=json.dumps(safe_groq.get('reasoning_chain', {})),
                        counter_arguments=json.dumps(safe_groq.get('reasoning_chain', {}).get('step5_counter_arguments', [])),
                        meta_confidence_score=safe_groq.get('_meta', {}).get('trust_multiplier', 0.5),
                        response_time_ms=safe_groq.get('_meta', {}).get('response_time_ms', 0),
                        tokens_used=safe_groq.get('_meta', {}).get('tokens_used', 0)
                    )
                    
                    db.add(log_entry)
                    db.commit()
                    logger.info("💾 Saved Layer 2 decision to DB")
                    
                except Exception as e:
                    db.rollback()
                    logger.error(f"❌ Failed to save Groq log to DB: {e}")
            
            logger.info(
                f"✅ Layer 2 final: {final_decision['decision']} "
                f"(L1: {layer1_signal.get('final_signal', 'N/A')}, "
                f"Groq: {groq_decision['decision']}, "
                f"conf: {final_decision['confidence']:.2f}, "
                f"duration: {final_decision.get('duration', 'N/A')}s)"
            )
            
            return final_decision
            
        except Exception as e:
            logger.error(f"❌ Layer 2 error: {e} - falling back to Layer 1")
            return layer1_signal  # Fallback to Layer 1 only
    
    def _format_market_context(
        self,
        layer1: Dict[str, Any],
        candles: List[Any] = None
    ) -> str:
        """
        Format Layer 1 signals into LLM-readable context
        
        Creates structured text with all relevant market data
        """
        # Extract Layer 1 metrics
        # Hurst
        hurst_signal = layer1.get('hurst_signal', {})
        hurst = hurst_signal.get('hurst', 0.5) if isinstance(hurst_signal, dict) else 0.5
        
        # O-U
        ou_sig = layer1.get('ou_signal', {})
        ou_dict = ou_sig if isinstance(ou_sig, dict) else {}
        ou_signal = ou_dict.get('deviation', 0.0) 
        ou_zscore = ou_dict.get('z_score', 0.0)
        
        # GARCH
        garch_sig = layer1.get('garch_signal', {})
        garch_dict = garch_sig if isinstance(garch_sig, dict) else {}
        garch_vol = garch_dict.get('current_volatility', 0.0)
        forecast_vol = garch_dict.get('forecast_volatility', 0.0)
        
        # Indicators
        indicators = layer1.get('indicators', {})
        if not isinstance(indicators, dict): indicators = {}
        
        rsi = indicators.get('rsi_14', 50)
        bb_position = indicators.get('bb_position', 0.5)
        macd_histogram = indicators.get('macd_histogram', 0)
        
        ema_20 = indicators.get('ema_20', 0)
        ema_50 = indicators.get('ema_50', 0)
        ema_trend = "bullish" if ema_20 > ema_50 else "bearish"
        
        ha_open = indicators.get('ha_open_0', 0)
        ha_close = indicators.get('ha_close_0', 0)
        ha_trend = "🟢 Bullish" if ha_close > ha_open else "🔴 Bearish"
        ha_context = f"\n- Heikin-Ashi Current: {ha_trend} (Open={ha_open:.2f}, Close={ha_close:.2f})"
        
        dist_ema21 = indicators.get('dist_ema21', 0)
        dist_context = f"\n- Distance to EMA21: {dist_ema21:.2f}%"
        
        # Recent price action
        recent_candles = ""
        if candles:
            # Use up to 25 candles for better trend context
            recent = candles[-25:]
            recent_candles = f"\nRecent {len(recent)} candles (1min timeframe):\n"
            for i, c in enumerate(recent, 1):
                try:
                    direction = "🟢" if float(c.close) > float(c.open) else "🔴"
                    # Compact format: Dir O H L C
                    recent_candles += f"{direction} #{i}: O{float(c.open):.2f} H{float(c.high):.2f} L{float(c.low):.2f} C{float(c.close):.2f}\n"
                except Exception:
                    pass
        
        # Build context
        context = f"""
**MARKET DATA FOR R_100 VOLATILITY INDEX**

## Layer 1 Statistical Signals

**Regime Detection:**
- Hurst Exponent: {hurst:.4f} ({'MEAN-REVERT' if hurst < 0.45 else 'RANDOM' if hurst < 0.55 else 'TRENDING'})

**Mean Reversion (Ornstein-Uhlenbeck):**
- O-U Signal: {ou_signal:.2f} ({'overbought' if ou_signal > 0 else 'oversold'})
- Z-Score: {ou_zscore:.2f} STD from equilibrium
- Interpretation: {'Extreme deviation - reversal likely' if abs(ou_zscore) > 2 else 'Mild deviation' if abs(ou_zscore) > 1 else 'Near equilibrium'}

**Volatility (GARCH):**
- Current Volatility: {garch_vol:.6f}
- Forecast Volatility: {forecast_vol:.6f}
- Change: {((forecast_vol / (garch_vol or 1) - 1) * 100):.1f}% ({'rising' if forecast_vol > garch_vol else 'falling'})

**Technical Indicators:**
- RSI(14): {rsi:.1f} ({'oversold' if rsi < 30 else 'overbought' if rsi > 70 else 'neutral'})
- Bollinger Position: {bb_position:.2f} (0=lower band, 0.5=middle, 1=upper band)
- MACD Histogram: {macd_histogram:.4f} ({'bullish' if macd_histogram > 0 else 'bearish'})
- EMA Trend (20/50): {ema_trend}{ha_context}{dist_context}

**Price Action:**{recent_candles}

**Layer 1 Recommendation:**
- Decision: {layer1.get('final_signal', 'UNKNOWN')}
- Confidence: {layer1.get('final_confidence', 0):.2f}
- Reason: {layer1.get('reasoning', 'N/A')}

**Direction Alignment (pre-computed):**
- Price Direction (last 5 candles): {layer1.get('price_direction', 'UNKNOWN')}
- Direction Aligned with L1 Signal: {layer1.get('direction_aligned', 'UNKNOWN')}
- Last 5 Closes: {layer1.get('last_5_closes', [])}
- RSI Extreme: {layer1.get('rsi_extreme', False)}

---

**YOUR TASK**: Analyze the above data using your 7-step reasoning process. Use the Direction Alignment data to adjust confidence:
- If Direction Aligned = True → maintain or boost L1 confidence (GREEN LIGHT)
- If Direction Aligned = False → reduce confidence by 0.15
- If RSI Extreme = True → reduce confidence by an additional 0.20
Output your decision as JSON with full reasoning_chain."""
        
        return context.strip()
    
    def _apply_meta_confidence(self, groq_decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adjust Groq's confidence based on historical accuracy
        
        If Groq has been wrong lately, reduce trust
        """
        if not self.meta_confidence.is_statistically_significant:
            # Not enough data yet - use Groq as-is
            groq_decision['_meta']['trust_multiplier'] = 1.0
            groq_decision['_meta']['meta_note'] = "Insufficient history for adjustment"
            return groq_decision
        
        # Get trust multiplier
        trust = self.meta_confidence.trust_multiplier
        original_conf = groq_decision['confidence']
        adjusted_conf = original_conf * trust
        
        groq_decision['confidence'] = adjusted_conf
        groq_decision['_meta']['trust_multiplier'] = trust
        groq_decision['_meta']['original_confidence'] = original_conf
        groq_decision['_meta']['meta_stats'] = self.meta_confidence.get_stats()
        
        logger.info(
            f"🎯 Meta-confidence adjustment: {original_conf:.2f} → {adjusted_conf:.2f} "
            f"(trust={trust:.2f}, accuracy={self.meta_confidence.accuracy:.2f})"
        )
        
        # Re-validate after adjustment
        if adjusted_conf < 0.70 and groq_decision['decision'] != 'HOLD':
            logger.info(f"📉 Adjusted confidence too low ({adjusted_conf:.2f}) → forcing HOLD")
            groq_decision['decision'] = 'HOLD'
        
        return groq_decision
    
    def _merge_decisions(
        self,
        layer1: Dict[str, Any],
        groq: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge Layer 1 and Groq decisions for logging
        
        Groq overrides Layer 1, but we keep both for comparison
        """
        # Start with Layer 1 to preserve context (symbol, price, technicals)
        merged = layer1.copy()
        
        # Save original Layer 1 decision before overwriting
        merged['layer1_decision'] = layer1.get('final_signal')
        merged['layer1_confidence'] = layer1.get('final_confidence')
        merged['layer1_reason'] = layer1.get('reasoning')
        
        # 🚀 FULL_CONTROL MODE: Groq can create trades independently
        # (VETO_ONLY mode disabled - Groq not restricted by Layer 1 HOLD)
        merged['final_signal'] = groq['decision']
        merged['final_confidence'] = groq['confidence']
        merged['decision'] = groq['decision']
        merged['confidence'] = groq['confidence']
        
        # Handle reasoning (convert dict to summary string for legacy compatibility)
        
        # Handle reasoning (convert dict to summary string for legacy compatibility)
        if isinstance(groq.get('reasoning_chain'), dict):
            summary = groq['reasoning_chain'].get('step6_final_decision_rationale', 'Groq Analysis')
            merged['reasoning'] = summary
        else:
            merged['reasoning'] = str(groq.get('reasoning_chain', 'Groq Analysis'))

        # Add Groq specific fields
        merged['groq_decision'] = groq['decision']
        merged['groq_confidence'] = groq['confidence']
        merged['layer'] = "groq_layer2"
        merged['_meta'] = groq.get('_meta', {})
        merged['_warnings'] = groq.get('_warnings', [])
        
        # Preserve or update contract details if Groq suggests changes
        if groq.get('contract_type'):
            merged['contract_type'] = groq['contract_type']
            
        if groq.get('stake_percentage'):
            merged['suggested_stake_multiplier'] = groq['stake_percentage']

        return merged
    
    def record_trade_outcome(
        self,
        trade_id: int,
        predicted_confidence: float,
        actual_outcome: str,  # "WIN" or "LOSS"
        decision: str
    ):
        """
        Record trade outcome for meta-confidence tracking
        
        Call this when a trade closes
        """
        was_correct = (actual_outcome == "WIN")
        self.meta_confidence.record_outcome(
            predicted_confidence=predicted_confidence,
            was_correct=was_correct,
            decision=decision
        )
        
        logger.info(
            f"📝 Recorded outcome for trade #{trade_id}: "
            f"{actual_outcome} (predicted conf: {predicted_confidence:.2f})"
        )


# Singleton instance
_layer2_engine = None

def get_layer2_engine() -> Layer2GroqEngine:
    """Get or create Layer 2 engine singleton"""
    global _layer2_engine
    if _layer2_engine is None:
        _layer2_engine = Layer2GroqEngine()
    return _layer2_engine
