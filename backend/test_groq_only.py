"""
Groq-Only Test Mode
Bypass Layer 1 and send 200 candles directly to Groq for decision
"""

import asyncio
from typing import Dict, Any
from loguru import logger
from sqlalchemy.orm import Session

from app.services.groq_client import get_groq_engine
from app.core.database import get_db
from app.models.models import Candle


async def test_groq_only_decision(db: Session) -> Dict[str, Any]:
    """
    Test Groq decision making with raw candle data (bypass Layer 1)
    
    Fetches 200 1-minute candles and sends directly to Groq
    """
    try:
        # 1. Fetch last 200 candles
        candles = db.query(Candle)\
            .filter(Candle.symbol == 'R_100')\
            .filter(Candle.interval == '1m')\
            .order_by(Candle.timestamp.desc())\
            .limit(200)\
            .all()
        
        if len(candles) < 200:
            return {
                "error": "Not enough candles",
                "available": len(candles),
                "required": 200
            }
        
        # Reverse to chronological order
        candles = list(reversed(candles))
        
        # 2. Format market context for Groq
        market_context = _format_raw_candles_for_groq(candles)
        
        # 3. Get Groq system prompt (raw trading analysis)
        system_prompt = """You are an elite AI trading analyst for Deriv.com synthetic indices (R_100).

You will receive 200 1-minute candles (OHLCV data).

Your job: Analyze the raw price action and decide CALL, PUT, or HOLD.

## ANALYSIS FRAMEWORK

1. **Trend Detection**
   - Look at the last 20-50 candles
   - Is price making higher highs + higher lows? → BULLISH
   - Is price making lower highs + lower lows? → BEARISH
   - Choppy/sideways? → HOLD

2. **Momentum**
   - Are recent candles getting bigger (increasing volatility)?
   - Are candles predominantly green or red?
   - Is there acceleration or deceleration?

3. **Support/Resistance**
   - Has price bounced from a level multiple times?
   - Is price at/near a significant high or low?
   - Is there a clear breakout or breakdown?

4. **Reversal Signals**
   - Long wicks with small bodies (rejection)
   - Series of small candles after big move (consolidation)
   - Doji or hammer patterns

5. **Decision Rules**
   - **CALL**: Clear uptrend + bullish momentum + no resistance nearby
   - **PUT**: Clear downtrend + bearish momentum + no support nearby
   - **HOLD**: Choppy, uncertain, or conflicting signals

## OUTPUT FORMAT (JSON)

{
  "decision": "CALL" | "PUT" | "HOLD",
  "confidence": 0.0-0.95,
  "contract_type": "CALL" | "PUT" | null,
  "reasoning_chain": {
    "trend": "BULLISH/BEARISH/NEUTRAL",
    "momentum": "STRONG/WEAK/NEUTRAL",
    "key_levels": "Description of support/resistance",
    "signals": ["Signal 1", "Signal 2", ...],
    "counter_arguments": ["Why this could fail 1", "Why this could fail 2", ...]
  }
}

**CRITICAL**: Confidence must reflect TRUE win probability. Be honest. Min 0.70 to trade.
"""
        
        # 4. Call Groq
        logger.info("🧪 Testing Groq-only decision (200 candles, bypass Layer 1)")
        
        groq = get_groq_engine()
        decision = await groq.get_decision(
            system_prompt=system_prompt,
            market_context=market_context
        )
        
        # 5. Log results
        logger.success(
            f"🎯 Groq-only decision: {decision['decision']} "
            f"(conf: {decision.get('confidence', 0):.2f})"
        )
        
        return {
            "status": "success",
            "decision": decision,
            "candles_analyzed": len(candles),
            "latest_price": candles[-1].close,
            "price_change_pct": ((candles[-1].close - candles[0].close) / candles[0].close) * 100
        }
        
    except Exception as e:
        logger.error(f"❌ Groq-only test failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def _format_raw_candles_for_groq(candles) -> str:
    """
    Format candles as readable text for Groq
    """
    latest = candles[-1]
    
    # Summary statistics
    start_price = candles[0].close
    end_price = candles[-1].close
    price_change = end_price - start_price
    price_change_pct = (price_change / start_price) * 100
    
    high = max(c.high for c in candles)
    low = min(c.low for c in candles)
    volatility = high - low
    
    # Recent candles (last 20)
    recent_candles = candles[-20:]
    green_candles = sum(1 for c in recent_candles if c.close > c.open)
    red_candles = len(recent_candles) - green_candles
    
    # Format output
    text = f"""# Market Data: R_100 (200 1-minute candles)

## Summary
- **Current Price**: {latest.close:.2f}
- **Price Change**: {price_change:+.2f} ({price_change_pct:+.2f}%)
- **Range**: {low:.2f} - {high:.2f} (volatility: {volatility:.2f})
- **Recent Momentum** (last 20): {green_candles} green / {red_candles} red

## Last 50 Candles (most recent)
"""
    
    # Show last 50 candles in table format
    text += "```\n"
    text += "Time       | Open    | High    | Low     | Close   | Type\n"
    text += "-" * 65 + "\n"
    
    for candle in candles[-50:]:
        candle_type = "🟢" if candle.close > candle.open else "🔴"
        time_str = candle.timestamp.strftime("%H:%M")
        text += f"{time_str}   | {candle.open:7.2f} | {candle.high:7.2f} | {candle.low:7.2f} | {candle.close:7.2f} | {candle_type}\n"
    
    text += "```\n\n"
    
    # Add pattern hints
    text += "## Pattern Recognition Hints\n"
    text += "- Look for higher highs/higher lows (uptrend)\n"
    text += "- Look for lower highs/lower lows (downtrend)\n"
    text += "- Identify key support/resistance levels\n"
    text += "- Check for reversal patterns (long wicks, doji)\n"
    text += "- Assess momentum (are candles getting bigger/smaller?)\n\n"
    
    text += f"**Current Price**: {latest.close:.2f}\n"
    text += f"**Your Decision**: CALL, PUT, or HOLD?\n"
    
    return text


# Main test function
async def main():
    """Run Groq-only test"""
    from app.core.database import SessionLocal
    
    db = SessionLocal()
    try:
        result = await test_groq_only_decision(db)
        
        print("\n" + "=" * 60)
        print("GROQ-ONLY TEST RESULT")
        print("=" * 60)
        print(f"Status: {result.get('status')}")
        
        if result.get('status') == 'success':
            decision = result['decision']
            print(f"\nDecision: {decision.get('decision')}")
            print(f"Confidence: {decision.get('confidence', 0):.2%}")
            print(f"Candles Analyzed: {result.get('candles_analyzed')}")
            print(f"Latest Price: {result.get('latest_price'):.2f}")
            print(f"Price Change: {result.get('price_change_pct'):+.2f}%")
            
            reasoning = decision.get('reasoning_chain', {})
            if reasoning:
                print(f"\nTrend: {reasoning.get('trend', 'N/A')}")
                print(f"Momentum: {reasoning.get('momentum', 'N/A')}")
                
                signals = reasoning.get('signals', [])
                if signals:
                    print("\nSignals:")
                    for s in signals:
                        print(f"  - {s}")
        else:
            print(f"Error: {result.get('error')}")
        
        print("=" * 60 + "\n")
        
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
