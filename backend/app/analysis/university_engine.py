"""
University Engine v2 — Enhanced Technical Analysis

Based on academic research (U of Bishops, Stevens Institute, QuantInsti, Oxford):
- Stochastic RSI with divergence detection
- Multi-confluence weighted scoring (7+ factors)
- Candlestick pattern confirmation
- ATR entry quality filter
- MACD histogram trend analysis

All indicators are READ from pre-computed DataFrame columns (pipeline-computed).
No internal indicator computation — compliant with engine contract.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
from loguru import logger

from app.analysis.base_engine import BaseAnalysisEngine
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from app.analysis.garch import GARCHModel


class UniversityEngine(BaseAnalysisEngine):
    """
    University Engine v2: Advanced Technical Analysis
    
    Improvements over Original v1:
    1. StochRSI for momentum + divergence detection
    2. Weighted confluence scoring (replaces 3-vote system)
    3. Candlestick pattern confirmation
    4. ATR-based entry quality filter
    5. MACD histogram trend analysis
    """
    
    name = "university_v2"
    version = "2.0"
    description = "University: StochRSI + Confluencia + Candlestick Patterns"
    
    def __init__(self):
        self.ou_model = OrnsteinUhlenbeckModel(window=200)
        self.garch_model = GARCHModel(window=100)
    
    # =================================================================
    # MAIN ANALYZE
    # =================================================================
    
    def analyze(self, df: pd.DataFrame, symbol: str = "R_100", **kwargs) -> Dict[str, Any]:
        """
        Full analysis pipeline with enhanced signal quality.
        """
        hurst_min = kwargs.get("hurst_min", 0.6)
        hurst_max = kwargs.get("hurst_max", 0.7)
        
        if df.empty or len(df) < 50:
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
                if abs(ou_dev) >= 2.0:
                    ou_dir = 'CALL' if ou_dev < -2.0 else 'PUT'
                    ou_conf = min(abs(ou_dev) / 4.0, 0.95)
                    ou_signal = {'signal': ou_dir, 'confidence': ou_conf, 'deviation': ou_dev, 'half_life': 15.0, 'reason': f'O-U deviation {ou_dev:.2f}σ → {ou_dir}'}
                else:
                    ou_signal = {'signal': 'HOLD', 'confidence': 0.0, 'deviation': ou_dev, 'half_life': 15.0, 'reason': f'O-U deviation {ou_dev:.2f}σ (below threshold)'}
            else:
                # O-U model analysis (core engine logic)
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
                garch_signal = {'signal': 'NEUTRAL', 'regime': garch_regime, 'stake_multiplier': stake_mult, 'forecast_mean': garch_vol}
            else:
                # GARCH model analysis (core engine logic)
                returns = df['close'].pct_change().dropna()
                if len(returns) > 50:
                    self.garch_model.fit(returns)
                    current_vol = float(latest.get('volatility_realized', 0) or 0)
                    garch_signal = self.garch_model.get_signal(current_vol)
                else:
                    garch_signal = {'signal': 'NEUTRAL', 'regime': 'UNKNOWN', 'stake_multiplier': 1.0}
            
            # Enhanced analysis — engine-specific (lightweight arithmetic on DataFrame columns)
            stoch_rsi = self._read_stoch_rsi(df)
            candlestick = self._detect_candlestick_patterns(df)
            macd_trend = self._analyze_macd_trend(df)
            atr_quality = self._calc_atr_entry_quality(df)
            divergence = self._detect_rsi_divergence(df)
            
            # Aggregate with enhanced logic
            result = self._aggregate_signals(
                ou_signal=ou_signal,
                garch_signal=garch_signal,
                hurst_signal=hurst_signal,
                indicators=indicators,
                stoch_rsi=stoch_rsi,
                candlestick=candlestick,
                macd_trend=macd_trend,
                atr_quality=atr_quality,
                divergence=divergence,
                current_price=current_price,
                hurst_min=hurst_min,
                hurst_max=hurst_max,
            )
            
            # Attach raw signals for L2 AI / debugging
            result['hurst_signal'] = hurst_signal
            result['ou_signal'] = ou_signal
            result['garch_signal'] = garch_signal
            result['indicators'] = indicators
            result['stoch_rsi'] = stoch_rsi
            result['candlestick_patterns'] = candlestick
            result['final_signal'] = result['signal']
            result['final_confidence'] = result['confidence']
            
            return result
            
        except Exception as e:
            logger.error(f"❌ UniversityEngine error: {e}")
            return self._empty_signal()

    # =================================================================
    # ENHANCED ANALYSIS (reads from DataFrame, no indicator computation)
    # =================================================================
    
    def _read_stoch_rsi(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Read StochRSI from pipeline and derive crossover/zone signals.
        K value is read from the 'stoch_rsi' column (0-100 scale).
        """
        try:
            if 'stoch_rsi' not in df.columns:
                return {"k": 0.5, "d": 0.5, "bullish_cross": False, "bearish_cross": False,
                        "overbought": False, "oversold": False, "zone": "neutral"}
            
            k_val = float(df.iloc[-1].get('stoch_rsi', 50) or 50) / 100.0  # Convert 0-100 to 0-1
            k_prev = float(df.iloc[-2].get('stoch_rsi', 50) or 50) / 100.0 if len(df) > 1 else k_val
            
            # Approximate D line from recent K values (3-period SMA)
            if len(df) >= 3:
                recent_k = [float(df.iloc[i].get('stoch_rsi', 50) or 50) / 100.0 for i in range(-3, 0)]
                d_val = sum(recent_k) / len(recent_k)
                recent_k_prev = [float(df.iloc[i].get('stoch_rsi', 50) or 50) / 100.0 for i in range(-4, -1)] if len(df) >= 4 else recent_k
                d_prev = sum(recent_k_prev) / len(recent_k_prev)
            else:
                d_val = k_val
                d_prev = k_prev
            
            # Crossover detection
            bullish_cross = k_prev <= d_prev and k_val > d_val
            bearish_cross = k_prev >= d_prev and k_val < d_val
            
            # Zones
            overbought = k_val > 0.80
            oversold = k_val < 0.20
            
            return {
                "k": round(k_val, 4),
                "d": round(d_val, 4),
                "bullish_cross": bullish_cross,
                "bearish_cross": bearish_cross,
                "overbought": overbought,
                "oversold": oversold,
                "zone": "overbought" if overbought else ("oversold" if oversold else "neutral"),
            }
        except Exception:
            return {"k": 0.5, "d": 0.5, "bullish_cross": False, "bearish_cross": False,
                    "overbought": False, "oversold": False, "zone": "neutral"}
    
    def _detect_candlestick_patterns(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Detect key candlestick patterns in last 3 candles.
        Uses raw OHLC data (not indicator computation).
        """
        try:
            if len(df) < 3:
                return {"pattern": None, "direction": "NEUTRAL", "strength": 0.0}
            
            c0 = df.iloc[-1]  # Current candle
            c1 = df.iloc[-2]  # Previous
            c2 = df.iloc[-3]
            
            o0, h0, l0, cl0 = float(c0['open']), float(c0['high']), float(c0['low']), float(c0['close'])
            o1, h1, l1, cl1 = float(c1['open']), float(c1['high']), float(c1['low']), float(c1['close'])
            o2, h2, l2, cl2 = float(c2['open']), float(c2['high']), float(c2['low']), float(c2['close'])
            
            body0 = abs(cl0 - o0)
            body1 = abs(cl1 - o1)
            range0 = h0 - l0 + 1e-10
            range1 = h1 - l1 + 1e-10
            
            # Bullish Engulfing
            if cl1 < o1 and cl0 > o0 and o0 <= cl1 and cl0 >= o1:
                return {"pattern": "bullish_engulfing", "direction": "BULLISH", "strength": 0.8}
            
            # Bearish Engulfing
            if cl1 > o1 and cl0 < o0 and o0 >= cl1 and cl0 <= o1:
                return {"pattern": "bearish_engulfing", "direction": "BEARISH", "strength": 0.8}
            
            # Hammer
            lower_wick = min(o0, cl0) - l0
            upper_wick = h0 - max(o0, cl0)
            if lower_wick > body0 * 2 and upper_wick < body0 * 0.5 and body0 / range0 < 0.35:
                return {"pattern": "hammer", "direction": "BULLISH", "strength": 0.6}
            
            # Shooting Star
            if upper_wick > body0 * 2 and lower_wick < body0 * 0.5 and body0 / range0 < 0.35:
                return {"pattern": "shooting_star", "direction": "BEARISH", "strength": 0.6}
            
            # Doji
            if body0 / range0 < 0.1:
                return {"pattern": "doji", "direction": "NEUTRAL", "strength": 0.3}
            
            # Three White Soldiers
            if cl0 > o0 and cl1 > o1 and cl2 > o2 and cl0 > cl1 > cl2:
                return {"pattern": "three_soldiers", "direction": "BULLISH", "strength": 0.7}
            
            # Three Black Crows
            if cl0 < o0 and cl1 < o1 and cl2 < o2 and cl0 < cl1 < cl2:
                return {"pattern": "three_crows", "direction": "BEARISH", "strength": 0.7}
            
            return {"pattern": None, "direction": "NEUTRAL", "strength": 0.0}
        except Exception:
            return {"pattern": None, "direction": "NEUTRAL", "strength": 0.0}
    
    def _analyze_macd_trend(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyze MACD histogram trend (reads from DataFrame columns)."""
        try:
            hist = df['macd_histogram'].astype(float)
            h_curr = float(hist.iloc[-1])
            h_prev = float(hist.iloc[-2]) if len(hist) > 1 else 0
            h_prev2 = float(hist.iloc[-3]) if len(hist) > 2 else 0
            
            growing = h_curr > h_prev > h_prev2
            shrinking = h_curr < h_prev < h_prev2
            
            if h_curr > 0:
                if growing:
                    trend = "STRONG_BULLISH"
                elif shrinking:
                    trend = "WEAKENING_BULLISH"
                else:
                    trend = "BULLISH"
            elif h_curr < 0:
                if shrinking:
                    trend = "STRONG_BEARISH"
                elif growing:
                    trend = "WEAKENING_BEARISH"
                else:
                    trend = "BEARISH"
            else:
                trend = "NEUTRAL"
            
            return {
                "value": round(h_curr, 6),
                "trend": trend,
                "growing": growing,
                "shrinking": shrinking,
            }
        except Exception:
            return {"value": 0, "trend": "NEUTRAL", "growing": False, "shrinking": False}
    
    def _calc_atr_entry_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """ATR-based entry quality (reads atr_14 from DataFrame)."""
        try:
            atr = float(df['atr_14'].iloc[-1]) if 'atr_14' in df.columns else 0
            candle_range = float(df.iloc[-1]['high']) - float(df.iloc[-1]['low'])
            
            if atr == 0:
                return {"ratio": 0, "quality": "unknown"}
            
            ratio = candle_range / atr
            
            if ratio < 0.5:
                quality = "excellent"
            elif ratio < 1.0:
                quality = "good"
            elif ratio < 1.5:
                quality = "fair"
            else:
                quality = "late"
            
            return {"ratio": round(ratio, 3), "quality": quality}
        except Exception:
            return {"ratio": 0, "quality": "unknown"}
    
    def _detect_rsi_divergence(self, df: pd.DataFrame, lookback: int = 10) -> Dict[str, Any]:
        """Detect RSI divergence (reads rsi_14 and close from DataFrame)."""
        try:
            if len(df) < lookback:
                return {"type": None, "detected": False}
            
            prices = df['close'].astype(float).values[-lookback:]
            rsi = df['rsi_14'].astype(float).values[-lookback:]
            
            price_min_idx = np.argmin(prices)
            price_max_idx = np.argmax(prices)
            
            price_last = prices[-1]
            rsi_last = rsi[-1]
            
            # Bullish divergence
            if price_last <= prices[price_min_idx] * 1.002:
                rsi_at_low = rsi[price_min_idx]
                if rsi_last > rsi_at_low + 3:
                    return {"type": "bullish", "detected": True, "strength": min((rsi_last - rsi_at_low) / 10, 1.0)}
            
            # Bearish divergence
            if price_last >= prices[price_max_idx] * 0.998:
                rsi_at_high = rsi[price_max_idx]
                if rsi_last < rsi_at_high - 3:
                    return {"type": "bearish", "detected": True, "strength": min((rsi_at_high - rsi_last) / 10, 1.0)}
            
            return {"type": None, "detected": False}
        except Exception:
            return {"type": None, "detected": False}
    
    # =================================================================
    # AGGREGATION — WEIGHTED CONFLUENCE SCORING
    # =================================================================
    
    def _aggregate_signals(
        self,
        ou_signal: Dict,
        garch_signal: Dict,
        hurst_signal: Dict,
        indicators: Dict,
        stoch_rsi: Dict,
        candlestick: Dict,
        macd_trend: Dict,
        atr_quality: Dict,
        divergence: Dict,
        current_price: float,
        hurst_min: float = 0.6,
        hurst_max: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Weighted confluence scoring system.
        """
        
        reasoning = []
        
        # ======== REGIME FILTER ========
        regime = hurst_signal.get('regime', 'RANDOM')
        is_mr_safe = hurst_signal.get('trade_recommended', False)
        
        if not is_mr_safe and regime != 'TRENDING':
            reasoning.append(f"Hurst {hurst_signal['hurst']:.3f} = {regime} → HOLD")
            return self._hold_response(reasoning)
        
        reasoning.append(f"Hurst {hurst_signal['hurst']:.3f} — {regime}")
        
        # ======== MEAN REVERSION (O-U driven) ========
        if regime == 'MEAN_REVERSION':
            duration = self.ou_model.get_suggested_duration()
            ou_sig = ou_signal.get('signal', 'HOLD')
            ou_conf = ou_signal.get('confidence', 0.0)
            
            if ou_sig in ('CALL', 'PUT'):
                confidence = ou_conf
                
                # Candlestick bonus/penalty
                if candlestick['direction'] == ('BULLISH' if ou_sig == 'CALL' else 'BEARISH'):
                    confidence = min(confidence * 1.1, 0.95)
                    reasoning.append(f"🕯️ {candlestick['pattern']} confirms {ou_sig}")
                elif candlestick['direction'] != 'NEUTRAL' and candlestick['direction'] != ('BULLISH' if ou_sig == 'CALL' else 'BEARISH'):
                    confidence = max(confidence * 0.9, 0.50)
                    reasoning.append(f"⚠️ {candlestick['pattern']} contradicts {ou_sig}")
                
                # Divergence super-confirmation
                if divergence['detected']:
                    if (divergence['type'] == 'bullish' and ou_sig == 'CALL') or \
                       (divergence['type'] == 'bearish' and ou_sig == 'PUT'):
                        confidence = min(confidence * 1.15, 0.95)
                        reasoning.append(f"📐 RSI divergence confirms {ou_sig}")
                
                reasoning.append(f"Mean Reversion: {ou_signal['reason']} → {ou_sig}")
                
                garch_mult = garch_signal.get('stake_multiplier', 1.0)
                
                return {
                    'signal': ou_sig,
                    'confidence': round(confidence, 4),
                    'contract_type': ou_sig,
                    'stake_multiplier': round(garch_mult, 2),
                    'duration': int(duration),
                    'reasoning': ' | '.join(reasoning),
                }
            else:
                reasoning.append("O-U deviation below threshold — HOLD")
                return self._hold_response(reasoning)
        
        # ======== TRENDING — WEIGHTED CONFLUENCE ========
        elif regime == 'TRENDING':
            hurst_value = hurst_signal.get('hurst', 0.5)
            trend_strength = abs(hurst_value - 0.5)
            duration = 300
            
            min_str = hurst_min - 0.5
            max_str = hurst_max - 0.5
            if trend_strength < min_str:
                reasoning.append(f"Trend too weak (Hurst={hurst_value:.3f}, min={hurst_min})")
                return self._hold_response(reasoning)
            if trend_strength >= max_str:
                reasoning.append(f"Trend overextended (Hurst={hurst_value:.3f}, max={hurst_max})")
                return self._hold_response(reasoning)
            
            reasoning.append(f"Trending (Hurst={hurst_value:.3f}) → {duration}s")
            
            # ---- Gather indicators ----
            ema_21 = indicators.get('ema_21', 0)
            ema_50 = indicators.get('ema_50', 0)
            rsi = indicators.get('rsi_14', 50)
            macd_hist = indicators.get('macd_histogram', 0)
            momentum_5 = indicators.get('momentum_5', 0)
            bb_upper = indicators.get('bollinger_upper', 0)
            bb_lower = indicators.get('bollinger_lower', 0)
            bb_middle = indicators.get('bollinger_middle', 0)
            
            # ---- WEIGHTED CONFLUENCE SCORING ----
            bullish_score = 0.0
            bearish_score = 0.0
            max_possible = 0.0
            
            # Factor 1: EMA Trend (weight 1.0)
            max_possible += 1.0
            if ema_21 > ema_50:
                bullish_score += 1.0
                reasoning.append("EMA21>EMA50 → Bull +1.0")
            else:
                bearish_score += 1.0
                reasoning.append("EMA21<EMA50 → Bear +1.0")
            
            # Factor 2: Price vs EMA50 (weight 1.0)
            max_possible += 1.0
            if current_price > ema_50:
                bullish_score += 1.0
            else:
                bearish_score += 1.0
            
            # Factor 3: MACD direction (weight 1.0)
            max_possible += 1.0
            if macd_hist > 0:
                bullish_score += 1.0
            else:
                bearish_score += 1.0
            
            # Factor 4: MACD histogram TREND (weight 0.5)
            max_possible += 0.5
            if macd_trend['trend'] in ('STRONG_BULLISH', 'BULLISH'):
                bullish_score += 0.5
                reasoning.append(f"MACD hist {macd_trend['trend']} +0.5")
            elif macd_trend['trend'] in ('STRONG_BEARISH', 'BEARISH'):
                bearish_score += 0.5
                reasoning.append(f"MACD hist {macd_trend['trend']} +0.5")
            elif macd_trend['trend'] == 'WEAKENING_BULLISH':
                bullish_score += 0.2
            elif macd_trend['trend'] == 'WEAKENING_BEARISH':
                bearish_score += 0.2
            
            # Factor 5: StochRSI Momentum (weight 1.5) — KEY FACTOR
            max_possible += 1.5
            if stoch_rsi['bullish_cross']:
                bullish_score += 1.5
                reasoning.append("StochRSI bullish cross +1.5 🔥")
            elif stoch_rsi['bearish_cross']:
                bearish_score += 1.5
                reasoning.append("StochRSI bearish cross +1.5 🔥")
            elif stoch_rsi['oversold']:
                bullish_score += 0.8
                reasoning.append("StochRSI oversold → bull +0.8")
            elif stoch_rsi['overbought']:
                bearish_score += 0.8
                reasoning.append("StochRSI overbought → bear +0.8")
            else:
                if stoch_rsi['k'] > 0.6:
                    bullish_score += 0.4
                elif stoch_rsi['k'] < 0.4:
                    bearish_score += 0.4
            
            # Factor 6: RSI Zone (weight 1.0)
            max_possible += 1.0
            if rsi > 55:
                bullish_score += min((rsi - 50) / 30, 1.0)
            elif rsi < 45:
                bearish_score += min((50 - rsi) / 30, 1.0)
            
            # Factor 7: Momentum (weight 1.0)
            max_possible += 1.0
            if momentum_5 > 0:
                bullish_score += 1.0
            elif momentum_5 < 0:
                bearish_score += 1.0
            
            # Factor 8: Candlestick Pattern (weight 1.0) — BONUS
            if candlestick['pattern'] is not None:
                max_possible += 1.0
                if candlestick['direction'] == 'BULLISH':
                    bullish_score += candlestick['strength']
                    reasoning.append(f"🕯️ {candlestick['pattern']} → Bull +{candlestick['strength']}")
                elif candlestick['direction'] == 'BEARISH':
                    bearish_score += candlestick['strength']
                    reasoning.append(f"🕯️ {candlestick['pattern']} → Bear +{candlestick['strength']}")
            
            # ---- DETERMINE DIRECTION ----
            total_score = max(bullish_score, bearish_score)
            net_score = bullish_score - bearish_score
            
            MIN_CONFLUENCE = 3.5
            
            if total_score < MIN_CONFLUENCE:
                reasoning.append(f"Score too low: Bull={bullish_score:.1f} Bear={bearish_score:.1f} (need {MIN_CONFLUENCE})")
                return self._hold_response(reasoning)
            
            if bullish_score > bearish_score:
                signal = 'CALL'
                contract_type = 'CALL'
                score_pct = bullish_score / max_possible
            else:
                signal = 'PUT'
                contract_type = 'PUT'
                score_pct = bearish_score / max_possible
            
            reasoning.append(f"Score: Bull={bullish_score:.1f} Bear={bearish_score:.1f} / {max_possible:.1f}")
            
            # ---- CONFIDENCE FROM SCORE ----
            confidence = 0.55 + (score_pct * 0.35)
            
            # ---- ADJUSTMENTS ----
            
            # ATR entry quality
            if atr_quality['quality'] == 'late':
                confidence = max(confidence - 0.10, 0.50)
                reasoning.append(f"⚠️ ATR late entry (ratio={atr_quality['ratio']})")
            elif atr_quality['quality'] == 'excellent':
                confidence = min(confidence + 0.05, 0.90)
                reasoning.append(f"✅ ATR excellent entry")
            
            # RSI extreme warnings
            if signal == 'CALL' and rsi >= 80:
                confidence = max(confidence - 0.15, 0.50)
                reasoning.append(f"⚠️ RSI {rsi:.0f} overbought for CALL")
            elif signal == 'PUT' and rsi <= 20:
                confidence = max(confidence - 0.15, 0.50)
                reasoning.append(f"⚠️ RSI {rsi:.0f} oversold for PUT")
            
            # Divergence super-confirmation or warning
            if divergence['detected']:
                if (divergence['type'] == 'bullish' and signal == 'CALL') or \
                   (divergence['type'] == 'bearish' and signal == 'PUT'):
                    confidence = min(confidence + 0.08, 0.92)
                    reasoning.append(f"📐 RSI {divergence['type']} divergence confirms!")
                elif (divergence['type'] == 'bullish' and signal == 'PUT') or \
                     (divergence['type'] == 'bearish' and signal == 'CALL'):
                    confidence = max(confidence - 0.10, 0.50)
                    reasoning.append(f"⚠️ RSI {divergence['type']} divergence contradicts!")
            
            # GARCH stake adjustment
            garch_mult = garch_signal.get('stake_multiplier', 1.0)
            reasoning.append(f"GARCH {garch_signal['regime']} → stake ×{garch_mult:.2f}")
            
            # BB analysis (informative)
            bb_width = (bb_upper - bb_lower) / (bb_middle + 1e-10) if bb_middle else 0
            if bb_width < 0.005:
                reasoning.append(f"BB Squeeze ({bb_width:.4f})")
            
            return {
                'signal': signal,
                'confidence': round(confidence, 4),
                'contract_type': contract_type,
                'stake_multiplier': round(garch_mult, 2),
                'duration': int(duration),
                'reasoning': ' | '.join(reasoning),
                'indicators': {
                    'ema_21': ema_21,
                    'ema_50': ema_50,
                    'rsi_14': rsi,
                    'macd_histogram': macd_hist,
                    'bb_width': round(bb_width, 5),
                    'momentum_5': momentum_5,
                },
            }
        
        else:
            return self._hold_response(reasoning + [f"Regime unclear ({regime})"])
    
    # =================================================================
    # HELPERS
    # =================================================================
    
    def _hold_response(self, reasoning_list):
        return {
            'signal': 'HOLD',
            'confidence': 0.0,
            'contract_type': None,
            'stake_multiplier': 1.0,
            'duration': 300,
            'reasoning': ' | '.join(reasoning_list),
            'final_signal': 'HOLD',
            'final_confidence': 0.0,
        }
    
    def _empty_signal(self):
        return {
            'signal': 'HOLD',
            'confidence': 0.0,
            'contract_type': None,
            'stake_multiplier': 1.0,
            'duration': 300,
            'reasoning': 'Insufficient data',
            'final_signal': 'HOLD',
            'final_confidence': 0.0,
            'hurst_signal': {'hurst': 0.5, 'regime': 'UNKNOWN'},
            'ou_signal': {},
            'garch_signal': {'regime': 'UNKNOWN', 'stake_multiplier': 1.0},
            'indicators': {},
        }
