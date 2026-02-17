"""
PHASE 2: GROQ VALIDATION — Top 5 Configs
Sends each L1 trade signal through Groq for confirmation/rejection.

Usage: docker exec deriv-backend python /app/optimizer_groq_phase2.py
"""
import sys
sys.path.insert(0, '/app')

import json
import time
import asyncio
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from app.core.database import SessionLocal
from app.models.models import Candle
from app.analysis.indicators import TechnicalIndicators
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from app.analysis.garch import GARCHModel
from app.analysis.hurst import HurstExponent
from app.services.groq_client import GroqTradingEngine
from app.prompts.trading_system_prompt import TRADING_SYSTEM_PROMPT

import logging
logging.disable(logging.CRITICAL)

# Top 5 profitable configs from Phase 1
TOP_CONFIGS = [
    {
        'id': 65, 'name': 'RANDOM_065_BEST',
        'ema_cross_age_min': 2, 'ema_sep_min': 0.001,
        'rsi_upper': 80, 'rsi_lower': 35,
        'price_dist_max': 1.5, 'hurst_trend_strength': 0.18,
        'require_diverging': True, 'require_momentum': True,
        'duration_mode': 'fixed_5m', 'confidence_base': 0.80,
    },
    {
        'id': 20, 'name': 'RANDOM_020_100WR',
        'ema_cross_age_min': 4, 'ema_sep_min': 0.001,
        'rsi_upper': 72, 'rsi_lower': 20,
        'price_dist_max': 2.0, 'hurst_trend_strength': 0.25,
        'require_diverging': False, 'require_momentum': True,
        'duration_mode': 'hurst_dynamic', 'confidence_base': 0.65,
    },
    {
        'id': 8, 'name': 'RANDOM_008_58WR',
        'ema_cross_age_min': 7, 'ema_sep_min': 0.002,
        'rsi_upper': 70, 'rsi_lower': 28,
        'price_dist_max': 0.5, 'hurst_trend_strength': 0.12,
        'require_diverging': False, 'require_momentum': True,
        'duration_mode': 'fixed_5m', 'confidence_base': 0.80,
    },
    {
        'id': 3, 'name': 'SHORT_DURATION_75WR',
        'ema_cross_age_min': 2, 'ema_sep_min': 0.002,
        'rsi_upper': 72, 'rsi_lower': 28,
        'price_dist_max': 0.7, 'hurst_trend_strength': 0.15,
        'require_diverging': True, 'require_momentum': True,
        'duration_mode': 'fixed_5m', 'confidence_base': 0.70,
    },
    {
        'id': 70, 'name': 'RANDOM_070_57WR',
        'ema_cross_age_min': 2, 'ema_sep_min': 0.002,
        'rsi_upper': 78, 'rsi_lower': 25,
        'price_dist_max': 2.0, 'hurst_trend_strength': 0.12,
        'require_diverging': True, 'require_momentum': False,
        'duration_mode': 'fixed_20m', 'confidence_base': 0.75,
    },
]


def format_market_context(indicators, hurst, ou, garch, current_price, l1_signal, l1_conf):
    """Format market data as context for Groq prompt."""
    return f"""
## Current Market Snapshot
- **Current Price**: {current_price:.2f}
- **Symbol**: Volatility_75_s (synthetic index)

## Technical Indicators
- EMA9: {indicators.get('ema_9', 0):.2f}
- EMA21: {indicators.get('ema_21', 0):.2f}
- EMA50: {indicators.get('ema_50', 0):.2f}
- RSI(14): {indicators.get('rsi_14', 50):.1f}
- MACD Histogram: {indicators.get('macd_histogram', 0):.4f}
- ATR(14): {indicators.get('atr_14', 0):.4f}
- Bollinger Upper: {indicators.get('bb_upper', 0):.2f}
- Bollinger Lower: {indicators.get('bb_lower', 0):.2f}
- EMA Cross Age: {indicators.get('ema_cross_age', 0)} bars
- EMA Diverging: {indicators.get('ema_diverging', False)}
- EMA Separation Rate: {indicators.get('ema_separation_rate', 0):.6f}
- 5-bar Momentum: {indicators.get('momentum_5', 0):.2f}

## Statistical Models
- **Hurst Exponent**: {hurst.get('hurst', 0.5):.4f} (Regime: {hurst.get('regime', 'UNKNOWN')})
- **O-U Signal**: {ou.get('signal', 'HOLD')} (conf: {ou.get('confidence', 0):.2f})
- **GARCH Regime**: {garch.get('regime', 'NORMAL')}

## Layer 1 Decision
- Signal: **{l1_signal}**
- Confidence: {l1_conf:.0%}
"""


