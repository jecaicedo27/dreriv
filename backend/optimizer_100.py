"""
PARAMETER OPTIMIZER — 100 Configurations
Finds the best trading strategy parameters by simulating against 12h of live data.

Usage: docker exec deriv-backend python /app/optimizer_100.py
"""
import sys
sys.path.insert(0, '/app')

import json
import time
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from itertools import product
from app.core.database import SessionLocal
from app.models.models import Candle
from app.analysis.indicators import TechnicalIndicators
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
from app.analysis.garch import GARCHModel
from app.analysis.hurst import HurstExponent

# Suppress noisy logging during optimization
import logging
logging.disable(logging.CRITICAL)

# ============================================================
# PARAMETER SPACE — What we're optimizing
# ============================================================
PARAM_SPACE = {
    'ema_cross_age_min':   [1, 2, 3, 4, 5, 7, 10],
    'ema_sep_min':         [0.0005, 0.001, 0.0015, 0.002, 0.003, 0.004, 0.005],
    'rsi_upper':           [65, 68, 70, 72, 75, 78, 80],
    'rsi_lower':           [20, 25, 28, 30, 32, 35, 40],
    'price_dist_max':      [0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0],
    'hurst_trend_strength':[0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30],
    'require_diverging':   [True, False],
    'require_momentum':    [True, False],
    'duration_mode':       ['fixed_5m', 'fixed_10m', 'fixed_15m', 'fixed_20m', 'hurst_dynamic'],
    'confidence_base':     [0.65, 0.70, 0.75, 0.80],
}

# ============================================================
# CONFIG GENERATION — Latin Hypercube-inspired sampling
# ============================================================
def generate_configs(n=100):
    """Generate n random parameter configurations with good coverage."""
    configs = []
    
    # Config 0: Current production settings (baseline)
    configs.append({
        'id': 0,
        'name': 'BASELINE_CURRENT',
        'ema_cross_age_min': 3,
        'ema_sep_min': 0.002,
        'rsi_upper': 70,
        'rsi_lower': 30,
        'price_dist_max': 1.0,
        'hurst_trend_strength': 0.15,
        'require_diverging': True,
        'require_momentum': True,
        'duration_mode': 'hurst_dynamic',
        'confidence_base': 0.75,
    })
    
    # Config 1: Very conservative
    configs.append({
        'id': 1,
        'name': 'ULTRA_CONSERVATIVE',
        'ema_cross_age_min': 7,
        'ema_sep_min': 0.004,
        'rsi_upper': 65,
        'rsi_lower': 35,
        'price_dist_max': 0.5,
        'hurst_trend_strength': 0.25,
        'require_diverging': True,
        'require_momentum': True,
        'duration_mode': 'fixed_5m',
        'confidence_base': 0.80,
    })
    
    # Config 2: Aggressive
    configs.append({
        'id': 2,
        'name': 'AGGRESSIVE',
        'ema_cross_age_min': 1,
        'ema_sep_min': 0.001,
        'rsi_upper': 80,
        'rsi_lower': 20,
        'price_dist_max': 2.0,
        'hurst_trend_strength': 0.10,
        'require_diverging': False,
        'require_momentum': False,
        'duration_mode': 'fixed_5m',
        'confidence_base': 0.65,
    })
    
    # Config 3: Short duration specialist
    configs.append({
        'id': 3,
        'name': 'SHORT_DURATION',
        'ema_cross_age_min': 2,
        'ema_sep_min': 0.002,
        'rsi_upper': 72,
        'rsi_lower': 28,
        'price_dist_max': 0.7,
        'hurst_trend_strength': 0.15,
        'require_diverging': True,
        'require_momentum': True,
        'duration_mode': 'fixed_5m',
        'confidence_base': 0.70,
    })
    
    # Config 4: Long duration specialist  
    configs.append({
        'id': 4,
        'name': 'LONG_DURATION',
        'ema_cross_age_min': 5,
        'ema_sep_min': 0.003,
        'rsi_upper': 68,
        'rsi_lower': 32,
        'price_dist_max': 1.5,
        'hurst_trend_strength': 0.20,
        'require_diverging': True,
        'require_momentum': False,
        'duration_mode': 'fixed_20m',
        'confidence_base': 0.75,
    })
    
    # Generate remaining random configs
    random.seed(42)  # Reproducible
    for i in range(5, n):
        config = {
            'id': i,
            'name': f'RANDOM_{i:03d}',
            'ema_cross_age_min': random.choice(PARAM_SPACE['ema_cross_age_min']),
            'ema_sep_min': random.choice(PARAM_SPACE['ema_sep_min']),
            'rsi_upper': random.choice(PARAM_SPACE['rsi_upper']),
            'rsi_lower': random.choice(PARAM_SPACE['rsi_lower']),
            'price_dist_max': random.choice(PARAM_SPACE['price_dist_max']),
            'hurst_trend_strength': random.choice(PARAM_SPACE['hurst_trend_strength']),
            'require_diverging': random.choice(PARAM_SPACE['require_diverging']),
            'require_momentum': random.choice(PARAM_SPACE['require_momentum']),
            'duration_mode': random.choice(PARAM_SPACE['duration_mode']),
            'confidence_base': random.choice(PARAM_SPACE['confidence_base']),
        }
        configs.append(config)
    
    return configs


