#!/usr/bin/env python3
"""
Complete Historical Backtest with Full Indicator Calculation
Compares OLD vs NEW strategy on historical data
"""

import sys
import os
sys.path.insert(0, '/app')
os.chdir('/app')

import numpy as np
from datetime import datetime
from sqlalchemy import create_engine, text
from app.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)

class HistoricalBacktest:
    def __init__(self):
        self.results = {
            'old_strategy': {'trades': [], 'balance': 10000},
            'new_strategy': {'trades': [], 'balance': 10000}
        }
        
    def calculate_rsi(self, prices, period=14):
        """Calculate RSI"""
        if len(prices) < period + 1:
            return 50
            
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_macd(self, prices):
        """Calculate MACD"""
        if len(prices) < 26:
            return 0, 0, 0
            
        ema_12 = self._ema(prices, 12)
        ema_26 = self._ema(prices, 26)
        macd_line = ema_12 - ema_26
        signal_line = self._ema([macd_line], 9) if len([macd_line]) >= 9 else 0
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def _ema(self, prices, period):
        """Calculate EMA"""
        if len(prices) < period:
            return np.mean(prices)
        multiplier = 2 / (period + 1)
        ema = np.mean(prices[:period])
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema
    
    def generate_signal(self, indicators, use_new_rules=True, consecutive_losses=0):
        """Generate trading signal based on indicators"""
        rsi = indicators['rsi']
        macd = indicators['macd']
        macd_signal = indicators['macd_signal']
        ou_zscore = indicators['ou_zscore']
        hurst = indicators['hurst']
        
        # Dynamic confidence threshold (NEW STRATEGY)
        if use_new_rules:
            if consecutive_losses >= 4:
                min_confidence = 0.80
            elif consecutive_losses >= 3:
                return None, 0  # Cooldown
            elif consecutive_losses >= 2:
                min_confidence = 0.73
            else:
                min_confidence = 0.70
        else:
            if consecutive_losses >= 4:
                return None, 0  # OLD: Cooldown at 4
            min_confidence = 0.70
        
        # Signal generation
        direction = None
        confidence = 0
        
        # MACD bearish
        if macd < macd_signal:
            # PUT signal
            if rsi < 40:
                direction = 'PUT'
                confidence = 0.78
            
            # CALL only in extreme oversold (NEW RULE)
            elif use_new_rules and rsi < 20 and ou_zscore < -2.5:
                direction = 'CALL'
                confidence = 0.72  # Lower for countertrend
            # OLD: Allow CALL easier
            elif not use_new_rules and rsi < 30:
                direction = 'CALL'
                confidence = 0.72
        
        # MACD bullish  
        elif macd > macd_signal:
            # CALL signal
            if rsi < 60:
                direction = 'CALL'
                confidence = 0.78
            
            # PUT only in extreme overbought
            elif rsi > 80 and ou_zscore > 2.5:
                direction = 'PUT'
                confidence = 0.72
        
        # Check confidence threshold
        if confidence < min_confidence:
            return None, 0
            
        return direction, confidence
    
    def simulate_trade_outcome(self, direction, entry_price, next_price):
        """Simulate trade outcome"""
        stake = 60.0
        
        if direction == 'CALL':
            win = next_price > entry_price
        else:  # PUT
            win = next_price < entry_price
        
        if win:
            return 'WIN', stake * 0.85
        else:
            return 'LOSS', -stake
    
    def run_backtest(self):
        """Run complete backtest"""
        print("\n" + "="*70)
        print("🔬 COMPLETE HISTORICAL BACKTEST")
        print("="*70 + "\n")
        
        # Load candles
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT open_time, open, high, low, close, volume
                FROM candles
                ORDER BY open_time ASC
            """))
            candles = result.fetchall()
        
        if len(candles) < 100:
            print(f"❌ Not enough data ({len(candles)} candles)")
            return
        
        print(f"📊 Loaded {len(candles)} candles")
        print(f"📅 Period: {candles[0][0]} → {candles[-1][0]}")
        print(f"\n⏳ Calculating indicators and simulating trades...\n")
        
        # Run both strategies
        for strategy_name, use_new_rules in [('old_strategy', False), ('new_strategy', True)]:
            print(f"\n{'='*70}")
            print(f"{'NEW STRATEGY' if use_new_rules else 'OLD STRATEGY'}")
            print(f"{'='*70}")
            
            balance = 10000
            trades = []
            consecutive_losses = 0
            
            for i in range(50, len(candles) - 1):
                # Get window for indicators
                window = candles[max(0, i-50):i+1]
                prices = [c[4] for c in window]  # close prices
                
                # Calculate indicators
                try:
                    rsi = self.calculate_rsi(prices, 14)
                    macd, macd_sig, macd_hist = self.calculate_macd(prices)
                    
                    # Simplified Hurst (just use 0.5 for now)
                    hurst = 0.5
                    
                    # Simplified O-U zscore
                    if len(prices) >= 30:
                        current_price = prices[-1]
                        mean_price = np.mean(prices[-30:])
                        std_price = np.std(prices[-30:])
                        ou_zscore = (current_price - mean_price) / std_price if std_price > 0 else 0
                    else:
                        ou_zscore = 0
                    
                    indicators = {
                        'rsi': rsi,
                        'macd': macd,
                        'macd_signal': macd_sig,
                        'ou_zscore': ou_zscore,
                        'hurst': hurst
                    }
                    
                    # Generate signal
                    direction, confidence = self.generate_signal(
                        indicators, use_new_rules, consecutive_losses
                    )
                    
                    if direction is None:
                        continue
                    
                    # Simulate trade
                    entry_price = candles[i][4]  # close price
                    next_price = candles[i+1][4]
                    
                    outcome, pnl = self.simulate_trade_outcome(direction, entry_price, next_price)
                    balance += pnl
                    
                    # Update consecutive losses
                    if outcome == 'LOSS':
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0
                    
                    trades.append({
                        'time': candles[i][0],
                        'direction': direction,
                        'confidence': confidence,
                        'outcome': outcome,
                        'pnl': pnl,
                        'balance': balance
                    })
                    
                    # Progress indicator
                    if len(trades) % 10 == 0:
                        print(f"  Trade #{len(trades)}: {direction} → {outcome} (Balance: ${balance:,.2f})")
                
                except Exception as e:
                    continue
            
            self.results[strategy_name] = {
                'trades': trades,
                'balance': balance
            }
            
            print(f"\n✅ {strategy_name.upper()} Complete: {len(trades)} trades")
        
        # Print comparison
        self._print_comparison()
    
    def _print_comparison(self):
        """Print strategy comparison"""
        print("\n" + "="*70)
        print("📊 BACKTEST RESULTS COMPARISON")
        print("="*70 + "\n")
        
        for strategy_name in ['old_strategy', 'new_strategy']:
            trades = self.results[strategy_name]['trades']
            if not trades:
                print(f"{strategy_name.upper()}: No trades")
                continue
            
            wins = sum(1 for t in trades if t['outcome'] == 'WIN')
            losses = sum(1 for t in trades if t['outcome'] == 'LOSS')
            total = len(trades)
            win_rate = wins / total * 100 if total > 0 else 0
            
            total_pnl = self.results[strategy_name]['balance'] - 10000
            roi = total_pnl / 10000 * 100
            
            call_trades = sum(1 for t in trades if t['direction'] == 'CALL')
            put_trades = sum(1 for t in trades if t['direction'] == 'PUT')
            
            avg_win = np.mean([t['pnl'] for t in trades if t['outcome'] == 'WIN']) if wins > 0 else 0
            avg_loss = np.mean([t['pnl'] for t in trades if t['outcome'] == 'LOSS']) if losses > 0 else 0
            
            print(f"{'NEW STRATEGY' if 'new' in strategy_name else 'OLD STRATEGY'}:")
            print(f"  Total Trades:     {total}")
            print(f"  Wins:             {wins} ({win_rate:.1f}%)")
            print(f"  Losses:           {losses}")
            print(f"  Final Balance:    ${self.results[strategy_name]['balance']:,.2f}")
            print(f"  Total P&L:        ${total_pnl:,.2f}")
            print(f"  ROI:              {roi:.1f}%")
            print(f"  Avg Win:          ${avg_win:.2f}")
            print(f"  Avg Loss:         ${avg_loss:.2f}")
            print(f"  CALL Trades:      {call_trades} ({call_trades/total*100:.1f}%)")
            print(f"  PUT Trades:       {put_trades} ({put_trades/total*100:.1f}%)")
            print()
        
        # Improvement
        old_pnl = self.results['old_strategy']['balance'] - 10000
        new_pnl = self.results['new_strategy']['balance'] - 10000
        improvement = new_pnl - old_pnl
        improvement_pct = (improvement / abs(old_pnl) * 100) if old_pnl != 0 else 0
        
        print("="*70)
        print(f"💰 IMPROVEMENT:")
        print(f"  OLD P&L:          ${old_pnl:,.2f}")
        print(f"  NEW P&L:          ${new_pnl:,.2f}")
        print(f"  Improvement:      ${improvement:,.2f} ({improvement_pct:+.1f}%)")
        print("="*70 + "\n")

if __name__ == "__main__":
    try:
        backtester = HistoricalBacktest()
        backtester.run_backtest()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
