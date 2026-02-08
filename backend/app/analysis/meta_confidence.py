"""
Meta-Confidence Tracker for Groq AI
Monitors Groq's prediction accuracy over rolling windows
Adjusts trust multiplier based on performance
"""

from typing import List, Tuple
from collections import deque
from loguru import logger


class GroqMetaConfidence:
    """
    Track how well Groq's predictions match reality
    
    Maintains rolling window of (predicted_confidence, actual_outcome)
    Calculates:
    - Accuracy: % of correct predictions
    - Calibration error: How well confidence matches reality
    - Trust multiplier: Factor to adjust Groq's confidence
    """
    
    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self.recent_decisions: deque = deque(maxlen=window_size)
        # Store (confidence, was_correct, decision_type)
    
    def record_outcome(
        self,
        predicted_confidence: float,
        was_correct: bool,
        decision: str = "UNKNOWN"
    ):
        """
        Record the outcome of a trade
        
        Args:
            predicted_confidence: What Groq said (0.0-1.0)
            was_correct: Did the trade win?
            decision: CALL or PUT (for analysis)
        """
        self.recent_decisions.append((
            predicted_confidence,
            was_correct,
            decision
        ))
        
        logger.info(
            f"📊 Meta-confidence recorded: "
            f"predicted={predicted_confidence:.2f}, "
            f"actual={'WIN' if was_correct else 'LOSS'}, "
            f"window={len(self.recent_decisions)}/{self.window_size}"
        )
    
    @property
    def accuracy(self) -> float:
        """Overall accuracy (% wins) in rolling window"""
        if not self.recent_decisions:
            return 0.5  # Neutral prior
        
        correct = sum(1 for _, won, _ in self.recent_decisions if won)
        return correct / len(self.recent_decisions)
    
    @property
    def calibration_error(self) -> float:
        """
        How well confidence matches actual accuracy
        
        Perfect calibration = 0.0
        Overconfident = positive value
        Underconfident = negative value
        """
        if not self.recent_decisions:
            return 0.0
        
        avg_confidence = sum(
            conf for conf, _, _ in self.recent_decisions
        ) / len(self.recent_decisions)
        
        return avg_confidence - self.accuracy
    
    @property
    def trust_multiplier(self) -> float:
        """
        Multiply Groq's confidence by this value
        
        Based on accuracy:
        - ≥65%: 1.0 (full trust)
        - 55-64%: 0.85 (slight reduction)
        - 45-54%: 0.70 (significant reduction)
        - <45%: 0.50 (halve influence - worse than random)
        """
        acc = self.accuracy
        
        if acc >= 0.65:
            return 1.0
        elif acc >= 0.55:
            return 0.85
        elif acc >= 0.45:
            return 0.70
        else:
            return 0.50
    
    @property
    def sample_size(self) -> int:
        """Number of trades in current window"""
        return len(self.recent_decisions)
    
    @property
    def is_statistically_significant(self) -> bool:
        """Require at least 10 trades for reliable stats"""
        return len(self.recent_decisions) >= 10
    
    def get_stats(self) -> dict:
        """Get all stats as dict for logging/dashboard"""
        return {
            "accuracy": round(self.accuracy, 4),
            "calibration_error": round(self.calibration_error, 4),
            "trust_multiplier": round(self.trust_multiplier, 4),
            "sample_size": self.sample_size,
            "is_significant": self.is_statistically_significant
        }
    
    def reset(self):
        """Clear all history (use when strategy changes)"""
        self.recent_decisions.clear()
        logger.warning("🔄 Meta-confidence tracker reset")


# Singleton instance
_meta_confidence = None

def get_meta_confidence() -> GroqMetaConfidence:
    """Get or create meta-confidence tracker singleton"""
    global _meta_confidence
    if _meta_confidence is None:
        _meta_confidence = GroqMetaConfidence(window_size=20)
    return _meta_confidence