# ============================================================
# PARAMETERIZED STRATEGY — The core logic with adjustable params
# ============================================================
def evaluate_signal(params, indicators, hurst_signal, ou_signal, garch_signal, current_price):
    """
    Parameterized version of Layer1 _aggregate_signals.
    Returns: (signal, confidence, contract_type, duration, reasoning)
    """
    signal = 'HOLD'
    confidence = 0.0
    contract_type = None
    duration = 300
    reasoning = []
    
    regime = hurst_signal.get('regime', 'RANDOM')
    hurst_value = hurst_signal.get('hurst', 0.5)
    is_mean_reversion_safe = hurst_signal.get('trade_recommended', False)
    
    # Block if neither Mean Reversion nor Trending
    if not is_mean_reversion_safe and regime != 'TRENDING':
        return 'HOLD', 0, None, 300, 'Regime unclear/random'
    
    # =========== MEAN REVERSION ===========
    if regime == 'MEAN_REVERSION':
        ou_sig = ou_signal.get('signal', 'HOLD')
        ou_conf = ou_signal.get('confidence', 0.0)
        
        if ou_sig in ['CALL', 'PUT']:
            # Use O-U suggested duration
            ou_model = OrnsteinUhlenbeckModel()
            try:
                duration = ou_model.get_suggested_duration()
            except:
                duration = 300
            return ou_sig, ou_conf, ou_sig, duration, f'Mean Reversion: {ou_signal.get("reason", "")}'
        else:
            return 'HOLD', 0, None, 300, 'O-U deviation below threshold'
    
    # =========== TRENDING ===========
    elif regime == 'TRENDING':
        trend_strength = abs(hurst_value - 0.5)
        
        # Hurst trend strength filter
        if trend_strength < params['hurst_trend_strength']:
            return 'HOLD', 0, None, 300, f'Trend too weak (strength={trend_strength:.3f} < {params["hurst_trend_strength"]})'
        
        # Duration calculation
        dm = params['duration_mode']
        if dm == 'fixed_5m':
            duration = 300
        elif dm == 'fixed_10m':
            duration = 600
        elif dm == 'fixed_15m':
            duration = 900
        elif dm == 'fixed_20m':
            duration = 1200
        elif dm == 'hurst_dynamic':
            if trend_strength > 0.25:
                duration = 1800
            elif trend_strength > 0.20:
                duration = 1200
            elif trend_strength > 0.15:
                duration = 900
            else:
                duration = 600
        
        ema_9 = indicators.get('ema_9', 0)
        ema_21 = indicators.get('ema_21', 0)
        ema_50 = indicators.get('ema_50', 0)
        rsi = indicators.get('rsi_14', 50)
        macd_hist = indicators.get('macd_histogram', 0)
        
        # --- EMA CROSSOVER CONFIRMATION ---
        ema_cross_age = indicators.get('ema_cross_age', 0)
        ema_diverging = indicators.get('ema_diverging', False)
        ema_sep_rate = indicators.get('ema_separation_rate', 0)
        
        if ema_cross_age < params['ema_cross_age_min']:
            return 'HOLD', 0, None, duration, f'EMA cross too recent ({ema_cross_age} < {params["ema_cross_age_min"]})'
        
        if params['require_diverging'] and not ema_diverging:
            return 'HOLD', 0, None, duration, f'EMAs converging (rate={ema_sep_rate:.4f})'
        
        # Trend direction voting
        ema_trend = "BULLISH" if ema_21 > ema_50 else "BEARISH"
        price_trend = "BULLISH" if current_price > ema_50 else "BEARISH"
        macd_trend = "BULLISH" if macd_hist > 0 else "BEARISH"
        
        bullish_votes = sum([ema_trend == "BULLISH", price_trend == "BULLISH", macd_trend == "BULLISH"])
        trend = "BULLISH" if bullish_votes >= 2 else "BEARISH"
        
        # EMA separation
        ema_separation = abs(ema_21 - ema_50) / (ema_50 + 1e-10)
        if ema_separation < params['ema_sep_min']:
            return 'HOLD', 0, None, duration, f'EMA sep too weak ({ema_separation:.4f} < {params["ema_sep_min"]})'
        
        trend_conf_bonus = min(ema_separation / 0.01, 0.15)
        
        momentum_5 = indicators.get('momentum_5', 0)
        
        if trend == 'BULLISH':
            # Price above both EMAs
            if current_price < ema_50 or current_price < ema_21:
                return 'HOLD', 0, None, duration, 'Price not above both EMAs for CALL'
            
            # RSI filter
            if rsi >= params['rsi_upper']:
                return 'HOLD', 0, None, duration, f'RSI {rsi:.1f} >= {params["rsi_upper"]} overbought'
            
            # Overextension filter
            price_dist_pct = (current_price - ema_21) / ema_21 * 100
            if price_dist_pct > params['price_dist_max']:
                return 'HOLD', 0, None, duration, f'Overextended {price_dist_pct:.2f}% > {params["price_dist_max"]}%'
            
            # Momentum check
            if params['require_momentum'] and momentum_5 < 0:
                return 'HOLD', 0, None, duration, f'Momentum negative ({momentum_5:.2f})'
            
            signal = 'CALL'
            confidence = min(params['confidence_base'] + trend_conf_bonus, 0.92)
            contract_type = 'CALL'
            reasoning = f'CALL RSI={rsi:.1f} dist={price_dist_pct:.2f}% mom5={momentum_5:.2f}'
            
        elif trend == 'BEARISH':
            # Price below both EMAs
            if current_price > ema_50 or current_price > ema_21:
                return 'HOLD', 0, None, duration, 'Price not below both EMAs for PUT'
            
            # RSI filter
            if rsi <= params['rsi_lower']:
                return 'HOLD', 0, None, duration, f'RSI {rsi:.1f} <= {params["rsi_lower"]} oversold'
            
            # Overextension filter
            price_dist_pct = (ema_21 - current_price) / ema_21 * 100
            if price_dist_pct > params['price_dist_max']:
                return 'HOLD', 0, None, duration, f'Overextended below {price_dist_pct:.2f}% > {params["price_dist_max"]}%'
            
            # Momentum check
            if params['require_momentum'] and momentum_5 > 0:
                return 'HOLD', 0, None, duration, f'Momentum positive ({momentum_5:.2f})'
            
            signal = 'PUT'
            confidence = min(params['confidence_base'] + trend_conf_bonus, 0.92)
            contract_type = 'PUT'
            reasoning = f'PUT RSI={rsi:.1f} dist={price_dist_pct:.2f}% mom5={momentum_5:.2f}'
    
    return signal, confidence, contract_type, duration, reasoning


