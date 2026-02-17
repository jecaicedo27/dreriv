"""
Accumulator Analysis Engine for Boom 1000 Index

Specialized analysis for Accumulator (ACCU) contracts:
- Spike detection (Boom 1000 has upward spikes every ~1000 ticks)
- Volatility scoring to determine if it's safe to enter
- Growth rate recommendation based on current conditions
- Entry signal generation

Key insight: Boom 1000 drops gradually and spikes up.
Accumulators profit when price stays WITHIN barriers.
→ We want to enter during calm/gradual-drop periods (low volatility)
→ We want to AVOID entering right before a spike (high risk of barrier breach)
→ After a spike, there's usually a calm period → good entry
"""
import numpy as np
from collections import deque
from typing import Dict, Any, Optional, Tuple
from loguru import logger
from datetime import datetime

from app.core.accu_config import AccuConfig


class AccuAnalysisEngine:
    """
    Analysis engine for Accumulator contracts on Boom 1000.
    
    Processes tick-by-tick data to generate entry signals.
    """

    def __init__(self, config: AccuConfig = None):
        self.config = config or AccuConfig()

        # Tick history buffer
        self.ticks: deque = deque(maxlen=2000)
        self.tick_changes: deque = deque(maxlen=2000)  # % changes between ticks

        # Spike tracking
        self.last_spike_tick_index = -1000  # Long ago by default
        self.total_ticks = 0
        self.spikes_detected = 0

        # Statistics
        self.rolling_mean = 0.0
        self.rolling_std = 0.0

        # Last analysis result (for dashboard)
        self.last_signal = 'NOT_READY'
        self.last_reasoning = ''
        self.last_volatility_score = 0.0

    def process_tick(self, price: float) -> Dict[str, Any]:
        """
        Process a new tick and return analysis.
        
        Returns dict with:
            - ready: bool (enough data to analyze)
            - signal: 'ENTER' | 'WAIT' | 'NOT_READY'
            - growth_rate: recommended growth rate
            - reasoning: str
            - metrics: dict with analysis details
        """
        self.total_ticks += 1
        self.ticks.append(price)

        # Calculate tick-to-tick change
        if len(self.ticks) >= 2:
            prev = self.ticks[-2]
            if prev != 0:
                pct_change = (price - prev) / prev * 100
                self.tick_changes.append(pct_change)

        # Not enough data yet
        if len(self.tick_changes) < self.config.MIN_TICKS_BEFORE_ENTRY:
            return {
                'ready': False,
                'signal': 'NOT_READY',
                'growth_rate': self.config.GROWTH_RATE,
                'reasoning': f'Collecting ticks: {len(self.tick_changes)}/{self.config.MIN_TICKS_BEFORE_ENTRY}',
                'metrics': {
                    'ticks_collected': len(self.tick_changes),
                    'ticks_needed': self.config.MIN_TICKS_BEFORE_ENTRY,
                    'current_price': price
                }
            }

        # Update rolling statistics
        changes_array = np.array(list(self.tick_changes))
        self.rolling_mean = np.mean(changes_array[-self.config.VOLATILITY_WINDOW:])
        self.rolling_std = np.std(changes_array[-self.config.VOLATILITY_WINDOW:])

        # Detect spike in this tick
        is_spike = self._detect_spike(changes_array)

        # Calculate volatility score
        vol_score = self._calculate_volatility_score(changes_array)

        # Determine ticks since last spike
        ticks_since_spike = self.total_ticks - self.last_spike_tick_index

        # Generate entry signal
        signal, reasoning = self._generate_signal(
            vol_score=vol_score,
            ticks_since_spike=ticks_since_spike,
            is_spike=is_spike,
            current_price=price
        )

        # Recommend growth rate
        growth_rate = self._recommend_growth_rate(vol_score)

        # Cache last result for get_stats
        self.last_signal = signal
        self.last_reasoning = reasoning
        self.last_volatility_score = round(vol_score, 4)

        return {
            'ready': True,
            'signal': signal,
            'growth_rate': growth_rate,
            'reasoning': reasoning,
            'metrics': {
                'current_price': price,
                'volatility_score': round(vol_score, 4),
                'rolling_std': round(self.rolling_std, 6),
                'rolling_mean': round(self.rolling_mean, 6),
                'ticks_since_spike': ticks_since_spike,
                'total_spikes': self.spikes_detected,
                'total_ticks': self.total_ticks,
                'is_spike': is_spike
            }
        }

    def _detect_spike(self, changes: np.ndarray) -> bool:
        """
        Detect if the latest tick is a spike (boom).
        Boom 1000: upward spikes > 4σ from mean.
        """
        if len(changes) < 2:
            return False

        latest_change = changes[-1]

        # Use longer-term stats for spike detection
        lookback = min(self.config.SPIKE_LOOKBACK, len(changes))
        long_mean = np.mean(changes[-lookback:])
        long_std = np.std(changes[-lookback:])

        if long_std == 0:
            return False

        z_score = (latest_change - long_mean) / long_std

        # Boom 1000 spikes are UPWARD — large positive z-score
        if z_score > self.config.SPIKE_THRESHOLD_SIGMA:
            self.last_spike_tick_index = self.total_ticks
            self.spikes_detected += 1
            logger.warning(
                f"🔥 SPIKE DETECTED! Change: {latest_change:.4f}%, "
                f"Z-score: {z_score:.2f}, Total spikes: {self.spikes_detected}"
            )
            return True

        return False

    def _calculate_volatility_score(self, changes: np.ndarray) -> float:
        """
        Calculate normalized volatility score.
        
        Score < 1.0 → below average volatility (good for entry)
        Score > 1.0 → above average volatility (risky)
        Score > 2.0 → very high volatility (don't enter)
        """
        window = min(self.config.VOLATILITY_WINDOW, len(changes))
        recent_vol = np.std(changes[-window:])

        # Long-term baseline volatility
        long_vol = np.std(changes)

        if long_vol == 0:
            return 1.0

        return recent_vol / long_vol

    def _generate_signal(
        self,
        vol_score: float,
        ticks_since_spike: int,
        is_spike: bool,
        current_price: float
    ) -> Tuple[str, str]:
        """
        Generate entry signal based on all factors.
        
        Returns (signal, reasoning)
        """
        reasons = []

        # Rule 1: Never enter during or immediately after a spike
        if is_spike:
            return ('WAIT', '🔥 Spike detectado en este tick — esperando estabilización')

        if ticks_since_spike < self.config.MIN_TICKS_SINCE_SPIKE:
            reasons.append(f'⏳ Solo {ticks_since_spike} ticks desde último spike (min: {self.config.MIN_TICKS_SINCE_SPIKE})')
            return ('WAIT', ' | '.join(reasons))

        # Rule 2: Volatility must be acceptable
        if vol_score > self.config.MAX_VOLATILITY_FOR_ENTRY:
            reasons.append(f'📈 Volatilidad alta ({vol_score:.2f}x) — riesgoso')
            return ('WAIT', ' | '.join(reasons))

        # All conditions met → ENTER
        reasons.append(f'✅ Vol={vol_score:.2f}x (normal)')
        reasons.append(f'✅ {ticks_since_spike} ticks desde spike')

        if vol_score < 0.7:
            reasons.append('🎯 Volatilidad MUY baja — condiciones ideales')
        elif vol_score < 1.0:
            reasons.append('👍 Volatilidad por debajo del promedio')

        return ('ENTER', ' | '.join(reasons))

    def _recommend_growth_rate(self, vol_score: float) -> float:
        """
        Recommend growth rate based on volatility.
        Lower volatility → higher growth rate (more aggressive, wider barriers still safe)
        Higher volatility → lower growth rate (conservative, narrower barriers)
        """
        if not self.config.GROWTH_RATE_ADAPTIVE:
            return self.config.GROWTH_RATE

        if vol_score < 0.7:
            return self.config.GROWTH_RATE_LOW_VOL   # 3%
        elif vol_score < 1.2:
            return self.config.GROWTH_RATE_NORMAL     # 2%
        else:
            return self.config.GROWTH_RATE_HIGH_VOL   # 1%

    def get_stats(self) -> Dict[str, Any]:
        """Return current engine statistics"""
        return {
            'total_ticks': self.total_ticks,
            'spikes_detected': self.spikes_detected,
            'avg_ticks_per_spike': (self.total_ticks / self.spikes_detected) if self.spikes_detected > 0 else None,
            'rolling_mean': round(self.rolling_mean, 6),
            'rolling_std': round(self.rolling_std, 6),
            'buffer_size': len(self.ticks),
            'last_price': self.ticks[-1] if self.ticks else None,
            # Dashboard fields
            'volatility_score': self.last_volatility_score,
            'signal': self.last_signal,
            'reasoning': self.last_reasoning,
        }

    def reset(self):
        """Reset all state"""
        self.ticks.clear()
        self.tick_changes.clear()
        self.last_spike_tick_index = -1000
        self.total_ticks = 0
        self.spikes_detected = 0
        self.rolling_mean = 0.0
        self.rolling_std = 0.0
        logger.info("🔄 AccuAnalysisEngine reset")
