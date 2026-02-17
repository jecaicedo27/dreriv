"""
Base Strategy Interface for Simulation
All custom strategies must implement this interface
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any
import pandas as pd


class Strategy(ABC):
    """
    Base class for all backtesting strategies
    """
    
    def __init__(self, config: dict = None):
        """
        Initialize strategy with config
        
        Args:
            config: Strategy-specific configuration
        """
        self.config = config or {}
        self.name = self.__class__.__name__
    
    @abstractmethod
    async def analyze(
        self,
        current_candle: pd.Series,
        history: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Analyze current market state and return trading decision
        
        Args:
            current_candle: Current candle data (Series with OHLC + indicators)
            history: Historical candles up to current (DataFrame)
        
        Returns:
            {
                'signal': 'CALL' | 'PUT' | 'HOLD',
                'confidence': float (0.0-1.0),
                'stake': float,
                'reasoning': str (optional)
            }
        """
        pass
    
    def get_name(self) -> str:
        """Get strategy name"""
        return self.name
    
    def get_config(self) -> dict:
        """Get strategy configuration"""
        return self.config
