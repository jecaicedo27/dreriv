"""
OpenAI API client for AI-powered trading decisions
GPT-5.2 as alternative to Groq/Llama for Layer 2
"""

from openai import OpenAI
import json
import time
import asyncio
from typing import Dict, Any, Optional
from loguru import logger

from app.core.config import get_settings


class OpenAITradingEngine:
    """
    OpenAI client for trading decisions
    - Same interface as GroqTradingEngine
    - Uses GPT-5.2 for potentially better reasoning
    - JSON mode enforced
    """
    
    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        temperature: float = 0.05,
        max_tokens: int = 1500,
        timeout: int = 15
    ):
        settings = get_settings()
        resolved_key = api_key or settings.OPENAI_API_KEY
        
        # Fallback: read directly from .env if not in env vars
        if not resolved_key:
            try:
                import os
                env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), '.env')
                if os.path.exists(env_path):
                    with open(env_path) as f:
                        for line in f:
                            if line.startswith('OPENAI_API_KEY='):
                                resolved_key = line.strip().split('=', 1)[1]
                                logger.info(f"🔑 OpenAI key loaded from .env file")
                                break
            except Exception as e:
                logger.warning(f"⚠️ Could not read .env: {e}")
        
        self.client = OpenAI(api_key=resolved_key)
        self.model = model or settings.OPENAI_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        
        logger.info(f"🤖 OpenAI Trading Engine initialized - Model: {self.model}")
    
    async def get_decision(
        self,
        system_prompt: str,
        market_context: str
    ) -> Dict[str, Any]:
        """
        Get AI trading decision - same interface as GroqTradingEngine
        """
        start = time.time()
        
        try:
            response = await asyncio.wait_for(
                self._call_openai_api(system_prompt, market_context),
                timeout=self.timeout
            )
            
            elapsed_ms = int((time.time() - start) * 1000)
            raw_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0
            
            # Parse JSON
            decision = json.loads(raw_text)
            
            # Validate structure (same as Groq)
            decision = self._validate_response(decision)
            
            # Add metadata
            decision["_meta"] = {
                "response_time_ms": elapsed_ms,
                "tokens_used": tokens_used,
                "model": self.model,
                "temperature": self.temperature,
                "provider": "openai"
            }
            
            logger.info(
                f"🧠 OpenAI decision: {decision['decision']} "
                f"(conf: {decision['confidence']:.2f}, {elapsed_ms}ms, {tokens_used} tokens)"
            )
            
            return decision
            
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ OpenAI timeout after {self.timeout}s")
            return self._error_response("timeout")
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ OpenAI returned invalid JSON: {e}")
            return self._error_response("invalid_json")
            
        except Exception as e:
            logger.error(f"❌ OpenAI API error: {e}")
            return self._error_response(str(e))
    
    async def _call_openai_api(self, system_prompt: str, user_message: str):
        """Async wrapper for OpenAI API call"""
        params = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=self.temperature,
            response_format={"type": "json_object"}
        )
        # GPT-5.x uses max_completion_tokens, older models use max_tokens
        if self.model.startswith("gpt-5"):
            params["max_completion_tokens"] = self.max_tokens
        else:
            params["max_tokens"] = self.max_tokens
        
        return await asyncio.to_thread(
            self.client.chat.completions.create,
            **params
        )
    
    def _validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize - same logic as Groq"""
        errors = []
        warnings = []
        
        # Required fields
        required = ["decision", "confidence", "reasoning_chain"]
        for field in required:
            if field not in response:
                errors.append(f"missing_{field}")
        
        if errors:
            logger.warning(f"⚠️ OpenAI response validation failed: {errors}")
            return self._error_response(f"validation_failed: {errors}")
        
        # Valid decision
        if response["decision"] not in ["CALL", "PUT", "HOLD"]:
            logger.warning(f"⚠️ Invalid decision: {response['decision']}")
            response["decision"] = "HOLD"
            warnings.append("invalid_decision_forced_hold")
        
        # Confidence cap at 0.95
        if response["confidence"] > 0.95:
            response["confidence"] = 0.85
            warnings.append("confidence_capped")
        
        # Confidence threshold
        if response["confidence"] < 0.55 and response["decision"] != "HOLD":
            logger.info(f"📉 Low confidence ({response['confidence']}) → forcing HOLD")
            response["decision"] = "HOLD"
            warnings.append("low_confidence_forced_hold")
        
        # Contract type check
        if response["decision"] in ["CALL", "PUT"]:
            if not response.get("contract_type"):
                response["decision"] = "HOLD"
                warnings.append("missing_contract_type")
        
        # Stake bounds
        stake = response.get("stake_percentage", 1.0)
        if stake > 2.0:
            response["stake_percentage"] = 2.0
        if stake < 0.3 and response["decision"] != "HOLD":
            response["stake_percentage"] = 0.3
        
        if warnings:
            response["_warnings"] = warnings
        
        return response
    
    def _error_response(self, error_type: str) -> Dict[str, Any]:
        """Standard error response"""
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
                "model": self.model,
                "provider": "openai"
            }
        }


# Singleton
openai_engine = None

def get_openai_engine() -> OpenAITradingEngine:
    """Get or create OpenAI engine singleton"""
    global openai_engine
    if openai_engine is None:
        openai_engine = OpenAITradingEngine()
    return openai_engine
