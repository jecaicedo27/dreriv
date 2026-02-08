---
name: groq-trading-decisions
description: "Groq API integration for AI-powered trading decisions. Use when building the Groq decision layer, crafting trading system prompts, implementing chain-of-thought reasoning for trades, validating LLM JSON responses, implementing anti-hallucination safeguards, or building a meta-confidence tracking system for LLM accuracy in trading contexts."
---

# Groq AI Trading Decision Engine

## Overview

Specialized patterns for using Groq's ultra-fast LLM inference as an intelligent decision layer in an automated trading system. Covers prompt engineering for trading, anti-hallucination techniques, response validation, meta-confidence tracking, and fallback strategies.

## When to Use This Skill

- Integrating Groq API as a trading decision maker
- Writing system prompts that produce consistent, calibrated JSON responses
- Implementing chain-of-thought reasoning for trade analysis
- Building validation pipelines for LLM trading outputs
- Tracking LLM accuracy over time (meta-confidence)
- Implementing fallback when Groq is unavailable

## Do Not Use This Skill When

- Using Groq for general-purpose chat or text generation
- Building trading systems that don't involve LLM decision-making
- Working with other LLM providers (patterns are Groq-optimized)

## Groq API Integration Pattern

### Client Setup
```python
from groq import Groq
import json
import time

class GroqTradingEngine:
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.client = Groq(api_key=api_key)
        self.model = model
        self.temperature = 0.05    # Near-zero for consistency
        self.max_tokens = 1500     # Enough for chain-of-thought + JSON
        self.timeout = 8           # Seconds
        
    async def get_decision(self, system_prompt: str, market_context: str) -> dict:
        start = time.time()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": market_context}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"}  # Force JSON mode
            )
            
            elapsed_ms = int((time.time() - start) * 1000)
            raw_text = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            
            # Parse and validate
            decision = self._validate_response(json.loads(raw_text))
            decision["_meta"] = {
                "response_time_ms": elapsed_ms,
                "tokens_used": tokens_used,
                "model": self.model
            }
            return decision
            
        except json.JSONDecodeError:
            return {"decision": "WAIT", "confidence": 0, "error": "invalid_json"}
        except Exception as e:
            return {"decision": "WAIT", "confidence": 0, "error": str(e)}
```

### Critical: response_format Parameter
Always use `response_format={"type": "json_object"}` with Groq. This forces the model to output valid JSON and eliminates markdown wrapping issues.

## System Prompt Engineering for Trading

### Key Principles

1. **Temperature 0.05**: Same market data → same decision. Never use > 0.1 for trading.
2. **Chain of Thought FIRST, then decision**: Force the model to reason before concluding.
3. **Devil's Advocate step**: Model must find reasons NOT to trade before deciding.
4. **Calibrated confidence**: Define what each confidence level MEANS explicitly.
5. **Anti-hallucination rules**: Explicit instructions to prevent inventing signals.

### System Prompt Structure (Recommended Order)

```
1. ROLE DEFINITION — What the model is and what it does
2. FUNDAMENTAL PRINCIPLES — Core philosophy (preservation > profit)
3. DOMAIN KNOWLEDGE — Instrument-specific facts (synthetics are algorithmic, etc.)
4. REASONING PROCESS — Numbered steps to follow IN ORDER
5. ANTI-HALLUCINATION RULES — What the model must NEVER do
6. RISK RULES — Hard constraints that override everything
7. CONFIDENCE CALIBRATION — What each confidence level means
8. OUTPUT FORMAT — JSON schema with every field defined
9. FEW-SHOT EXAMPLES — 3 examples: good BUY, good WAIT, good Crash/Boom trade
```

### Anti-Hallucination Rules (Include These Verbatim)

```
ANTI-HALLUCINATION RULES:
1. Do NOT invent confluences. If only 1 signal is clear, say WAIT.
2. Do NOT interpret ambiguous data as signals. RSI at 45 is NOT "approaching oversold."
3. Do NOT ignore contradictory signals to justify a trade.
4. If pgvector data shows < 5 similar patterns, it does NOT count as a confluence.
5. If Hurst exponent is 0.45-0.55, any directional signal loses one confluence.
6. NEVER output confidence > 0.95. If you're that confident, you're hallucinating.
7. If your counter_arguments list is empty, add "insufficient devil's advocate analysis" and reduce confidence by 0.10.
```

### Confidence Calibration Block

```
CONFIDENCE CALIBRATION:
0.70-0.75: Acceptable setup. Minimum confluences met. Some uncertainty. MIN stake.
0.76-0.82: Good setup. Multiple confluences. Controlled risk. NORMAL stake.
0.83-0.89: Strong setup. Everything aligned. Low risk. INCREASED stake.
0.90-0.95: Exceptional. Rarely occurs. Only when ALL data agrees. MAX stake.
> 0.95: IMPOSSIBLE. Reduce to 0.85 — you are overconfident.
```

### Few-Shot Examples