def evaluate_signal(params, indicators, hurst_signal, ou_signal, garch_signal, current_price):
    """Same parameterized L1 logic from Phase 1."""
    regime = hurst_signal.get('regime', 'RANDOM')
    hurst_value = hurst_signal.get('hurst', 0.5)
    is_mean_reversion_safe = hurst_signal.get('trade_recommended', False)
    
    if not is_mean_reversion_safe and regime != 'TRENDING':
        return 'HOLD', 0, None, 300, 'Regime unclear/random'
    
    if regime == 'MEAN_REVERSION':
        ou_sig = ou_signal.get('signal', 'HOLD')
        ou_conf = ou_signal.get('confidence', 0.0)
        if ou_sig in ['CALL', 'PUT']:
            return ou_sig, ou_conf, ou_sig, 300, f'Mean Reversion: {ou_signal.get("reason", "")}'
        return 'HOLD', 0, None, 300, 'O-U deviation below threshold'
    
    elif regime == 'TRENDING':
        trend_strength = abs(hurst_value - 0.5)
        if trend_strength < params['hurst_trend_strength']:
            return 'HOLD', 0, None, 300, f'Trend too weak'
        
        dm = params['duration_mode']
        dur_map = {'fixed_5m': 300, 'fixed_10m': 600, 'fixed_15m': 900, 'fixed_20m': 1200}
        duration = dur_map.get(dm, 600)
        if dm == 'hurst_dynamic':
            duration = 1800 if trend_strength > 0.25 else (1200 if trend_strength > 0.20 else (900 if trend_strength > 0.15 else 600))
        
        ema_21 = indicators.get('ema_21', 0)
        ema_50 = indicators.get('ema_50', 0)
        rsi = indicators.get('rsi_14', 50)
        macd_hist = indicators.get('macd_histogram', 0)
        ema_cross_age = indicators.get('ema_cross_age', 0)
        ema_diverging = indicators.get('ema_diverging', False)
        
        if ema_cross_age < params['ema_cross_age_min']:
            return 'HOLD', 0, None, duration, 'EMA cross too recent'
        if params['require_diverging'] and not ema_diverging:
            return 'HOLD', 0, None, duration, 'EMAs converging'
        
        ema_trend = "BULLISH" if ema_21 > ema_50 else "BEARISH"
        price_trend = "BULLISH" if current_price > ema_50 else "BEARISH"
        macd_trend = "BULLISH" if macd_hist > 0 else "BEARISH"
        bullish_votes = sum([ema_trend == "BULLISH", price_trend == "BULLISH", macd_trend == "BULLISH"])
        trend = "BULLISH" if bullish_votes >= 2 else "BEARISH"
        
        ema_separation = abs(ema_21 - ema_50) / (ema_50 + 1e-10)
        if ema_separation < params['ema_sep_min']:
            return 'HOLD', 0, None, duration, 'EMA sep too weak'
        
        trend_conf_bonus = min(ema_separation / 0.01, 0.15)
        momentum_5 = indicators.get('momentum_5', 0)
        
        if trend == 'BULLISH':
            if current_price < ema_50 or current_price < ema_21:
                return 'HOLD', 0, None, duration, 'Price not above both EMAs'
            if rsi >= params['rsi_upper']:
                return 'HOLD', 0, None, duration, f'RSI overbought'
            price_dist = (current_price - ema_21) / ema_21 * 100
            if price_dist > params['price_dist_max']:
                return 'HOLD', 0, None, duration, 'Overextended'
            if params['require_momentum'] and momentum_5 < 0:
                return 'HOLD', 0, None, duration, 'Momentum negative'
            return 'CALL', min(params['confidence_base'] + trend_conf_bonus, 0.92), 'CALL', duration, 'CALL confirmed'
            
        elif trend == 'BEARISH':
            if current_price > ema_50 or current_price > ema_21:
                return 'HOLD', 0, None, duration, 'Price not below both EMAs'
            if rsi <= params['rsi_lower']:
                return 'HOLD', 0, None, duration, f'RSI oversold'
            price_dist = (ema_21 - current_price) / ema_21 * 100
            if price_dist > params['price_dist_max']:
                return 'HOLD', 0, None, duration, 'Overextended below'
            if params['require_momentum'] and momentum_5 > 0:
                return 'HOLD', 0, None, duration, 'Momentum positive'
            return 'PUT', min(params['confidence_base'] + trend_conf_bonus, 0.92), 'PUT', duration, 'PUT confirmed'
    
    return 'HOLD', 0, None, 300, 'No signal'