# ============================================================
# WALK-FORWARD SIMULATOR
# ============================================================
def simulate_config(params, precomputed, df_all, sim_start_idx, cooldown_bars=5):
    """
    Walk forward simulation for a single config using pre-computed model outputs.
    Returns dict with results.
    """
    STAKE = 10.0
    PAYOUT = 0.88
    
    trades = []
    last_trade_idx = -cooldown_bars
    
    for i in range(sim_start_idx, len(df_all)):
        if i - last_trade_idx < cooldown_bars:
            continue
        
        if i not in precomputed:
            continue
        
        pc = precomputed[i]
        current_price = float(df_all.iloc[i]['close'])
        
        # Use pre-computed values
        indicators = pc['indicators']
        hurst_result = pc['hurst']
        ou_signal = pc['ou']
        garch_signal = pc['garch']
        
        # Evaluate signal with this config's params
        sig, conf, ct, dur, reason = evaluate_signal(
            params, indicators, hurst_result, ou_signal, garch_signal, current_price
        )
        
        if sig in ['CALL', 'PUT'] and conf >= 0.60:
            # Calculate outcome
            future_bars = min(dur // 60, len(df_all) - i - 1)
            if future_bars < 1:
                continue
            
            future_idx = min(i + future_bars, len(df_all) - 1)
            future_price = float(df_all.iloc[future_idx]['close'])
            
            if sig == 'CALL':
                won = future_price > current_price
            else:
                won = future_price < current_price
            
            pnl = STAKE * PAYOUT if won else -STAKE
            
            trades.append({
                'bar': i,
                'time': str(df_all.iloc[i]['open_time']),
                'direction': sig,
                'confidence': conf,
                'entry': current_price,
                'exit': future_price,
                'duration_bars': future_bars,
                'won': won,
                'pnl': pnl,
            })
            
            last_trade_idx = i  # Set cooldown
    
    # Results
    total_trades = len(trades)
    wins = sum(1 for t in trades if t['won'])
    losses = total_trades - wins
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    return {
        'config_id': params['id'],
        'config_name': params['name'],
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 1),
        'total_pnl': round(total_pnl, 2),
        'avg_pnl': round(total_pnl / total_trades, 2) if total_trades > 0 else 0,
        'params': {k: v for k, v in params.items() if k not in ['id', 'name']},
        'trades': trades,
    }