Include 3 examples in the system prompt:
1. **Correct BUY** with full reasoning chain (shows good analysis)
2. **Correct WAIT** with insufficient data (shows restraint is valued)
3. **Correct Crash/Boom trade** in hot zone (shows domain knowledge)

Each example should show the complete JSON output including reasoning_chain.

## Response Validation Pipeline

```python
def validate_groq_response(response: dict) -> tuple[bool, dict]:
    """
    Validate and sanitize Groq's trading decision.
    Returns (is_valid, sanitized_response)
    """
    errors = []
    
    # 1. Required fields
    required = ["decision", "confidence", "reasoning_chain"]
    for field in required:
        if field not in response:
            errors.append(f"Missing required field: {field}")
    
    if errors:
        return False, {"decision": "WAIT", "errors": errors}
    
    # 2. Decision must be valid
    if response["decision"] not in ["BUY", "SELL", "WAIT"]:
        return False, {"decision": "WAIT", "errors": ["Invalid decision value"]}
    
    # 3. Confidence cap at 0.95
    if response.get("confidence", 0) > 0.95:
        response["confidence"] = 0.85  # Auto-reduce overconfidence
        response["_warnings"] = response.get("_warnings", []) + ["confidence_capped"]
    
    # 4. Confidence threshold
    if response["confidence"] < 0.70 and response["decision"] != "WAIT":
        response["decision"] = "WAIT"  # Force WAIT on low confidence
    
    # 5. Check counter_arguments exist (devil's advocate)
    chain = response.get("reasoning_chain", {})
    counter_args = chain.get("step5_counter_arguments", [])
    if not counter_args and response["decision"] != "WAIT":
        response["confidence"] = max(0, response["confidence"] - 0.10)
        response["_warnings"] = response.get("_warnings", []) + ["no_counter_arguments"]
    
    # 6. Coherence: BUY/SELL must have contract_type
    if response["decision"] in ["BUY", "SELL"] and not response.get("contract_type"):
        return False, {"decision": "WAIT", "errors": ["BUY/SELL without contract_type"]}
    
    # 7. Stake bounds
    stake = response.get("stake_percentage", 0)
    if stake > 2.0:
        response["stake_percentage"] = 2.0
    if stake < 0.3 and response["decision"] != "WAIT":
        response["stake_percentage"] = 0.3
    
    return True, response
```

## Meta-Confidence Tracking

Track Groq's accuracy over rolling windows to adjust trust:

```python
class GroqMetaConfidence:
    """Track how well Groq's predictions match reality"""
    
    def __init__(self, window_size=20):
        self.window_size = window_size
        self.recent_decisions = []  # [(confidence, was_correct)]
    
    def record_outcome(self, confidence: float, was_correct: bool):
        self.recent_decisions.append((confidence, was_correct))
        if len(self.recent_decisions) > self.window_size:
            self.recent_decisions.pop(0)
    
    @property
    def accuracy(self) -> float:
        if not self.recent_decisions:
            return 0.5
        correct = sum(1 for _, c in self.recent_decisions if c)
        return correct / len(self.recent_decisions)
    
    @property
    def calibration_error(self) -> float:
        """How well confidence matches actual accuracy"""
        if not self.recent_decisions:
            return 0
        avg_confidence = sum(c for c, _ in self.recent_decisions) / len(self.recent_decisions)
        return abs(avg_confidence - self.accuracy)
    
    @property
    def trust_multiplier(self) -> float:
        """Multiply Groq's confidence by this. <1 = reduce trust."""
        if self.accuracy >= 0.65:
            return 1.0      # Full trust
        elif self.accuracy >= 0.55:
            return 0.85      # Slight reduction
        elif self.accuracy >= 0.45:
            return 0.70      # Significant reduction
        else:
            return 0.50      # Groq is doing worse than random — halve influence
```

## Fallback Strategy When Groq is Unavailable

```python
async def get_trading_decision(self, market_data):
    """Decision with Groq fallback"""
    try:
        groq_decision = await asyncio.wait_for(
            self.groq_engine.get_decision(self.system_prompt, market_data),
            timeout=self.timeout
        )
        return groq_decision, "groq"
    except (asyncio.TimeoutError, Exception):
        # Fallback: only trade if mechanical + pgvector agree
        mechanical = self.get_mechanical_signal(market_data)
        pgvector = self.get_pgvector_signal(market_data)
        
        if (mechanical["confidence"] > 0.75 and 
            pgvector["confidence"] > 0.70 and
            mechanical["direction"] == pgvector["direction"]):
            return {
                "decision": mechanical["direction"],
                "confidence": min(mechanical["confidence"], pgvector["confidence"]) * 0.85,
                "stake_percentage": 1.0 * 0.5,  # Half stake without Groq
                "source": "mechanical_fallback"
            }, "fallback"
        
        return {"decision": "WAIT", "confidence": 0}, "fallback"
```

## Safety Rules

- **Never** let Groq override hardcoded risk limits (max stake, max loss, etc.)
- **Always** validate JSON before acting on it
- **Log** every Groq request and response for debugging
- **Track** tokens consumed daily for cost management
- **Monitor** response times — if consistently > 5s, consider model downgrade
