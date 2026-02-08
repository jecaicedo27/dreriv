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
            
            # Merge with Layer 1 for logging
            final_decision = self._merge_decisions(layer1_signal, groq_decision)
            
            # Save to Database if session provided
            if db:
                try:
                    from app.models.models import GroqDecisionLog
                    import json
                    
                    log_entry = GroqDecisionLog(
                        layer1_signals=layer1_signal,
                        layer2_patterns={}, # Placeholder
                        market_context={"text": market_context},
                        groq_raw_response=json.dumps(groq_decision),
                        groq_parsed_decision=groq_decision,
                        decision=final_decision['decision'],
                        confidence=final_decision['confidence'],
                        reasoning=json.dumps(groq_decision.get('reasoning_chain', {})),
                        counter_arguments=json.dumps(groq_decision.get('reasoning_chain', {}).get('step5_counter_arguments', [])),
                        meta_confidence_score=groq_decision.get('_meta', {}).get('trust_multiplier', 0.5),
                        response_time_ms=groq_decision.get('_meta', {}).get('response_time_ms', 0),
                        tokens_used=groq_decision.get('_meta', {}).get('tokens_used', 0)
                    )
                    
                    db.add(log_entry)
                    db.commit()
                    logger.info("💾 Saved Layer 2 decision to DB")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to save Groq log to DB: {e}")
            
            logger.info(
                f"✅ Layer 2 final: {final_decision['decision']} "
                f"(L1: {layer1_signal.get('final_signal', 'N/A')}, "
                f"Groq: {groq_decision['decision']}, "
                f"conf: {final_decision['confidence']:.2f})"
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
        
        # Recent price action
        recent_candles = ""
        if candles and len(candles) >= 3:
            recent = candles[-3:]
            recent_candles = f"\nRecent 3 candles:\n"
            for i, c in enumerate(recent, 1):
                try:
                    direction = "🟢" if float(c.close) > float(c.open) else "🔴"
                    recent_candles += f"  {direction} Candle {i}: O={c.open} H={c.high} L={c.low} C={c.close}\n"
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
- EMA Trend (20/50): {ema_trend}

**Price Action:**{recent_candles}

**Layer 1 Recommendation:**
- Decision: {layer1.get('final_signal', 'UNKNOWN')}
- Confidence: {layer1.get('final_confidence', 0):.2f}
- Reason: {layer1.get('reasoning', 'N/A')}

---

**YOUR TASK**: Analyze the above data using your 7-step reasoning process. Output your decision as JSON with full reasoning_chain."""
        
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
        
        # Overwrite with Groq decision
        merged['final_signal'] = groq['decision']
        merged['final_confidence'] = groq['confidence']
        merged['decision'] = groq['decision'] # Keep 'decision' for legacy/logging check
        merged['confidence'] = groq['confidence'] # Required for DB logging in analyze()
        
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