async def main():
    start_time = time.time()
    
    print("=" * 70)
    print("🧠 PHASE 2: GROQ VALIDATION — Top 5 Configs")
    print("=" * 70)
    
    # Init Groq
    groq = GroqTradingEngine()
    
    # Load data
    db = SessionLocal()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=13)
    candles = db.query(Candle).filter(Candle.open_time >= cutoff).order_by(Candle.open_time.asc()).all()
    db.close()
    
    data = [{
        'open_time': c.open_time,
        'open': float(c.open), 'high': float(c.high),
        'low': float(c.low), 'close': float(c.close), 'volume': 0,
    } for c in candles]
    df = pd.DataFrame(data)
    
    print(f"📊 Loaded {len(df)} candles")
    
    # Pre-compute models
    print("⚡ Pre-computing models...")
    sim_start = 250
    LOOKBACK = 250
    ou_model = OrnsteinUhlenbeckModel()
    garch_model = GARCHModel()
    precomputed = {}
    
    for i in range(sim_start, len(df)):
        start_idx = max(0, i - LOOKBACK)
        window = df.iloc[start_idx:i+1].copy()
        if len(window) < 50:
            continue
        try:
            window_ind = TechnicalIndicators.calculate_all(window)
            indicators = TechnicalIndicators.get_latest_values(window_ind)
            prices = window['close'].astype(float)
            hurst_val = HurstExponent.calculate(prices)
            h_regime = 'MEAN_REVERSION' if hurst_val < 0.45 else ('TRENDING' if hurst_val > 0.55 else 'RANDOM')
            h_rec = hurst_val < 0.45
            hurst = {'hurst': hurst_val, 'regime': h_regime, 'trade_recommended': h_rec}
            
            pa = window['close'].values.astype(float)
            try:
                ou_model.fit(pa)
                ou_sig = ou_model.get_signal(pa[-1])
            except:
                ou_sig = {'signal': 'HOLD', 'confidence': 0}
            
            try:
                pp = window['close'].astype(float)
                rets = np.log(pp / pp.shift(1)).dropna()
                garch_model.fit(rets)
                garch_sig = garch_model.get_signal()
            except:
                garch_sig = {'regime': 'NORMAL', 'stake_multiplier': 1.0}
            
            precomputed[i] = {'indicators': indicators, 'hurst': hurst, 'ou': ou_sig, 'garch': garch_sig}
        except:
            continue
    
    print(f"   ✅ Pre-computed {len(precomputed)} bars")
    
    # Run each config with Groq validation
    STAKE = 10.0
    PAYOUT = 0.88
    COOLDOWN = 5
    results_all = []
    groq_call_count = 0
    
    for config in TOP_CONFIGS:
        print(f"\n{'='*50}")
        print(f"🔬 Config #{config['id']}: {config['name']}")
        print(f"{'='*50}")
        
        trades_l1_only = []
        trades_groq_filtered = []
        last_trade_idx = -COOLDOWN
        
        for i in range(sim_start, len(df)):
            if i - last_trade_idx < COOLDOWN:
                continue
            if i not in precomputed:
                continue
            
            pc = precomputed[i]
            price = float(df.iloc[i]['close'])
            
            sig, conf, ct, dur, reason = evaluate_signal(
                config, pc['indicators'], pc['hurst'], pc['ou'], pc['garch'], price
            )
            
            if sig not in ['CALL', 'PUT'] or conf < 0.60:
                continue
            
            # Calculate actual outcome
            future_bars = min(dur // 60, len(df) - i - 1)
            if future_bars < 1:
                continue
            future_price = float(df.iloc[min(i + future_bars, len(df) - 1)]['close'])
            won = (future_price > price) if sig == 'CALL' else (future_price < price)
            pnl = STAKE * PAYOUT if won else -STAKE
            
            trade = {
                'bar': i, 'time': str(df.iloc[i]['open_time']),
                'direction': sig, 'entry': price, 'exit': future_price,
                'duration_bars': future_bars, 'won': won, 'pnl': pnl,
                'l1_confidence': conf,
            }
            trades_l1_only.append(trade.copy())
            
            # === GROQ VALIDATION ===
            market_ctx = format_market_context(
                pc['indicators'], pc['hurst'], pc['ou'], pc['garch'],
                price, sig, conf
            )
            
            try:
                groq_decision = await groq.get_decision(TRADING_SYSTEM_PROMPT, market_ctx)
                groq_call_count += 1
                
                groq_sig = groq_decision.get('decision', 'HOLD')
                groq_conf = groq_decision.get('confidence', 0)
                
                trade['groq_decision'] = groq_sig
                trade['groq_confidence'] = groq_conf
                
                # Groq confirms the trade?
                if groq_sig == sig and groq_conf >= 0.60:
                    trade['groq_approved'] = True
                    trades_groq_filtered.append(trade.copy())
                else:
                    trade['groq_approved'] = False
                    
                outcome_icon = "✅" if won else "❌"
                groq_icon = "🟢" if trade.get('groq_approved') else "🔴"
                print(f"  {trade['time'][:16]} | {sig} | L1={conf:.0%} | Groq={groq_sig}({groq_conf:.0%}) {groq_icon} | {outcome_icon} ${pnl:+.2f}")
                
                # Rate limit: 0.5s between Groq calls
                await asyncio.sleep(0.5)
                
            except Exception as e:
                trade['groq_decision'] = 'ERROR'
                trade['groq_approved'] = False
                print(f"  {trade['time'][:16]} | {sig} | Groq ERROR: {e}")
            
            last_trade_idx = i
        
        # Config summary
        l1_wins = sum(1 for t in trades_l1_only if t['won'])
        l1_total = len(trades_l1_only)
        l1_pnl = sum(t['pnl'] for t in trades_l1_only)
        
        gf_wins = sum(1 for t in trades_groq_filtered if t['won'])
        gf_total = len(trades_groq_filtered)
        gf_pnl = sum(t['pnl'] for t in trades_groq_filtered)
        
        # Trades Groq rejected that were actually losses (good filters)
        rejected = [t for t in trades_l1_only if not t.get('groq_approved', False)]
        rejected_losses = sum(1 for t in rejected if not t['won'])
        rejected_wins = sum(1 for t in rejected if t['won'])
        
        print(f"\n  📊 Config #{config['id']} Summary:")
        print(f"     L1 Only:      {l1_total:2d} trades | {l1_wins}W | WR={l1_wins/l1_total*100 if l1_total else 0:.1f}% | PnL=${l1_pnl:+.2f}")
        print(f"     Groq Filtered: {gf_total:2d} trades | {gf_wins}W | WR={gf_wins/gf_total*100 if gf_total else 0:.1f}% | PnL=${gf_pnl:+.2f}")
        print(f"     Groq rejected: {len(rejected)} trades ({rejected_losses} were losses ✅, {rejected_wins} were wins ❌)")
        
        results_all.append({
            'config_id': config['id'],
            'config_name': config['name'],
            'l1_only': {'trades': l1_total, 'wins': l1_wins, 'wr': round(l1_wins/l1_total*100, 1) if l1_total else 0, 'pnl': round(l1_pnl, 2)},
            'groq_filtered': {'trades': gf_total, 'wins': gf_wins, 'wr': round(gf_wins/gf_total*100, 1) if gf_total else 0, 'pnl': round(gf_pnl, 2)},
            'groq_rejected_losses': rejected_losses,
            'groq_rejected_wins': rejected_wins,
            'params': {k: v for k, v in config.items() if k not in ['id', 'name']},
        })
    
    # ============================================================
    # FINAL COMPARISON
    # ============================================================
    elapsed = time.time() - start_time
    
    print(f"\n{'='*70}")
    print(f"🏆 FINAL COMPARISON — L1 vs L1+Groq (completed in {elapsed:.1f}s)")
    print(f"{'='*70}")
    print(f"   Total Groq API calls: {groq_call_count}")
    
    print(f"\n{'Config':30s} | {'L1 Only':20s} | {'L1+Groq':20s} | Groq Value")
    print("-" * 95)
    
    for r in results_all:
        l1 = r['l1_only']
        gf = r['groq_filtered']
        saved = r['groq_rejected_losses']
        lost = r['groq_rejected_wins']
        value = (saved * STAKE) - (lost * STAKE * PAYOUT)
        print(f"  {r['config_name']:28s} | {l1['trades']:2d}T {l1['wins']:2d}W {l1['wr']:5.1f}% ${l1['pnl']:+7.2f} | "
              f"{gf['trades']:2d}T {gf['wins']:2d}W {gf['wr']:5.1f}% ${gf['pnl']:+7.2f} | "
              f"Saved ${saved*STAKE:.0f}, Lost ${lost*STAKE*PAYOUT:.0f} = ${value:+.2f}")
    
    # Find overall winner
    best_groq = max(results_all, key=lambda r: (r['groq_filtered']['wins'], r['groq_filtered']['wr'], r['groq_filtered']['pnl']))
    
    print(f"\n🥇 OVERALL WINNER (L1+Groq): Config #{best_groq['config_id']} ({best_groq['config_name']})")
    print(f"   Performance: {best_groq['groq_filtered']['trades']}T, {best_groq['groq_filtered']['wins']}W, "
          f"WR={best_groq['groq_filtered']['wr']}%, PnL=${best_groq['groq_filtered']['pnl']:+.2f}")
    print(f"   Parameters: {best_groq['params']}")
    
    # Save results
    output_file = '/app/optimization_groq_results.json'
    with open(output_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds': round(elapsed, 1),
            'groq_calls': groq_call_count,
            'winner': best_groq,
            'all_results': results_all,
        }, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to: {output_file}")


if __name__ == '__main__':
    asyncio.run(main())