# ============================================================
# MAIN EXECUTION
# ============================================================
def main():
    start_time = time.time()
    
    print("=" * 70)
    print("🔧 PARAMETER OPTIMIZER — 100 Configurations")
    print("=" * 70)
    
    # Load data
    db = SessionLocal()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=25)  # 24h + 1h warmup
    candles = db.query(Candle).filter(
        Candle.open_time >= cutoff
    ).order_by(Candle.open_time.asc()).all()
    db.close()
    
    print(f"📊 Loaded {len(candles)} candles")
    print(f"   Range: {candles[0].open_time} → {candles[-1].open_time}")
    
    # Convert to DataFrame
    data = [{
        'open_time': c.open_time,
        'open': float(c.open),
        'high': float(c.high),
        'low': float(c.low),
        'close': float(c.close),
        'volume': 0,
    } for c in candles]
    df_all = pd.DataFrame(data)
    
    # Simulation starts at bar 250 (Hurst needs 200 bars minimum)
    sim_start_idx = 250
    print(f"   Simulation starts at bar {sim_start_idx} ({len(df_all) - sim_start_idx} bars to simulate)")
    
    # ============================================================
    # PHASE 1: PRE-COMPUTE ALL MODELS (once per bar)
    # ============================================================
    print(f"\n⚡ Phase 1: Pre-computing models for {len(df_all) - sim_start_idx} bars...")
    
    ou_model = OrnsteinUhlenbeckModel()
    garch_model = GARCHModel()
    precomputed = {}
    LOOKBACK = 250
    
    for i in range(sim_start_idx, len(df_all)):
        start_idx = max(0, i - LOOKBACK)
        window = df_all.iloc[start_idx:i+1].copy()
        
        if len(window) < 50:
            continue
        
        try:
            # Indicators
            window_ind = TechnicalIndicators.calculate_all(window)
            indicators = TechnicalIndicators.get_latest_values(window_ind)
            
            # Hurst
            prices = window['close'].astype(float)
            hurst_val = HurstExponent.calculate(prices)
            if hurst_val < 0.45:
                h_regime, h_rec = 'MEAN_REVERSION', True
            elif hurst_val > 0.55:
                h_regime, h_rec = 'TRENDING', False
            else:
                h_regime, h_rec = 'RANDOM', False
            hurst_result = {'hurst': hurst_val, 'regime': h_regime, 'trade_recommended': h_rec}
            
            # O-U
            prices_series = window['close'].astype(float)
            try:
                ou_model.fit(prices_series)
                ou_signal = ou_model.get_signal(float(prices_series.iloc[-1]))
            except:
                ou_signal = {'signal': 'HOLD', 'confidence': 0}
            
            # GARCH
            try:
                prices_pd = window['close'].astype(float)
                returns = np.log(prices_pd / prices_pd.shift(1)).dropna()
                garch_model.fit(returns)
                garch_signal = garch_model.get_signal()
            except:
                garch_signal = {'regime': 'NORMAL', 'stake_multiplier': 1.0}
            
            precomputed[i] = {
                'indicators': indicators,
                'hurst': hurst_result,
                'ou': ou_signal,
                'garch': garch_signal,
            }
        except:
            continue
        
        # Progress
        if (i - sim_start_idx) % 100 == 0:
            print(f"   Pre-computed bar {i}/{len(df_all)} ({len(precomputed)} cached)")
    
    print(f"   ✅ Pre-computed {len(precomputed)} bars in {time.time()-start_time:.1f}s")
    
    # ============================================================
    # PHASE 2: RUN 100 CONFIGS (fast — just parameter evaluation)
    # ============================================================
    configs = generate_configs(100)
    print(f"\n🔄 Phase 2: Running {len(configs)} configurations...")
    print(f"   Cooldown between trades: 5 bars (5 min)")
    print("-" * 70)
    
    all_results = []
    
    for idx, config in enumerate(configs):
        result = simulate_config(config, precomputed, df_all, sim_start_idx, cooldown_bars=5)
        all_results.append(result)
        
        status = f"W={result['wins']} L={result['losses']} WR={result['win_rate']}% PnL=${result['total_pnl']:+.2f}"
        bar = "█" * (result['wins']) + "░" * (result['losses'])
        print(f"  [{idx+1:3d}/100] {config['name']:25s} → {result['total_trades']:2d} trades | {status} | {bar}")
    
    elapsed = time.time() - start_time
    
    # ============================================================
    # RESULTS ANALYSIS
    # ============================================================
    print(f"\n{'=' * 70}")
    print(f"📊 OPTIMIZATION RESULTS (completed in {elapsed:.1f}s)")
    print(f"{'=' * 70}")
    
    # Sort by wins (primary), then by win_rate, then by PnL
    ranked = sorted(all_results, key=lambda r: (r['wins'], r['win_rate'], r['total_pnl']), reverse=True)
    
    # Filter configs that had at least 1 trade
    had_trades = [r for r in ranked if r['total_trades'] > 0]
    no_trades = [r for r in ranked if r['total_trades'] == 0]
    
    print(f"\n📋 Summary:")
    print(f"   Configs with trades: {len(had_trades)}")
    print(f"   Configs with 0 trades: {len(no_trades)} (too conservative)")
    
    if had_trades:
        print(f"\n🏆 TOP 10 CONFIGURATIONS (by most wins):")
        print(f"{'Rank':>4s} | {'ID':>3s} | {'Name':25s} | {'Trades':>6s} | {'Wins':>4s} | {'WR%':>5s} | {'P&L':>8s} | Key Params")
        print("-" * 110)
        
        for rank, r in enumerate(had_trades[:10], 1):
            p = r['params']
            key_params = f"age≥{p['ema_cross_age_min']}, sep≥{p['ema_sep_min']}, RSI[{p['rsi_lower']}-{p['rsi_upper']}], dist≤{p['price_dist_max']}%, dur={p['duration_mode']}"
            print(f"  {rank:2d}  | {r['config_id']:3d} |  {r['config_name']:24s}| {r['total_trades']:6d} | {r['wins']:4d} | {r['win_rate']:4.1f}% | ${r['total_pnl']:+7.2f} | {key_params}")
        
        print(f"\n❌ BOTTOM 5 CONFIGURATIONS:")
        print(f"{'Rank':>4s} | {'ID':>3s} | {'Name':25s} | {'Trades':>6s} | {'Wins':>4s} | {'WR%':>5s} | {'P&L':>8s}")
        print("-" * 80)
        for r in had_trades[-5:]:
            print(f"  -- | {r['config_id']:3d} |  {r['config_name']:24s}| {r['total_trades']:6d} | {r['wins']:4d} | {r['win_rate']:4.1f}% | ${r['total_pnl']:+7.2f}")
    
    # ============================================================
    # BEST CONFIG DETAILS
    # ============================================================
    if had_trades:
        best = had_trades[0]
        print(f"\n{'=' * 70}")
        print(f"🥇 BEST CONFIGURATION: #{best['config_id']} ({best['config_name']})")
        print(f"{'=' * 70}")
        print(f"\n📊 Performance:")
        print(f"   Total Trades: {best['total_trades']}")
        print(f"   Wins: {best['wins']} | Losses: {best['losses']}")
        print(f"   Win Rate: {best['win_rate']}%")
        print(f"   Total P&L: ${best['total_pnl']:+.2f}")
        print(f"   Avg P&L/trade: ${best['avg_pnl']:+.2f}")
        
        print(f"\n⚙️ Parameters:")
        for key, val in best['params'].items():
            print(f"   {key:25s}: {val}")
        
        print(f"\n📝 Trade Log:")
        for t in best['trades']:
            outcome = "✅" if t['won'] else "❌"
            print(f"   {t['time'][:19]} | {t['direction']:4s} | conf={t['confidence']:.0%} | "
                  f"{t['entry']:.2f} → {t['exit']:.2f} ({t['duration_bars']}bars) | {outcome} ${t['pnl']:+.2f}")
    
    # ============================================================
    # SAVE FULL RESULTS
    # ============================================================
    output_file = '/app/optimization_results.json'
    
    # Remove trade details for compact JSON (keep only top 20 trades per config)
    compact_results = []
    for r in ranked:
        compact = {k: v for k, v in r.items() if k != 'trades'}
        compact['sample_trades'] = r['trades'][:5]  # First 5 trades only
        compact_results.append(compact)
    
    with open(output_file, 'w') as f:
        json.dump({
            'meta': {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'candles': len(candles),
                'configs_tested': len(configs),
                'elapsed_seconds': round(elapsed, 1),
            },
            'best_config': had_trades[0] if had_trades else None,
            'all_results': compact_results,
        }, f, indent=2, default=str)
    
    print(f"\n💾 Full results saved to: {output_file}")
    print(f"⏱️  Completed in {elapsed:.1f}s")
    
    # Return code for best config
    if had_trades and had_trades[0]['win_rate'] > 50:
        print(f"\n✅ Found profitable configuration! Win Rate: {had_trades[0]['win_rate']}%")
    elif had_trades:
        print(f"\n⚠️ Best config has {had_trades[0]['win_rate']}% win rate — needs more data or different approach")
    else:
        print(f"\n❌ All configs produced 0 trades — need to loosen constraints")


if __name__ == '__main__':
    main()
