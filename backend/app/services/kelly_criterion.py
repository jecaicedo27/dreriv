"""
Kelly Criterion Position Sizing
Optimal bet sizing based on edge and win rate

Based on skill: trading-risk-management
"""
import numpy as np
from typing import Dict, Any
from loguru import logger

from app.core.config import get_settings

settings = get_settings()


class KellyCriterion:
    """
    Kelly Criterion for optimal position sizing
    
    Full Kelly formula:
    f* = (p * b - q) / b
    
    Where:
    - p = probability of winning
    - q = probability of losing (1 - p)
    - b = odds received (payout / stake ratio)
    - f* = fraction of bankroll to bet
    
    For binary options (fixed payout):
    - If payout = 1.95x stake
    - b = 0.95 (net profit ratio)
    """
    
    @staticmethod
    def calculate_kelly_fraction(
        win_probability: float,
        payout_ratio: float = 0.95,
        kelly_fraction: float = None
    ) -> float:
        """
        Calculate Kelly fraction for position sizing
        
        Args:
            win_probability: Probability of winning (0-1)
            payout_ratio: Net profit ratio (typically 0.90-0.95 for Deriv)
            kelly_fraction: Multiplier to Kelly (default from settings)
            
        Returns:
            Fraction of bankroll to risk (0-1)
        """
        if kelly_fraction is None:
            kelly_fraction = settings.KELLY_FRACTION
        
        # Clamp win probability to valid range
        p = max(0.01, min(0.99, win_probability))
        q = 1 - p
        b = payout_ratio
        
        # Full Kelly formula
        kelly = (p * b - q) / b
        
        # Apply fractional Kelly (typically 0.25 = quarter Kelly)
        fractional_kelly = kelly * kelly_fraction
        
        # Clamp to 0-20% of bankroll (safety limit)
        fractional_kelly = max(0.0, min(0.20, fractional_kelly))
        
        logger.debug(f"Kelly: p={p:.3f}, b={b:.2f} → f*={kelly:.4f} → fractional={fractional_kelly:.4f}")
        
        return fractional_kelly
    
    @staticmethod
    def calculate_stake(
        balance: float,
        win_probability: float,
        payout_ratio: float = 0.95,
        min_stake: float = 0.35,
        max_stake: float = 100.0
    ) -> float:
        """
        Calculate actual stake amount in currency
        
        Args:
            balance: Current account balance
            win_probability: Probability of winning
            payout_ratio: Net profit ratio
            min_stake: Minimum allowed stake
            max_stake: Maximum allowed stake
            
        Returns:
            Stake amount in currency
        """
        # Calculate Kelly fraction
        kelly_frac = KellyCriterion.calculate_kelly_fraction(win_probability, payout_ratio)
        
        # Calculate stake
        stake = balance * kelly_frac
        
        # Apply min/max limits
        stake = max(min_stake, min(max_stake, stake))
        
        # Round to 2 decimals
        stake = round(stake, 2)
        
        logger.info(f"💰 Kelly stake: {stake:.2f} (balance={balance:.2f}, p={win_probability:.3f})")
        
        return stake
    
    @staticmethod
    def get_recommended_stake(
        balance: float,
        confidence: float,
        stake_multiplier: float = 1.0,
        drawdown_multiplier: float = 1.0
    ) -> Dict[str, Any]:
        """
        Get recommended stake with all adjustments
        
        Args:
            balance: Current balance
            confidence: Model confidence (0-1)
            stake_multiplier: GARCH volatility adjustment
            drawdown_multiplier: Drawdown recovery adjustment
            
        Returns:
            Dict with stake and metadata
        """
        # Base Kelly stake
        base_stake = KellyCriterion.calculate_stake(balance, confidence)
        
        # Apply GARCH multiplier
        garch_adjusted = base_stake * stake_multiplier
        
        # Apply drawdown recovery multiplier
        final_stake = garch_adjusted * drawdown_multiplier
        
        # Round to 2 decimals
        final_stake = round(final_stake, 2)
        
        # Ensure minimum
        final_stake = max(0.35, final_stake)
        
        return {
            'stake': final_stake,
            'base_kelly_stake': round(base_stake, 2),
            'garch_multiplier': round(stake_multiplier, 2),
            'drawdown_multiplier': round(drawdown_multiplier, 2),
            'confidence': round(confidence, 4)
        }
