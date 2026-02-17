"""
Groq API client for AI-powered trading decisions
Ultra-fast LLM inference with structured JSON outputs
"""

from groq import Groq
import json
import time
import asyncio
from typing import Dict, Any, Optional
from loguru import logger

from app.core.config import get_settings


class GroqTradingEngine:
    """
    Groq AI client optimized for trading decisions
    - Temperature 0.05 for consistency
    - JSON mode enforced
    - Response validation pipeline
    - Timeout handling
    """
    
    def __init__(
        self,
        api_key: str = None,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.05,
        max_tokens: int = 1500,
        timeout: int = 8
    ):
        self.client = Groq(api_key=api_key or get_settings().GROQ_API_KEY)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        
        logger.info(f"🤖 Groq Trading Engine initialized - Model: {self.model}")
    
    async def get_decision(
        self,
        system_prompt: str,
        market_context: str
    ) -> Dict[str, Any]:
        """
        Get AI trading decision with validation
        
        Args:
            system_prompt: Comprehensive trading system instructions
            market_context: Current market data formatted for LLM
            
        Returns:
            Validated decision dict with confidence, reasoning, etc.
        """
        start = time.time()
        
        try:
            # Call Groq API
            response = await asyncio.wait_for(
                self._call_groq_api(system_prompt, market_context),
                timeout=self.timeout
            )
            
            elapsed_ms = int((time.time() - start) * 1000)
            raw_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            
            # Parse JSON
            decision = json.loads(raw_text)
            
            # Validate structure
            decision = self._validate_response(decision)
            
            # Add metadata
            decision["_meta"] = {
                "response_time_ms": elapsed_ms,
                "tokens_used": tokens_used,
                "model": self.model,
                "temperature": self.temperature
            }
            
            logger.info(
                f"🧠 Groq decision: {decision['decision']} "
                f"(conf: {decision['confidence']:.2f}, {elapsed_ms}ms)"
            )
            
            return decision
            
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Groq timeout after {self.timeout}s")
            return self._error_response("timeout")
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Groq returned invalid JSON: {e}")
            return self._error_response("invalid_json")
            
        except Exception as e:
            logger.error(f"❌ Groq API error: {e}")
            return self._error_response(str(e))
    
    async def _call_groq_api(self, system_prompt: str, user_message: str):
        """Async wrapper for Groq API call"""
        return await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"}  # Force JSON mode
        )
    
    def _validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and sanitize Groq response
        
        Checks:
        - Required fields present
        - Valid decision values
        - Confidence bounds (0.0-0.95 max)
        - Stake bounds (0.3%-2.0%)
        - Devil's advocate check
        """
        errors = []
        warnings = []
        
        # 1. Required fields
        required = ["decision", "confidence", "reasoning_chain"]
        for field in required:
            if field not in response:
                errors.append(f"missing_{field}")
        
        if errors:
            logger.warning(f"⚠️ Groq response validation failed: {errors}")
            return self._error_response(f"validation_failed: {errors}")
        
        # 2. Valid decision
        if response["decision"] not in ["CALL", "PUT", "HOLD"]:
            logger.warning(f"⚠️ Invalid decision: {response['decision']}")
            response["decision"] = "HOLD"
            warnings.append("invalid_decision_forced_hold")
        
        # 3. Confidence cap at 0.95
        if response["confidence"] > 0.95:
            logger.warning(f"⚠️ Overconfident: {response['confidence']} → capping at 0.85")
            response["confidence"] = 0.85
            warnings.append("confidence_capped")
        
        # 4. Confidence threshold for trading
        if response["confidence"] < 0.60 and response["decision"] != "HOLD":
            logger.info(f"📉 Low confidence ({response['confidence']}) → forcing HOLD")
            response["decision"] = "HOLD"
            warnings.append("low_confidence_forced_hold")
        
        # 5. Check devil's advocate (counter_arguments)
        chain = response.get("reasoning_chain", {})
        counter_args = chain.get("step5_counter_arguments", [])
        
        if not counter_args and response["decision"] != "HOLD":
            logger.warning("⚠️ No counter_arguments found - reducing confidence")
            response["confidence"] = max(0, response["confidence"] - 0.10)
            warnings.append("missing_counter_arguments")
        
        # 6. BUY/SELL requires contract_type
        if response["decision"] in ["CALL", "PUT"]:
            if not response.get("contract_type"):
                logger.warning("⚠️ CALL/PUT without contract_type → forcing HOLD")
                response["decision"] = "HOLD"
                warnings.append("missing_contract_type")
        
        # 7. Stake bounds
        stake = response.get("stake_percentage", 1.0)
        if stake > 2.0:
            response["stake_percentage"] = 2.0
            warnings.append("stake_capped_at_2pct")
        if stake < 0.3 and response["decision"] != "HOLD":
            response["stake_percentage"] = 0.3
            warnings.append("stake_min_0_3pct")
        
        if warnings:
            response["_warnings"] = warnings
        
        return response
    
    def _error_response(self, error_type: str) -> Dict[str, Any]:
        """Standard error response - always HOLD with 0 confidence"""
        return {
            "decision": "HOLD",
            "confidence": 0.0,
            "contract_type": None,
            "stake_percentage": 0.0,
            "reasoning_chain": {},
            "error": error_type,
            "_meta": {
                "response_time_ms": 0,
                "tokens_used": 0,
                "model": self.model
            }
        }


# Singleton instance
groq_engine = None

def get_groq_engine() -> GroqTradingEngine:
    """Get or create Groq engine singleton"""
    global groq_engine
    if groq_engine is None:
        groq_engine = GroqTradingEngine()
    return groq_engine
