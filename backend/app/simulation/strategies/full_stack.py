
from typing import Dict, Any
from loguru import logger
import pandas as pd

from app.simulation.strategies.current_bot import CurrentBotStrategy
from app.analysis.layer2_groq import Layer2GroqEngine
from app.services.groq_client import GroqTradingEngine
from app.prompts.trading_system_prompt import get_system_prompt
from app.analysis.meta_confidence import get_meta_confidence

class SimulationLayer2Engine(Layer2GroqEngine):
    """
    Custom Layer 2 engine for simulation that allows specific API Key
    Overrides the singleton pattern to use a dedicated client
    """
    def __init__(self, api_key: str):
        # Do NOT call super().__init__() because it uses get_groq_engine() singleton
        # Instead, manually initialize with custom client
        
        self.groq = GroqTradingEngine(api_key=api_key)
        self.system_prompt = get_system_prompt()
        self.meta_confidence = get_meta_confidence()
        
        logger.info("🧠 Simulation Layer 2 Engine initialized with CUSTOM API KEY")

class FullStackStrategy(CurrentBotStrategy):
    """
    Strategy that runs the full stack:
    1. Layer 1 (Statistical Models) - from CurrentBotStrategy
    2. Layer 2 (Groq AI) - with custom API Key
    """
    
    def __init__(self, api_key: str, config: dict = None):
        super().__init__(config)
        self.name = "FullStack_Groq_Sim"
        
        # Initialize custom Layer 2
        self.l2_engine = SimulationLayer2Engine(api_key)
        
    async def analyze(
        self,
        current_candle: pd.Series,
        history: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Run full analysis pipeline
        """
        # 1. Run Layer 1 (from parent class)
        # We need to call the signal_engine directly because super().analyze() 
        # returns the final decision dict, but L2 needs the detailed L1 signal structure.
        
        # Copied logic from CurrentBotStrategy to get the raw signal
        if len(history) < 50:
            return {'signal': 'HOLD', 'confidence': 0.0}
            
        window = history.iloc[-250:].copy() if len(history) > 250 else history.copy()
        
        # Ensure float types
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 
                       'rsi_14', 'ema_9', 'ema_21', 'ema_50', 
                       'macd', 'macd_signal', 'macd_histogram',
                       'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
                       'atr_14', 'returns', 'momentum_5', 'volatility_realized']
        
        for col in numeric_cols:
            if col in window.columns:
                window[col] = window[col].astype(float)
        
        try:
            # 1. Layer 1 Analysis
            l1_result = self.signal_engine.analyze(window, 'R_100')
            
            l1_decision = l1_result.get('final_signal', 'HOLD')
            l1_conf = l1_result.get('final_confidence', 0.0)
            
            # 2. Layer 2 Analysis (Groq)
            # Only call Groq if L1 has SOME viability or if we want to test Groq's ability to find trades in noise?
            # Usually we filter by L1 confidence to save tokens.
            # But user wants "process with our bot".
            # The real bot triggers L2 if L1 confidence > threshold OR if specific regime.
            
            trigger_l2 = False
            
            # Logic from main bot.py should be replicated here?
            # In bot.py, typically: if l1_conf > 0.4 or "interesting"
            
            if l1_decision != 'HOLD' or l1_conf > 0.40:
                trigger_l2 = True
            
            # Also trigger if Hurst indicates clear regime even if signal is weak?
            hurst = l1_result.get('hurst_signal', {}).get('hurst', 0.5)
            if abs(hurst - 0.5) > 0.15: # Strong trending or mean reversion
                trigger_l2 = True
                
            if trigger_l2:
                # Convert history to list for context formatting if needed
                # Layer2 engine takes list of objects usually? 
                # _format_market_context takes "candles" list.
                
                # Convert tail of dataframe to list of objects (mocking DB objects)
                class MockCandle:
                    def __init__(self, row):
                        self.open = row['open']
                        self.close = row['close']
                        self.high = row['high']
                        self.low = row['low']
                
                recent_candles = [MockCandle(r) for _, r in window.iloc[-30:].iterrows()]
                
                l2_result = await self.l2_engine.analyze(
                    layer1_signal=l1_result,
                    candles=recent_candles,
                    db=None # No DB logging for simulation to avoid polluting logs? OR yes?
                    # User said "process with our bot", maybe implies logging decisions?
                    # But engine.py saves trades. layer2 saves decision logs.
                    # We can pass None to avoid writing to groq_decisions_log table if we want to keep it clean.
                )
                
                return {
                    'signal': l2_result['decision'],
                    'confidence': l2_result['confidence'],
                    'stake': self.default_stake * l2_result.get('suggested_stake_multiplier', 1.0),
                    'duration': l2_result.get('duration', 300),
                    'reasoning': l2_result.get('reasoning', '')
                }
            
            else:
                return {
                    'signal': l1_decision,
                    'confidence': l1_conf,
                    'stake': self.default_stake,
                    'reasoning': l1_result.get('reasoning', '')
                }
                
        except Exception as e:
            logger.error(f"FullStack Strategy error: {e}")
            import traceback
            traceback.print_exc()
            return {'signal': 'HOLD', 'confidence': 0.0}
