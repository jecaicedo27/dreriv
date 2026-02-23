"""
Layer 1 Analysis Engine
Aggregates all statistical models to generate trading signals

This is the core decision engine for MVP (without pgvector and Groq).

All indicators are READ from pre-computed DataFrame columns (pipeline-computed).
O-U and GARCH models are core analysis logic, not indicator fallbacks.
Compliant with engine contract.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger

from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from app.analysis.garch import GARCHModel
from app.analysis.base_engine import BaseAnalysisEngine


class Layer1SignalEngine(BaseAnalysisEngine):
    """
    Layer 1: Statistical Models + Technical Indicators (Original v1)
    
    Combines:
    - Ornstein-Uhlenbeck (mean reversion)
    - GARCH (volatility regime)
    - Hurst exponent (trending vs mean-reverting)
    - Technical indicators (confirmation)
    """
    
    name = "original_v1"
    version = "1.0"
    description = "Original: Hurst + O-U + GARCH + EMA/RSI/MACD (3-vote)"
    
    def __init__(self):
        self.ou_model = OrnsteinUhlenbeckModel(window=200)
        self.garch_model = GARCHModel(window=100)
        # NOTE: No session state. analyze() is a PURE function.
        # Same input → same output, always. Cooldowns/limits are external.
        
    def analyze(self, df: pd.DataFrame, symbol: str = 'R_100', hurst_min: float = 0.6, hurst_max: float = 0.7) -> Dict[str, Any]:
        """
        Perform complete Layer 1 analysis
        
        Args:
            df: DataFrame with OHLC data + pre-computed indicators
            symbol: Trading symbol (e.g., 'R_100')
            
        Returns:
            Dictionary with signals and analysis
        """
        if df.empty or len(df) < 50:
            logger.warning(f"Not enough data for analysis: {len(df)} candles")
            return self._empty_signal()
        
        try:
            latest = df.iloc[-1]
            current_price = float(latest['close'])
            
            # ===== Read ALL indicators from pre-computed DataFrame =====
            indicators = {
                'ema_9': float(latest.get('ema_9', 0) or 0),
                'ema_21': float(latest.get('ema_21', 0) or 0),
                'ema_50': float(latest.get('ema_50', 0) or 0),
                'rsi_14': float(latest.get('rsi_14', 50) or 50),
                'atr_14': float(latest.get('atr_14', 0) or 0),
                'bollinger_upper': float(latest.get('bollinger_upper', 0) or 0),
                'bollinger_middle': float(latest.get('bollinger_middle', 0) or 0),
                'bollinger_lower': float(latest.get('bollinger_lower', 0) or 0),
                'macd': float(latest.get('macd', 0) or 0),
                'macd_signal': float(latest.get('macd_signal', 0) or 0),
                'macd_histogram': float(latest.get('macd_histogram', 0) or 0),
                'returns': float(latest.get('returns', 0) or 0),
                'momentum_5': float(latest.get('momentum_5', 0) or 0),
                'volatility_realized': float(latest.get('volatility_realized', 0) or 0),
                'price_position': float(latest.get('price_position', 0) or 0),
            }
            
            # EMA crossover metrics from DataFrame
            indicators['ema_cross_age'] = int(latest.get('ema_cross_age', 0) or 0)
            indicators['ema_diverging'] = bool(int(latest.get('ema_diverging', 0) or 0))
            indicators['ema_separation_rate'] = float(latest.get('ema_gap_rate', 0) or 0)
            indicators['ema_cross_direction'] = 'BULLISH' if indicators['ema_21'] > indicators['ema_50'] else 'BEARISH'
            
            # ===== Hurst from pre-computed columns =====
            hurst_val = float(latest.get('hurst_exponent', 0) or 0)
            hurst_fast_val = float(latest.get('hurst_fast', 0) or 0)
            regime_str = str(latest.get('regime', 'RANDOM_WALK') or 'RANDOM_WALK')
            
            # Use best available Hurst value
            if hurst_val == 0 and hurst_fast_val == 0:
                hurst_val = 0.5  # Neutral default
            elif hurst_val == 0:
                hurst_val = hurst_fast_val
            
            hurst_signal = {
                'hurst': hurst_val,
                'hurst_fast': hurst_fast_val if hurst_fast_val > 0 else hurst_val,
                'hurst_slow': hurst_val,
                'regime': regime_str,
                'trade_recommended': regime_str in ('MEAN_REVERSION_CONFIRMED', 'MEAN_REVERTING', 'WEAK_MEAN_REVERTING'),
            }
            
            # ===== O-U from pre-computed column =====
            ou_dev = float(latest.get('ou_deviation', 0) or 0)
            if ou_dev != 0:
                # Reconstruct ou_signal from pre-computed deviation
                if abs(ou_dev) >= 2.0:
                    ou_dir = 'CALL' if ou_dev < -2.0 else 'PUT'
                    ou_conf = min(abs(ou_dev) / 4.0, 0.95)
                    ou_signal = {
                        'signal': ou_dir, 'confidence': ou_conf,
                        'deviation': ou_dev, 'half_life': 15.0,
                        'reason': f'O-U deviation {ou_dev:.2f}σ → {ou_dir}'
                    }
                else:
                    ou_signal = {'signal': 'HOLD', 'confidence': 0.0, 'deviation': ou_dev, 'half_life': 15.0, 'reason': f'O-U deviation {ou_dev:.2f}σ (below threshold)'}
            else:
                # O-U model analysis (core engine logic, not indicator computation)
                self.ou_model.fit(df['close'])
                ou_signal = self.ou_model.get_signal(current_price, threshold=2.0)
            
            # ===== GARCH from pre-computed column =====
            garch_vol = float(latest.get('garch_volatility_forecast', 0) or 0)
            if garch_vol > 0:
                current_vol = float(latest.get('volatility_realized', 0) or 0)
                if garch_vol > current_vol * 1.5:
                    garch_regime = 'HIGH_VOL'
                    stake_mult = 0.5
                elif garch_vol < current_vol * 0.5:
                    garch_regime = 'LOW_VOL'
                    stake_mult = 1.5
                else:
                    garch_regime = 'NORMAL'
                    stake_mult = 1.0
                garch_signal = {'signal': 'NEUTRAL', 'regime': garch_regime, 'stake_multiplier': stake_mult}
            else:
                # GARCH model analysis (core engine logic, not indicator computation)
                returns = df['close'].pct_change().dropna()
                if len(returns) > 50:
                    self.garch_model.fit(returns)
                    current_vol = float(latest.get('volatility_realized', 0) or 0)
                    garch_signal = self.garch_model.get_signal(current_vol)
                else:
                    garch_signal = {'signal': 'NEUTRAL', 'regime': 'UNKNOWN', 'stake_multiplier': 1.0}
            
            # Aggregate signals (same logic regardless of source)
            final_signal = self._aggregate_signals(
                ou_signal=ou_signal,
                garch_signal=garch_signal,
                hurst_signal=hurst_signal,
                indicators=indicators,
                current_price=current_price,
                hurst_min=hurst_min,
                hurst_max=hurst_max
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
                'duration': final_signal['duration'],
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
        current_price: float,
        hurst_min: float = 0.6,
        hurst_max: float = 0.7
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
        duration = 300  # Default duration (5 min)
        stake_multiplier = 1.0
        reasoning = []
        
        # Check Hurst first (regime filter)
        regime = hurst_signal.get('regime', 'RANDOM')
        is_mean_reversion_safe = hurst_signal.get('trade_recommended', False)
        
        # Block only if neither Mean Reversion nor Trending logic applies
        if not is_mean_reversion_safe and regime != 'TRENDING':
            reasoning.append(f"Hurst exponent {hurst_signal['hurst']:.3f} indicates {hurst_signal['regime']}")
            reasoning.append("Market regime unclear/random - HOLD")
            
            return self._hold_response(reasoning)
        
        # Regime is workable (either Mean Reversion or Trending)
        reasoning.append(f"Hurst {hurst_signal['hurst']:.3f} - {regime} regime active")
        
        # Get Regime
        regime = hurst_signal.get('regime', 'RANDOM')
        
        # LOGIC BRANCHING BASED ON REGIME
        
        if regime == 'MEAN_REVERSION':
            # MEAN REVERSION STRATEGY (O-U Driven)
            duration = self.ou_model.get_suggested_duration()
            
            ou_sig = ou_signal.get('signal', 'HOLD')
            ou_conf = ou_signal.get('confidence', 0.0)
            
            if ou_sig in ['CALL', 'PUT']:
                signal = ou_sig
                confidence = ou_conf
                half_life = ou_signal.get('half_life', 0)
                reasoning.append(f"Mean Reversion: {ou_signal['reason']} | Half-life: {half_life:.1f}min → Duration: {duration}s")
                contract_type = 'CALL' if ou_sig == 'CALL' else 'PUT'
            else:
                reasoning.append("O-U deviation below threshold - HOLD")
                return self._hold_response(reasoning)

        elif regime == 'TRENDING':
            # TREND FOLLOWING STRATEGY
            hurst_value = hurst_signal.get('hurst', 0.5)
            trend_strength = abs(hurst_value - 0.5)
            
            duration = 300  # Fixed 5 minutes
            
            # Hard filters: Hurst must be in sweet spot
            min_strength = hurst_min - 0.5
            max_strength = hurst_max - 0.5
            if trend_strength < min_strength:
                 reasoning.append(f"Trend too weak (Hurst={hurst_value:.3f}, min={hurst_min}) - HOLD")
                 return self._hold_response(reasoning)
            if trend_strength >= max_strength:
                 reasoning.append(f"Trend overextended (Hurst={hurst_value:.3f}, max={hurst_max}) - HOLD")
                 return self._hold_response(reasoning)

            reasoning.append(f"Trending (Hurst={hurst_value:.3f}) → Duration: {duration}s")
            
            # --- Gather ALL indicators ---
            ema_9 = indicators.get('ema_9', 0)
            ema_21 = indicators.get('ema_21', 0)
            ema_50 = indicators.get('ema_50', 0)
            rsi = indicators.get('rsi_14', 50)
            macd_hist = indicators.get('macd_histogram', 0)
            momentum_5 = indicators.get('momentum_5', 0)
            
            # Bollinger Bands
            bb_upper = indicators.get('bollinger_upper', 0)
            bb_middle = indicators.get('bollinger_middle', 0)
            bb_lower = indicators.get('bollinger_lower', 0)
            bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle else 0
            bb_position = (current_price - bb_lower) / (bb_upper - bb_lower + 1e-10) if (bb_upper - bb_lower) > 0 else 0.5
            
            # EMA crossover info
            ema_cross_age = indicators.get('ema_cross_age', 0)
            ema_diverging = indicators.get('ema_diverging', False)
            ema_sep_rate = indicators.get('ema_separation_rate', 0)
            ema_cross_dir = indicators.get('ema_cross_direction', 'NEUTRAL')
            
            # Rule 1: Crossover must persist for ≥2 candles
            if ema_cross_age < 2:
                reasoning.append(f"EMA crossover too recent ({ema_cross_age} bars) - HOLD")
                return self._hold_response(reasoning)
            # Rule 2: EMAs must be diverging, not converging
            if not ema_diverging:
                reasoning.append(f"EMAs converging (gap_rate={ema_sep_rate:.4f}) - HOLD")
                return self._hold_response(reasoning)
            
            reasoning.append(f"EMA cross: {ema_cross_dir} age={ema_cross_age}, diverging={ema_diverging}")
            
            # Determine direction via majority vote
            ema_trend = "BULLISH" if ema_21 > ema_50 else "BEARISH"
            price_trend = "BULLISH" if current_price > ema_50 else "BEARISH"  
            macd_trend = "BULLISH" if macd_hist > 0 else "BEARISH"
            
            bullish_votes = sum([
                ema_trend == "BULLISH",
                price_trend == "BULLISH",
                macd_trend == "BULLISH"
            ])
            
            trend = "BULLISH" if bullish_votes >= 2 else "BEARISH"
            
            # EMA separation (informative)
            ema_separation = abs(ema_21 - ema_50) / (ema_50 + 1e-10)
            trend_conf_bonus = min(ema_separation / 0.01, 0.15)
            
            # Require minimum trend strength
            if ema_separation < 0.001:
                reasoning.append(f"Trend too weak (EMA sep: {ema_separation:.4f}) - HOLD")
                return self._hold_response(reasoning)
            
            reasoning.append(f"Trend: {trend} (votes: {bullish_votes}/3, EMA21={ema_21:.2f}, EMA50={ema_50:.2f}, MACD={macd_hist:.4f})")
            
            # BB analysis (informative)
            bb_squeeze = bb_width < 0.005
            bb_expanding = bb_width > 0.008
            if bb_squeeze:
                reasoning.append(f"BB Squeeze (width={bb_width:.4f})")
            elif bb_expanding:
                reasoning.append(f"BB Expanding (width={bb_width:.4f})")
            else:
                reasoning.append(f"BB Normal (width={bb_width:.4f}, pos={bb_position:.2f})")
            
            # Set signal direction based on trend
            confidence = min(0.60 + trend_conf_bonus, 0.85)
            
            if trend == 'BULLISH':
                signal = 'CALL'
                contract_type = 'CALL'
                price_dist_pct = (current_price - ema_21) / ema_21 * 100 if ema_21 else 0
                
                if current_price < ema_50:
                    reasoning.append(f"⚠️ Price ({current_price:.2f}) < EMA50 ({ema_50:.2f})")
                    confidence = max(confidence - 0.10, 0.55)
                if current_price < ema_21:
                    reasoning.append(f"⚠️ Price ({current_price:.2f}) < EMA21 ({ema_21:.2f})")
                    confidence = max(confidence - 0.05, 0.55)
                if rsi >= 80:
                    confidence = max(confidence - 0.15, 0.55)
                    reasoning.append(f"⚠️ RSI {rsi:.1f} overbought")
                if price_dist_pct > 1.5:
                    confidence = max(confidence - 0.10, 0.55)
                    reasoning.append(f"⚠️ Price overextended +{price_dist_pct:.2f}% from EMA21")
                if momentum_5 < 0:
                    confidence = max(confidence - 0.05, 0.55)
                    reasoning.append(f"⚠️ Momentum decelerating ({momentum_5:.2f})")
                    
            elif trend == 'BEARISH':
                signal = 'PUT'
                contract_type = 'PUT'
                price_dist_pct = (ema_21 - current_price) / ema_21 * 100 if ema_21 else 0
                
                if current_price > ema_50:
                    reasoning.append(f"⚠️ Price ({current_price:.2f}) > EMA50 ({ema_50:.2f})")
                    confidence = max(confidence - 0.10, 0.55)
                if current_price > ema_21:
                    reasoning.append(f"⚠️ Price ({current_price:.2f}) > EMA21 ({ema_21:.2f})")
                    confidence = max(confidence - 0.05, 0.55)
                if rsi <= 20:
                    confidence = max(confidence - 0.15, 0.55)
                    reasoning.append(f"⚠️ RSI {rsi:.1f} deeply oversold")
                elif rsi <= 35:
                    confidence = max(confidence - 0.05, 0.55)
                    reasoning.append(f"⚠️ RSI {rsi:.1f} approaching oversold")
                if price_dist_pct > 1.5:
                    confidence = max(confidence - 0.10, 0.55)
                    reasoning.append(f"⚠️ Price overextended -{price_dist_pct:.2f}% from EMA21")
                if momentum_5 > 0:
                    confidence = max(confidence - 0.05, 0.55)
                    reasoning.append(f"⚠️ Momentum decelerating ({momentum_5:.2f})")
            

        
        else:
            # Random/Unknown regime
            return self._hold_response(reasoning + ["Regime unclear/Random - HOLD"])
            
        # ---------------------------------------------------------
        # COMMON ADJUSTMENTS (GARCH, Confirmations)
        # ---------------------------------------------------------
        
        # Apply GARCH volatility adjustment to stake
        garch_mult = garch_signal.get('stake_multiplier', 1.0)
        stake_multiplier = garch_mult
        reasoning.append(f"GARCH regime {garch_signal['regime']} → stake ×{garch_mult:.2f}")
        
        # Technical indicator confirmations (Boost confidence)
        rsi = indicators.get('rsi_14', 50)
        
        if contract_type == 'CALL':
            if rsi < 40 and regime == 'MEAN_REVERSION': 
                confidence = min(confidence * 1.1, 0.95); reasoning.append("RSI confirim (oversold)")
            if regime == 'TRENDING' and rsi > 50: # Momentum confirmation
                 confidence = min(confidence * 1.1, 0.90); reasoning.append("RSI momentum confirm")
                 
        elif contract_type == 'PUT':
            if rsi > 60 and regime == 'MEAN_REVERSION':
                 confidence = min(confidence * 1.1, 0.95); reasoning.append("RSI confirm (overbought)")
            if regime == 'TRENDING' and rsi < 50: # Momentum confirmation
                 confidence = min(confidence * 1.1, 0.90); reasoning.append("RSI momentum confirm")
        
        return {
            'signal': signal,
            'confidence': round(confidence, 4),
            'contract_type': contract_type,
            'stake_multiplier': round(stake_multiplier, 2),
            'duration': int(duration),
            'reasoning': ' | '.join(reasoning)
        }
    
    def _hold_response(self, reasoning_list) -> Dict[str, Any]:
        return {
            'signal': 'HOLD',
            'confidence': 0.0,
            'contract_type': None,
            'stake_multiplier': 1.0,
            'duration': 300,
            'reasoning': ' | '.join(reasoning_list)
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
            'duration': 300,
            'reasoning': 'Insufficient data for analysis'
        }
