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
                'duration': final_signal['duration'],  # Changed from suggested_duration
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
        duration = 300  # Default duration (5 min)
        stake_multiplier = 1.0
        reasoning = []
        
        # Check Hurst first (regime filter)
        # Originally, Hurst only recommended trades for MEAN_REVERSION. 
        # Now we support TRENDING too, so we allow pass if regime is TRENDING.
        
        regime = hurst_signal.get('regime', 'RANDOM')
        is_mean_reversion_safe = hurst_signal.get('trade_recommended', False)
        
        # Block only if neither Mean Reversion nor Trending logic applies (e.g. Random Walk)
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
            # ---------------------------------------------------------
            # MEAN REVERSION STRATEGY (O-U Driven)
            # ---------------------------------------------------------
            # Duration based on O-U half-life (dynamic: 60s - 3600s)
            duration = self.ou_model.get_suggested_duration()
            
            ou_sig = ou_signal.get('signal', 'HOLD')
            ou_conf = ou_signal.get('confidence', 0.0)
            
            if ou_sig in ['CALL', 'PUT']:
                signal = ou_sig
                confidence = ou_conf
                half_life = ou_signal.get('half_life', 0)
                reasoning.append(f"Mean Reversion: {ou_signal['reason']} | Half-life: {half_life:.1f}min → Duration: {duration}s")
                
                # Assign contract type
                contract_type = 'CALL' if ou_sig == 'CALL' else 'PUT'
            else:
                reasoning.append("O-U deviation below threshold - HOLD")
                # Return HOLD immediately in pure mean reversion regime if no OU signal
                # Unless we want to check other things? No, keep it simple.
                return self._hold_response(reasoning)

        elif regime == 'TRENDING':
            # ---------------------------------------------------------
            # TREND FOLLOWING STRATEGY (EMA/MACD Driven)
            # ---------------------------------------------------------
            # Dynamic duration based on trend strength
            hurst_value = hurst_signal.get('hurst', 0.5)
            trend_strength = abs(hurst_value - 0.5)  # 0 = weak, 0.5 = very strong
            
            # HARDENED THRESHOLDS (Feb 13 Training)
            # Old: 0.1 (0.60) was too permissive for weak chop
            # New: 0.15 (0.65) minimum for trending signal
            
            # Fixed duration of 5 minutes (Config #65 optimal)
            duration = 300
            
            # CRITICAL FILTER: Enforce minimum trend strength
            # 0.10 = Hurst >= 0.60 (more entries, still filters weak chop)
            if trend_strength < 0.10:
                 reasoning.append(f"Trend too weak (Hurst={hurst_value:.3f}, str={trend_strength:.3f} < 0.10) - HOLD")
                 return self._hold_response(reasoning)

            reasoning.append(f"Trending (Hurst={hurst_value:.3f}) → Fixed Duration: {duration}s")
            
            # Multi-indicator trend detection (prevents false signals)
            ema_9 = indicators.get('ema_9', 0)
            ema_21 = indicators.get('ema_21', 0)
            ema_50 = indicators.get('ema_50', 0)
            rsi = indicators.get('rsi_14', 50)
            macd_hist = indicators.get('macd_histogram', 0)
            
            # Bollinger Bands
            bb_upper = indicators.get('bollinger_upper', 0)
            bb_middle = indicators.get('bollinger_middle', 0)
            bb_lower = indicators.get('bollinger_lower', 0)
            bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle else 0
            bb_position = (current_price - bb_lower) / (bb_upper - bb_lower + 1e-10) if (bb_upper - bb_lower) > 0 else 0.5
            
            # --- EMA CROSSOVER CONFIRMATION (Feb 15 Training) ---
            # Prevents premature entries before crossover is confirmed
            ema_cross_age = indicators.get('ema_cross_age', 0)
            ema_diverging = indicators.get('ema_diverging', False)
            ema_sep_rate = indicators.get('ema_separation_rate', 0)
            ema_cross_dir = indicators.get('ema_cross_direction', 'NEUTRAL')
            
            # Rule 1: Crossover must persist for ≥2 candles (Config #65)
            if ema_cross_age < 2:
                reasoning.append(f"EMA crossover too recent ({ema_cross_age} bars < 2 required) - Wait for confirmation - HOLD")
                return self._hold_response(reasoning)
            
            # Rule 2: EMAs must be diverging (gap growing = momentum)
            if not ema_diverging:
                reasoning.append(f"EMAs converging (gap_rate={ema_sep_rate:.4f}) - Trend losing momentum - HOLD")
                return self._hold_response(reasoning)
            
            reasoning.append(f"EMA cross confirmed: {ema_cross_dir} age={ema_cross_age} bars, diverging={ema_diverging}")
            
            # Require at least 2/3 indicators to confirm trend
            ema_trend = "BULLISH" if ema_21 > ema_50 else "BEARISH"
            price_trend = "BULLISH" if current_price > ema_50 else "BEARISH"  
            macd_trend = "BULLISH" if macd_hist > 0 else "BEARISH"
            
            bullish_votes = sum([
                ema_trend == "BULLISH",
                price_trend == "BULLISH",
                macd_trend == "BULLISH"
            ])
            
            trend = "BULLISH" if bullish_votes >= 2 else "BEARISH"
            
            # Calculate trend strength (EMA separation)
            ema_separation = abs(ema_21 - ema_50) / (ema_50 + 1e-10)
            trend_conf_bonus = min(ema_separation / 0.01, 0.15)  # Up to +15% confidence
            
            # Require minimum trend strength (Config #65: 0.001)
            if ema_separation < 0.001:
                reasoning.append(f"Trend too weak (EMA sep: {ema_separation:.4f}) - HOLD")
                return self._hold_response(reasoning)
            
            reasoning.append(f"Trend: {trend} (votes: {bullish_votes}/3, EMA21={ema_21:.2f}, EMA50={ema_50:.2f}, MACD={macd_hist:.4f})")
            
            # --- BOLLINGER BANDS ANALYSIS ---
            bb_squeeze = bb_width < 0.005  # Bands very tight = volatility compression
            bb_expanding = bb_width > 0.008  # Bands wide = strong move underway
            
            if bb_squeeze:
                reasoning.append(f"BB Squeeze detected (width={bb_width:.4f}) — breakout imminent")
            elif bb_expanding:
                reasoning.append(f"BB Expanding (width={bb_width:.4f}) — strong momentum")
            else:
                reasoning.append(f"BB Normal (width={bb_width:.4f}, pos={bb_position:.2f})")
            
            if trend == 'BULLISH':
                # Looking for CALLs (Dip buying or Breakout)
                
                # CRITICAL: Price must be above BOTH EMAs for full breakout confirmation
                if current_price < ema_50:
                    reasoning.append(f"Price ({current_price:.2f}) < EMA50 ({ema_50:.2f}) - No full breakout - HOLD")
                    return self._hold_response(reasoning)
                
                # Price must also be above EMA21 (Counter-momentum check)
                if current_price < ema_21:
                    reasoning.append(f"Trend BULLISH but Price ({current_price:.2f}) < EMA21 ({ema_21:.2f}) - Wait for pullback/breakout - HOLD")
                    return self._hold_response(reasoning)
                
                # --- EXHAUSTION INDICATORS (informative, not blocking) ---
                # These reduce confidence and add notes for Groq to evaluate
                
                signal = 'CALL'
                confidence = min(0.80 + trend_conf_bonus, 0.95)
                
                # 1. RSI overbought warning
                if rsi >= 80:
                    confidence = max(confidence - 0.15, 0.55)
                    reasoning.append(f"⚠️ RSI {rsi:.1f} >= 80 - Overbought, reversal risk (conf -{15}%)")
                elif rsi >= 70:
                    confidence = max(confidence - 0.05, 0.60)
                    reasoning.append(f"⚠️ RSI {rsi:.1f} >= 70 - Approaching overbought (conf -5%)")
                
                # 2. Price overextended from EMA21
                price_dist_pct = (current_price - ema_21) / ema_21 * 100
                if price_dist_pct > 1.5:
                    confidence = max(confidence - 0.10, 0.55)
                    reasoning.append(f"⚠️ Price overextended from EMA21 ({price_dist_pct:.2f}% > 1.5%) (conf -10%)")
                
                # 3. Momentum decelerating
                momentum_5 = indicators.get('momentum_5', 0)
                if momentum_5 < 0:
                    confidence = max(confidence - 0.10, 0.55)
                    reasoning.append(f"⚠️ 5-bar momentum negative ({momentum_5:.2f}) - Decelerating (conf -10%)")
                
                # Bollinger Band confidence adjustment for CALL
                if bb_position > 0.7 and bb_expanding:
                    confidence = min(confidence + 0.05, 0.95)
                    reasoning.append(f"BB boost: price riding upper band (pos={bb_position:.2f})")
                elif bb_squeeze:
                    confidence = min(confidence + 0.03, 0.95)
                    reasoning.append(f"BB boost: squeeze breakout")
                elif bb_position < 0.3:
                    confidence = max(confidence - 0.05, 0.55)
                    reasoning.append(f"BB caution: price near lower band in bullish trend (pos={bb_position:.2f})")
                
                contract_type = 'CALL'
                reasoning.append(f"CALL signal (RSI={rsi:.1f}, dist={price_dist_pct:.2f}%, mom5={momentum_5:.2f}) conf={confidence:.0%}")
                    
            elif trend == 'BEARISH':
                # Looking for PUTs
                
                # CRITICAL: Price must be below BOTH EMAs for full breakdown confirmation
                if current_price > ema_50:
                    reasoning.append(f"Price ({current_price:.2f}) > EMA50 ({ema_50:.2f}) - No full breakdown - HOLD")
                    return self._hold_response(reasoning)
                
                # Price must also be below EMA21 (Counter-trend check)
                if current_price > ema_21:
                    reasoning.append(f"Trend BEARISH but Price ({current_price:.2f}) > EMA21 ({ema_21:.2f}) - Counter-trend spike - HOLD")
                    return self._hold_response(reasoning)
                
                # --- EXHAUSTION INDICATORS (informative, not blocking) ---
                # These reduce confidence and add notes for Groq to evaluate
                
                signal = 'PUT'
                confidence = min(0.80 + trend_conf_bonus, 0.95)
                
                # 1. RSI oversold warning
                if rsi <= 20:
                    confidence = max(confidence - 0.15, 0.55)
                    reasoning.append(f"⚠️ RSI {rsi:.1f} <= 20 - Deeply oversold, bounce risk (conf -15%)")
                elif rsi <= 35:
                    confidence = max(confidence - 0.05, 0.60)
                    reasoning.append(f"⚠️ RSI {rsi:.1f} <= 35 - Approaching oversold (conf -5%)")
                
                # 2. Price overextended below EMA21
                price_dist_pct = (ema_21 - current_price) / ema_21 * 100
                if price_dist_pct > 1.5:
                    confidence = max(confidence - 0.10, 0.55)
                    reasoning.append(f"⚠️ Price overextended below EMA21 ({price_dist_pct:.2f}% > 1.5%) (conf -10%)")
                
                # 3. Momentum decelerating
                momentum_5 = indicators.get('momentum_5', 0)
                if momentum_5 > 0:
                    confidence = max(confidence - 0.10, 0.55)
                    reasoning.append(f"⚠️ 5-bar momentum positive ({momentum_5:.2f}) - Decelerating (conf -10%)")
                
                # Bollinger Band confidence adjustment for PUT
                if bb_position < 0.3 and bb_expanding:
                    confidence = min(confidence + 0.05, 0.95)
                    reasoning.append(f"BB boost: price riding lower band (pos={bb_position:.2f})")
                elif bb_squeeze:
                    confidence = min(confidence + 0.03, 0.95)
                    reasoning.append(f"BB boost: squeeze breakdown")
                elif bb_position > 0.7:
                    confidence = max(confidence - 0.05, 0.55)
                    reasoning.append(f"BB caution: price near upper band in bearish trend (pos={bb_position:.2f})")
                
                contract_type = 'PUT'
                reasoning.append(f"PUT signal (RSI={rsi:.1f}, dist={price_dist_pct:.2f}%, mom5={momentum_5:.2f}) conf={confidence:.0%}")
        
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
            'duration': 300,  # Changed from suggested_duration
            'reasoning': 'Insufficient data for analysis'
        }
