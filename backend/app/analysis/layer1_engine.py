"""
Layer 1 Analysis Engine
Aggregates all statistical models to generate trading signals

This is the core decision engine for MVP (without pgvector and Groq)
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger

from app.analysis.indicators import TechnicalIndicators
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from app.analysis.garch import GARCHModel
from app.analysis.hurst import HurstExponent


class Layer1SignalEngine:
    """
    Layer 1: Statistical Models + Technical Indicators
    
    Combines:
    - Ornstein-Uhlenbeck (mean reversion)
    - GARCH (volatility regime)
    - Hurst exponent (trending vs mean-reverting)
    - Technical indicators (confirmation)
    """
    
    def __init__(self):
        self.ou_model = OrnsteinUhlenbeckModel(window=200)
        self.garch_model = GARCHModel(window=100)
        
    def analyze(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        """
        Perform complete Layer 1 analysis
        
        Args:
            df: DataFrame with OHLC data
            symbol: Trading symbol (e.g., 'R_100')
            
        Returns:
            Dictionary with signals and analysis
        """
        if df.empty or len(df) < 50:
            logger.warning(f"Not enough data for analysis: {len(df)} candles")
            return self._empty_signal()
        
        try:
            # 1. Calculate technical indicators
            df = TechnicalIndicators.calculate_all(df)
            
            # 2. Get latest values
            latest = df.iloc[-1]
            current_price = latest['close']
            
            # 3. Ornstein-Uhlenbeck (Mean Reversion)
            self.ou_model.fit(df['close'])
            ou_signal = self.ou_model.get_signal(current_price, threshold=2.0)
            
            # 4. GARCH (Volatility)
            returns = df['returns'].dropna()
            if len(returns) > 50:
                self.garch_model.fit(returns)
                current_vol = latest.get('volatility_realized', 0)
                garch_signal = self.garch_model.get_signal(current_vol)
            else:
                garch_signal = {'signal': 'NEUTRAL', 'regime': 'UNKNOWN', 'stake_multiplier': 1.0}
            
            # 5. Hurst exponent
            hurst_signal = HurstExponent.get_signal(df['close'], window=200)
            
            # 6. Technical indicator confirmations
            indicators = TechnicalIndicators.get_latest_values(df)
            
            # 7. Aggregate signals
            final_signal = self._aggregate_signals(
                ou_signal=ou_signal,
                garch_signal=garch_signal,
                hurst_signal=hurst_signal,
                indicators=indicators,
                current_price=current_price
            )
            
            return {
                'symbol': symbol,
                'timestamp': pd.Timestamp.now().isoformat(),
                'current_price': float(current_price),
                
                # Layer 1 signals
                'ou_signal': ou_signal,
                'garch_signal': garch_signal,
                'hurst_signal': hurst_signal,
                'indicators': indicators,
                
                # Final aggregated signal
                'final_signal': final_signal['signal'],
                'final_confidence': final_signal['confidence'],
                'contract_type': final_signal['contract_type'],
                'suggested_stake_multiplier': final_signal['stake_multiplier'],
                'suggested_duration': final_signal['duration'],
                'reasoning': final_signal['reasoning']
            }
            
        except Exception as e:
            logger.error(f"❌ Layer 1 analysis error: {e}")
            return self._empty_signal()
    
    def _aggregate_signals(
        self,
        ou_signal: Dict,
        garch_signal: Dict,
        hurst_signal: Dict,
        indicators: Dict,
        current_price: float
    ) -> Dict[str, Any]:
        """
        Aggregate all signals into final trading decision
        
        Logic:
        1. Hurst must be favorable (H < 0.5 for mean reversion)
        2. O-U must show strong deviation (> 2 sigma)
        3. GARCH adjusts position size
        4. Technical indicators provide confirmation
        """
        
        # Default: HOLD
        signal = 'HOLD'
        confidence = 0.0
        contract_type = None
        stake_multiplier = 1.0
        reasoning = []
        
        # Check Hurst first (regime filter)
        if not hurst_signal.get('trade_recommended', False):
            reasoning.append(f"Hurst exponent {hurst_signal['hurst']:.3f} indicates {hurst_signal['regime']}")
            reasoning.append("Mean reversion NOT favorable - HOLD")
            
            return {
                'signal': 'HOLD',
                'confidence': 0.0,
                'contract_type': None,
                'stake_multiplier': 1.0,
                'duration': 300,
                'reasoning': ' | '.join(reasoning)
            }
        
        # Hurst is favorable (H < 0.5)
        reasoning.append(f"Hurst {hurst_signal['hurst']:.3f} - mean reversion regime OK")
        
        # Check O-U signal
        ou_sig = ou_signal.get('signal', 'HOLD')
        ou_conf = ou_signal.get('confidence', 0.0)
        
        if ou_sig in ['CALL', 'PUT']:
            signal = ou_sig
            confidence = ou_conf
            reasoning.append(ou_signal['reason'])
            
            # Map to Deriv contract types
            if ou_sig == 'CALL':
                contract_type = 'CALL'  # Rise
            else:
                contract_type = 'PUT'  # Fall
        else:
            reasoning.append("O-U deviation below threshold - HOLD")
            return {
                'signal': 'HOLD',
                'confidence': 0.0,
                'contract_type': None,
                'stake_multiplier': 1.0,
                'duration': 300,
                'reasoning': ' | '.join(reasoning)
            }
        
        # Apply GARCH volatility adjustment to stake
        garch_mult = garch_signal.get('stake_multiplier', 1.0)
        stake_multiplier = garch_mult
        reasoning.append(f"GARCH regime {garch_signal['regime']} → stake ×{garch_mult:.2f}")
        
        # Technical indicator confirmations
        rsi = indicators.get('rsi_14', 50)
        
        # RSI confirmation (optional boost to confidence)
        if contract_type == 'CALL' and rsi < 30:
            confidence = min(confidence * 1.1, 0.95)
            reasoning.append("RSI oversold - CALL confirmed")
        elif contract_type == 'PUT' and rsi > 70:
            confidence = min(confidence * 1.1, 0.95)
            reasoning.append("RSI overbought - PUT confirmed")
        
        # Duration suggestion from O-U half-life
        duration = ou_signal.get('half_life', 5) * 60  # Convert to seconds
        duration = max(60, min(duration, 900))  # Clamp 1-15 minutes
        
        return {
            'signal': signal,
            'confidence': round(confidence, 4),
            'contract_type': contract_type,
            'stake_multiplier': round(stake_multiplier, 2),
            'duration': int(duration),
            'reasoning': ' | '.join(reasoning)
        }
    
    def _empty_signal(self) -> Dict[str, Any]:
        """Return empty signal structure"""
        return {
            'symbol': '',
            'timestamp': pd.Timestamp.now().isoformat(),
            'current_price': 0.0,
            'ou_signal': {},
            'garch_signal': {},
            'hurst_signal': {},
            'indicators': {},
            'final_signal': 'HOLD',
            'final_confidence': 0.0,
            'contract_type': None,
            'suggested_stake_multiplier': 1.0,
            'suggested_duration': 300,
            'reasoning': 'Insufficient data for analysis'
        }
