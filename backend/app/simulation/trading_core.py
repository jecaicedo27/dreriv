"""
TradingCore — THE SINGLE BRAIN.

One function to analyze candles. Everyone calls this:
  - Visual simulation (bot_step)
  - Multi-day simulation (replay_bot)
  - Live bot (future)

TradingCore.analyze() is a PURE STATIC function.
It receives an engine + data, returns a signal.
No internal state. No copies. One brain.
"""
from typing import Dict, Any


class TradingCore:
    """
    Single source of truth for ALL trading decisions.
    
    Usage:
        signal = TradingCore.analyze(engine, df, symbol, use_groq, ai_provider)
    
    The CALLER manages the engine lifecycle:
        - bot_step: uses _get_sim_engine(date)
        - replay_bot: creates Layer1SignalEngine()
        - live bot: uses self.signal_engine
    """

    @staticmethod
    def analyze(
        engine,
        df,
        symbol: str = "R_100",
        use_groq: bool = False,
        ai_provider: str = "groq",
        hurst_min: float = 0.6,
        hurst_max: float = 0.7,
        slope_min: float = 0.0,
        slope_lookback: int = 20,
    ) -> Dict[str, Any]:
        """
        Analyze candles and return a trading signal.
        
        Args:
            engine: Layer1SignalEngine instance (caller manages lifecycle)
            df: DataFrame with OHLC + indicators, ending at current candle
            symbol: Trading symbol
            use_groq: Whether to use AI Layer 2
            ai_provider: Which AI provider
            hurst_min: Min Hurst for trending trades
            hurst_max: Max Hurst for trending trades
            slope_min: Min |EMA21 slope| to trade (0 = disabled)
            slope_lookback: Candles for slope regression window
        """
        # ===== SLOPE FILTER =====
        if slope_min > 0:
            from app.analysis.indicators import TechnicalIndicators
            slope_info = TechnicalIndicators.compute_ema_slope(df, lookback=slope_lookback)
            if slope_info['slope_abs'] < slope_min:
                entry_price = float(df.iloc[-1]['close'])
                return {
                    'action': 'HOLD', 'confidence': 0.0, 'entry_price': round(entry_price, 2),
                    'groq_used': False, 'ai_provider': 'none', 'l1_signal': 'HOLD',
                    'l1_confidence': 0.0,
                    'reasoning': f"Mercado lateral (pendiente={slope_info['slope']:.4f} < {slope_min})",
                    'groq_reasoning': '', 'hurst': 0.5,
                }

        # ===== Window: last 250 candles =====
        start_idx = max(0, len(df) - 250)
        window = df.iloc[start_idx:].copy()

        # ===== LAYER 1: Statistical Analysis =====
        signal = engine.safe_analyze(window, symbol, hurst_min=hurst_min, hurst_max=hurst_max)

        l1_signal = signal.get("final_signal", "HOLD")
        l1_confidence = signal.get("final_confidence", 0.0)
        l1_reasoning = signal.get("reasoning", "")
        hurst_value = signal.get("hurst_signal", {}).get("hurst", 0.5)

        # ===== LAYER 2: AI Meta-Analysis =====
        groq_used = False
        final_signal = l1_signal
        final_confidence = l1_confidence
        groq_reasoning = ""

        # AI ONLY when L1 has directional signal — L1 is gatekeeper
        should_call_ai = use_groq and l1_signal in ["CALL", "PUT"]

        if should_call_ai:
            try:
                layer2 = TradingCore._get_layer2(ai_provider)

                # === PRE-COMPUTE direction alignment for AI ===
                last_5 = df.iloc[-5:]["close"].tolist() if len(df) >= 5 else df["close"].tolist()
                rising = sum(1 for i in range(1, len(last_5)) if last_5[i] > last_5[i - 1])
                falling = sum(1 for i in range(1, len(last_5)) if last_5[i] < last_5[i - 1])

                if rising >= 3:
                    price_direction = "RISING"
                elif falling >= 3:
                    price_direction = "FALLING"
                else:
                    price_direction = "MIXED"

                direction_aligned = (
                    (l1_signal == "CALL" and price_direction == "RISING")
                    or (l1_signal == "PUT" and price_direction == "FALLING")
                )

                rsi_val = float(df.iloc[-1].get("rsi_14", 50))
                rsi_extreme = (l1_signal == "CALL" and rsi_val > 70) or (
                    l1_signal == "PUT" and rsi_val < 35
                )

                # Inject pre-computed context into signal for AI
                signal["price_direction"] = price_direction
                signal["direction_aligned"] = direction_aligned
                signal["rsi_extreme"] = rsi_extreme
                signal["last_5_closes"] = [round(p, 2) for p in last_5]

                # Build simple candle objects for AI context (last 25)
                class SC:
                    def __init__(self, r):
                        self.open = float(r["open"])
                        self.high = float(r["high"])
                        self.low = float(r["low"])
                        self.close = float(r["close"])

                candle_start = max(0, len(df) - 25)
                candles_for_ai = [SC(df.iloc[j]) for j in range(candle_start, len(df))]

                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Already in async context — await directly not possible from static
                    # Use a nested approach
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        ai_result = pool.submit(
                            asyncio.run,
                            layer2.analyze(layer1_signal=signal, candles=candles_for_ai, db=None)
                        ).result()
                else:
                    ai_result = asyncio.run(
                        layer2.analyze(layer1_signal=signal, candles=candles_for_ai, db=None)
                    )

                groq_used = True
                final_signal = ai_result.get("decision", ai_result.get("final_signal", "HOLD"))
                final_confidence = ai_result.get("confidence", ai_result.get("final_confidence", 0.0))

                chain = ai_result.get("reasoning_chain", {})
                if isinstance(chain, dict):
                    groq_reasoning = chain.get("step6_final_decision_rationale", str(chain)[:300])
                else:
                    groq_reasoning = str(chain)[:300]

            except Exception as e:
                from loguru import logger
                logger.warning(f"⚠️ AI Layer 2 error ({ai_provider}): {e}")
                final_signal = l1_signal
                final_confidence = l1_confidence

        entry_price = float(df.iloc[-1]["close"])

        return {
            "action": final_signal,
            "confidence": round(final_confidence, 3),
            "entry_price": round(entry_price, 2),
            "groq_used": groq_used,
            "ai_provider": ai_provider if groq_used else "none",
            "l1_signal": l1_signal,
            "l1_confidence": round(l1_confidence, 3),
            "reasoning": groq_reasoning if groq_used else l1_reasoning[:200],
            "groq_reasoning": groq_reasoning,
            "hurst": round(hurst_value, 4),
        }

    @staticmethod
    async def analyze_async(
        engine,
        df,
        symbol: str = "R_100",
        use_groq: bool = False,
        ai_provider: str = "groq",
        hurst_min: float = 0.6,
        hurst_max: float = 0.7,
        slope_min: float = 0.0,
        slope_lookback: int = 20,
    ) -> Dict[str, Any]:
        """Async version of analyze() — for use in async contexts (bot_step, replay_bot)."""
        # ===== SLOPE FILTER =====
        if slope_min > 0:
            from app.analysis.indicators import TechnicalIndicators
            slope_info = TechnicalIndicators.compute_ema_slope(df, lookback=slope_lookback)
            if slope_info['slope_abs'] < slope_min:
                entry_price = float(df.iloc[-1]['close'])
                return {
                    'action': 'HOLD', 'confidence': 0.0, 'entry_price': round(entry_price, 2),
                    'groq_used': False, 'ai_provider': 'none', 'l1_signal': 'HOLD',
                    'l1_confidence': 0.0,
                    'reasoning': f"Mercado lateral (pendiente={slope_info['slope']:.4f} < {slope_min})",
                    'groq_reasoning': '', 'hurst': 0.5,
                    'rsi_14': 0, 'ema_9': 0, 'ema_21': 0, 'macd_histogram': 0, 'bb_width': 0,
                }

        # ===== Window: last 250 candles =====
        start_idx = max(0, len(df) - 250)
        window = df.iloc[start_idx:]

        # ===== LAYER 1: Statistical Analysis =====
        signal = engine.safe_analyze(window, symbol, hurst_min=hurst_min, hurst_max=hurst_max)

        l1_signal = signal.get("final_signal", "HOLD")
        l1_confidence = signal.get("final_confidence", 0.0)
        l1_reasoning = signal.get("reasoning", "")
        hurst_value = signal.get("hurst_signal", {}).get("hurst", 0.5)

        # ===== LAYER 2: AI Meta-Analysis =====
        groq_used = False
        final_signal = l1_signal
        final_confidence = l1_confidence
        groq_reasoning = ""

        should_call_ai = use_groq and l1_signal in ["CALL", "PUT"]

        if should_call_ai:
            try:
                layer2 = TradingCore._get_layer2(ai_provider)

                last_5 = df.iloc[-5:]["close"].tolist() if len(df) >= 5 else df["close"].tolist()
                rising = sum(1 for i in range(1, len(last_5)) if last_5[i] > last_5[i - 1])
                falling = sum(1 for i in range(1, len(last_5)) if last_5[i] < last_5[i - 1])

                price_direction = "RISING" if rising >= 3 else ("FALLING" if falling >= 3 else "MIXED")
                direction_aligned = (l1_signal == "CALL" and price_direction == "RISING") or (l1_signal == "PUT" and price_direction == "FALLING")
                rsi_val = float(df.iloc[-1].get("rsi_14", 50))
                rsi_extreme = (l1_signal == "CALL" and rsi_val > 70) or (l1_signal == "PUT" and rsi_val < 35)

                signal["price_direction"] = price_direction
                signal["direction_aligned"] = direction_aligned
                signal["rsi_extreme"] = rsi_extreme
                signal["last_5_closes"] = [round(p, 2) for p in last_5]

                class SC:
                    def __init__(self, r):
                        self.open = float(r["open"])
                        self.high = float(r["high"])
                        self.low = float(r["low"])
                        self.close = float(r["close"])

                candle_start = max(0, len(df) - 25)
                candles_for_ai = [SC(df.iloc[j]) for j in range(candle_start, len(df))]

                ai_result = await layer2.analyze(layer1_signal=signal, candles=candles_for_ai, db=None)

                groq_used = True
                final_signal = ai_result.get("decision", ai_result.get("final_signal", "HOLD"))
                final_confidence = ai_result.get("confidence", ai_result.get("final_confidence", 0.0))
                chain = ai_result.get("reasoning_chain", {})
                groq_reasoning = chain.get("step6_final_decision_rationale", str(chain)[:300]) if isinstance(chain, dict) else str(chain)[:300]

            except Exception as e:
                from loguru import logger
                logger.warning(f"⚠️ AI Layer 2 error ({ai_provider}): {e}")
                final_signal = l1_signal
                final_confidence = l1_confidence

        entry_price = float(df.iloc[-1]["close"])

        # Extract indicators from engine signal, fallback to OHLC computation
        ind = signal.get("indicators", {})
        close = window["close"]

        # RSI 14
        rsi_val = float(ind.get("rsi_14", 0) or 0)
        if not rsi_val:
            try:
                delta = close.diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain.iloc[-1] / (loss.iloc[-1] + 1e-10)
                rsi_val = 100 - (100 / (1 + rs))
            except Exception:
                rsi_val = 0

        # EMA 9
        ema_9_val = float(ind.get("ema_9", 0) or 0)
        if not ema_9_val:
            try:
                ema_9_val = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
            except Exception:
                ema_9_val = 0

        # EMA 21
        ema_21_val = float(ind.get("ema_21", 0) or 0)
        if not ema_21_val:
            try:
                ema_21_val = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
            except Exception:
                ema_21_val = 0

        # MACD histogram
        macd_val = float(ind.get("macd_histogram", 0) or 0)
        if not macd_val:
            try:
                ema12 = close.ewm(span=12, adjust=False).mean()
                ema26 = close.ewm(span=26, adjust=False).mean()
                macd_line = ema12 - ema26
                signal_line = macd_line.ewm(span=9, adjust=False).mean()
                macd_val = float((macd_line - signal_line).iloc[-1])
            except Exception:
                macd_val = 0

        # Bollinger Band width
        bb_width = float(ind.get("bb_width", 0) or 0)
        if not bb_width:
            try:
                sma20 = close.rolling(20).mean().iloc[-1]
                std20 = close.rolling(20).std().iloc[-1]
                bb_upper = sma20 + 2 * std20
                bb_lower = sma20 - 2 * std20
                bb_width = (bb_upper - bb_lower) / (sma20 + 1e-10)
            except Exception:
                bb_width = 0

        return {
            "action": final_signal,
            "confidence": round(final_confidence, 3),
            "entry_price": round(entry_price, 2),
            "groq_used": groq_used,
            "ai_provider": ai_provider if groq_used else "none",
            "l1_signal": l1_signal,
            "l1_confidence": round(l1_confidence, 3),
            "reasoning": groq_reasoning if groq_used else l1_reasoning[:200],
            "groq_reasoning": groq_reasoning,
            "hurst": round(hurst_value, 4),
            "rsi_14": round(rsi_val, 2),
            "ema_9": round(ema_9_val, 2),
            "ema_21": round(ema_21_val, 2),
            "macd_histogram": round(macd_val, 4),
            "bb_width": round(bb_width, 5),
        }

    @staticmethod
    def _get_layer2(ai_provider: str):
        """Instantiate the appropriate AI Layer 2 engine."""
        if ai_provider == "openai":
            from app.services.openai_client import get_openai_engine
            from app.analysis.layer2_groq import Layer2GroqEngine
            from app.prompts.trading_system_prompt import get_system_prompt
            from app.analysis.meta_confidence import get_meta_confidence

            layer2 = Layer2GroqEngine.__new__(Layer2GroqEngine)
            layer2.groq = get_openai_engine()
            layer2.system_prompt = get_system_prompt()
            layer2.meta_confidence = get_meta_confidence()
        elif ai_provider == "claude":
            from app.services.claude_client import get_claude_engine
            from app.analysis.layer2_groq import Layer2GroqEngine
            from app.prompts.trading_system_prompt import get_system_prompt
            from app.analysis.meta_confidence import get_meta_confidence

            layer2 = Layer2GroqEngine.__new__(Layer2GroqEngine)
            layer2.groq = get_claude_engine()
            layer2.system_prompt = get_system_prompt()
            layer2.meta_confidence = get_meta_confidence()
        elif ai_provider == "gemini":
            from app.services.gemini_client import get_gemini_engine
            from app.analysis.layer2_groq import Layer2GroqEngine
            from app.prompts.trading_system_prompt import get_system_prompt
            from app.analysis.meta_confidence import get_meta_confidence

            layer2 = Layer2GroqEngine.__new__(Layer2GroqEngine)
            layer2.groq = get_gemini_engine()
            layer2.system_prompt = get_system_prompt()
            layer2.meta_confidence = get_meta_confidence()
        else:
            from app.analysis.layer2_groq import get_layer2_engine
            layer2 = get_layer2_engine()

        return layer2
