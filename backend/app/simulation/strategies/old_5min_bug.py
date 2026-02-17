"""
OLD Strategy (Bug Replica) - Fixed 5 Min Duration
Replica the bug where all trades used 300s duration regardless of regime
"""

import pandas as pd
from typing import Dict, Any
from loguru import logger

from app.simulation.strategy import Strategy


class Old5MinStrategy(Strategy):
    """
    BUG REPLICA: Always uses 300s (5 min) duration
    This was the behavior BEFORE the fix
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.name = "Old5Min_BugReplica"
        
        # Config defaults
        self.min_confidence = config.get('min_confidence', 0.60) if config else 0.60
        self.default_stake = config.get('default_stake', 60.0) if config else 60.0
        
        # Initialize Layer 1 Engine
        from app.analysis.layer1_engine import Layer1SignalEngine
        self.signal_engine = Layer1SignalEngine()
    
    async def analyze(
        self,
        current_candle: pd.Series,
        history: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Analyze using Layer 1 but FORCE duration to 300s (bug behavior)
        """
        
        # Need enough history for indicators
        if len(history) < 50:
            return {'signal': 'HOLD', 'confidence': 0.0}
        
        # Get last 250 candles (or available history)
        window = history.iloc[-250:].copy() if len(history) > 250 else history.copy()
        
        # Convert Decimal to float for numpy compatibility
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 
                       'rsi_14', 'ema_9', 'ema_21', 'ema_50', 
                       'macd', 'macd_signal', 'macd_histogram',
                       'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
                       'atr_14', 'returns', 'momentum_5', 'volatility_realized']
        
        for col in numeric_cols:
            if col in window.columns:
                window[col] = window[col].astype(float)
        
        try:
            # Run Layer 1 analysis
            signal = self.signal_engine.analyze(window, 'R_100')
            
            final_decision = signal.get('final_signal', 'HOLD')
            final_confidence = signal.get('final_confidence', 0.0)
            reasoning = signal.get('reasoning', '')
            
            # Filter by confidence
            if final_confidence < self.min_confidence:
                return {'signal': 'HOLD', 'confidence': final_confidence}
            
            # BUG: Always 300s regardless of what Layer1 said
            forced_duration = 300  
            
            return {
                'signal': final_decision,
                'confidence': final_confidence,
                'stake': self.default_stake,
                'duration': forced_duration,  # HARDCODED BUG
                'reasoning': f"{reasoning} | DURATION: {forced_duration}s (BUG)"
            }
            
        except Exception as e:
            logger.error(f"Strategy analysis error: {e}")
            return {'signal': 'HOLD', 'confidence': 0.0}
