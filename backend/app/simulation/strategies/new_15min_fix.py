"""
NEW Strategy (With Fix) - Dynamic 15 Min for TRENDING
Uses the CORRECTED logic where TRENDING regime gets 900s duration
"""

import pandas as pd
from typing import Dict, Any
from loguru import logger

from app.simulation.strategy import Strategy


class New15MinStrategy(Strategy):
    """
    FIXED VERSION: Uses 900s (15 min) for TRENDING, 300s (5 min) for MEAN_REVERSION
    This is the CURRENT production behavior after the bug fix
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.name = "New15Min_Fixed"
        
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
        Analyze using Layer 1 and RESPECT its duration calculation (fix)
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
            
            # FIX: Use the duration from Layer1 (respects regime)
            layer1_duration = signal.get('duration', 300)  
            
            return {
                'signal': final_decision,
                'confidence': final_confidence,
                'stake': self.default_stake,
                'duration': layer1_duration,  # RESPECTS LAYER1 DECISION
                'reasoning': f"{reasoning} | DURATION: {layer1_duration}s (FIXED)"
            }
            
        except Exception as e:
            logger.error(f"Strategy analysis error: {e}")
            return {'signal': 'HOLD', 'confidence': 0.0}
