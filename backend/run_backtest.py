#!/usr/bin/env python3
"""
Complete Historical Backtest - Using Pre-Calculated Indicators
Simulates OLD vs NEW strategy on enriched historical data
"""

import sys
sys.path.insert(0, '/app')

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from app.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)

class StrategyBacktest:
    def __init__(self, initial_balance=10000, stake=60):
        self.initial_balance = initial_balance
        self.stake = stake
        
    def get_dynamic_confidence_threshold(self, consecutive_losses):
        """Dynamic confidence threshold (NEW STRATEGY)"""
        if consecutive_losses >= 4:
            return 0.80
        elif consecutive_losses >= 3:
            return 0.75
        elif consecutive_losses >= 2:
            return 0.73
        return 0.70
    
    def should_trade(self, confidence, consecutive_losses, use_new_rules=True):
        """Check if should execute trade"""
        if use_new_rules:
            # NEW: Cooldown at 3 losses
            if consecutive_losses >= 3:
                return False, "cooldown"
            threshold = self.get_dynamic_confidence_threshold(consecutive_losses)
        else:
            # OLD: Cooldown at 4 losses, fixed threshold
            if consecutive_losses >= 4:
                return False, "cooldown"
            threshold = 0.70
        
        if confidence < threshold:
            return False, f"low_confidence ({confidence:.2f} < {threshold:.2f})"
        
        return True, "approved"
    
    def generate_signal(self, row, use_new_rules=True):
        """
        Generate trading signal from indicators
        Returns: (direction, confidence)
        """
        rsi = row['rsi_14']
        macd = row['macd']
        macd_signal = row['macd_signal']
        
        # Skip if indicators missing
        if pd.isna(rsi) or pd.isna(macd) or pd.isna(macd_signal):
            return None, 0
        
        direction = None
        confidence = 0
        
        # MACD bearish
        if macd < macd_signal:
            # PUT signal if oversold
            if rsi < 40:
                direction = 'PUT'
                confidence = 0.78
            # CALL only in extreme oversold (NEW RULE)
            elif use_new_rules and rsi < 20:
                direction = 'CALL'
                confidence = 0.72  # Lower for countertrend
            # OLD: Allow CALL easier
            elif not use_new_rules and rsi < 30:
                direction = 'CALL'
                confidence = 0.73
        
        # MACD bullish
        elif macd > macd_signal:
            # CALL signal if not overbought
            if rsi < 60:
                direction = 'CALL'
                confidence = 0.78
            # PUT only in extreme overbought
            elif rsi > 80:
                direction = 'PUT'
                confidence = 0.72
        
        return direction, confidence
    
    def simulate_trade_outcome(self, direction, entry_price, exit_price):
        """Simulate Rise/Fall trade outcome"""
        if direction == 'CALL':
            win = exit_price > entry_price
        else:  # PUT
            win = exit_price < entry_price
        
        if win:
            profit = self.stake * 0.85  # 85% payout
            return 'WIN', profit
        else:
            return 'LOSS', -self.stake
    
    def run_backtest(self, df, use_new_rules=True, strategy_name=""):
        """Run backtest on historical data"""
        balance = self.initial_balance
        trades = []
        consecutive_losses = 0
        
        total_cooldowns = 0
        total_blocked_low_conf = 0
        
        for i in range(len(df) - 1):
            row = df.iloc[i]
            next_row = df.iloc[i + 1]
            
            # Generate signal
            direction, confidence = self.generate_signal(row, use_new_rules)
            
            if direction is None:
                continue
            
            # Check if should trade
            should_execute, reason = self.should_trade(confidence, consecutive_losses, use_new_rules)
            
            if not should_execute:
                if reason == "cooldown":
                    total_cooldowns += 1
                else:
                    total_blocked_low_conf += 1
                continue
            
            # Execute trade
            entry_price = row['close']
            exit_price = next_row['close']
            
            outcome, pnl = self.simulate_trade_outcome(direction, entry_price, exit_price)
            balance += pnl
            
            # Update consecutive losses
            if outcome == 'LOSS':
                consecutive_losses += 1
            else:
                consecutive_losses = 0
            
            trades.append({
                'time': row['open_time'],
                'direction': direction,
                'confidence': confidence,
                'entry': entry_price,
                'exit': exit_price,
                'outcome': outcome,
                'pnl': pnl,
                'balance': balance,
                'consecutive_losses': consecutive_losses
            })
        
        return {
            'trades': trades,
            'final_balance': balance,
            'cooldowns': total_cooldowns,
            'blocked_low_conf': total_blocked_low_conf
        }
    
    def print_results(self, results, strategy_name):
        """Print backtest results"""
        trades = results['trades']
        
        if not trades:
            print(f"\n{strategy_name}: ❌ No trades executed")
            return
        
        trades_df = pd.DataFrame(trades)
        
        wins = len(trades_df[trades_df['outcome'] == 'WIN'])
        losses = len(trades_df[trades_df['outcome'] == 'LOSS'])
        total = len(trades_df)
        win_rate = (wins / total * 100) if total > 0 else 0
        
        total_pnl = results['final_balance'] - self.initial_balance
        roi = (total_pnl / self.initial_balance * 100)
        
        call_trades = len(trades_df[trades_df['direction'] == 'CALL'])
        put_trades = len(trades_df[trades_df['direction'] == 'PUT'])
        
        avg_win = trades_df[trades_df['outcome'] == 'WIN']['pnl'].mean() if wins > 0 else 0
        avg_loss = trades_df[trades_df['outcome'] == 'LOSS']['pnl'].mean() if losses > 0 else 0
        
        max_consecutive_losses = trades_df['consecutive_losses'].max()
        
        print(f"\n{'='*70}")
        print(f"{strategy_name}")
        print(f"{'='*70}")
        print(f"Total Trades:        {total}")
        print(f"  Blocked (cooldown): {results['cooldowns']}")
        print(f"  Blocked (low conf): {results['blocked_low_conf']}")
        print(f"\nPerformance:")
        print(f"  Wins:               {wins} ({win_rate:.1f}%)")
        print(f"  Losses:             {losses}")
        print(f"  Max Consec. Losses: {max_consecutive_losses}")
        print(f"\nFinancials:")
        print(f"  Initial Balance:    ${self.initial_balance:,.2f}")
        print(f"  Final Balance:      ${results['final_balance']:,.2f}")
        print(f"  Total P&L:          ${total_pnl:,.2f}")
        print(f"  ROI:                {roi:.1f}%")
        print(f"\nTrade Quality:")
        print(f"  Avg Win:            ${avg_win:.2f}")
        print(f"  Avg Loss:           ${avg_loss:.2f}")
        print(f"  Win/Loss Ratio:     {abs(avg_win/avg_loss):.2f}x" if avg_loss != 0 else "N/A")
        print(f"\nDirectional Balance:")
        print(f"  CALL Trades:        {call_trades} ({call_trades/total*100:.1f}%)")
        print(f"  PUT Trades:         {put_trades} ({put_trades/total*100:.1f}%)")
        print(f"{'='*70}\n")
        
        return {
            'total_trades': total,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'roi': roi,
            'max_consecutive_losses': max_consecutive_losses
        }

def main():
    print("\n" + "="*70)
    print("🔬 HISTORICAL BACKTEST - Strategy Comparison")
    print("="*70)
    
    # Load enriched candles
    print("\n📊 Loading enriched candle data...")
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT 
                open_time,
                close,
                rsi_14,
                macd,
                macd_signal,
                ema_9,
                ema_21
            FROM candles
            WHERE rsi_14 IS NOT NULL
            ORDER BY open_time ASC
        """), conn)
    
    print(f"✅ Loaded {len(df)} candles with indicators")
    print(f"📅 Period: {df['open_time'].min()} → {df['open_time'].max()}")
    
    # Initialize backtester
    backtester = StrategyBacktest(initial_balance=10000, stake=60)
    
    # Run OLD strategy
    print("\n⏳ Running OLD strategy backtest...")
    old_results = backtester.run_backtest(df, use_new_rules=False)
    old_summary = backtester.print_results(old_results, "📊 OLD STRATEGY (Fixed 0.70, Cooldown at 4)")
    
    # Run NEW strategy
    print("\n⏳ Running NEW strategy backtest...")
    new_results = backtester.run_backtest(df, use_new_rules=True)
    new_summary = backtester.print_results(new_results, "🚀 NEW STRATEGY (Dynamic Thresholds, Cooldown at 3)")
    
    # Comparison
    if old_summary and new_summary:
        improvement_pnl = new_summary['total_pnl'] - old_summary['total_pnl']
        improvement_pct = (improvement_pnl / abs(old_summary['total_pnl']) * 100) if old_summary['total_pnl'] != 0 else 0
        
        wr_improvement = new_summary['win_rate'] - old_summary['win_rate']
        
        print("="*70)
        print("📈 STRATEGY COMPARISON SUMMARY")
        print("="*70)
        print(f"\nWin Rate:")
        print(f"  OLD: {old_summary['win_rate']:.1f}%")
        print(f"  NEW: {new_summary['win_rate']:.1f}%")
        print(f"  Improvement: {wr_improvement:+.1f} percentage points")
        print(f"\nP&L:")
        print(f"  OLD: ${old_summary['total_pnl']:,.2f}")
        print(f"  NEW: ${new_summary['total_pnl']:,.2f}")
        print(f"  Improvement: ${improvement_pnl:,.2f} ({improvement_pct:+.1f}%)")
        print(f"\nRisk Control:")
        print(f"  OLD Max Consecutive Losses: {old_summary['max_consecutive_losses']}")
        print(f"  NEW Max Consecutive Losses: {new_summary['max_consecutive_losses']}")
        print(f"  Reduction: {old_summary['max_consecutive_losses'] - new_summary['max_consecutive_losses']} losses")
        print(f"\nTrade Volume:")
        print(f"  OLD Total Trades: {old_summary['total_trades']}")
        print(f"  NEW Total Trades: {new_summary['total_trades']}")
        print(f"  Difference: {new_summary['total_trades'] - old_summary['total_trades']} trades")
        print("="*70)
        
        # Verdict
        print("\n🎯 VERDICT:")
        if improvement_pnl > 0 and wr_improvement > 0:
            print("✅ NEW strategy outperforms OLD strategy")
            print(f"   Higher win rate (+{wr_improvement:.1f}%)")
            print(f"   Better P&L (+${improvement_pnl:.2f})")
            print(f"   Improved risk control (max losses: {old_summary['max_consecutive_losses']} → {new_summary['max_consecutive_losses']})")
        else:
            print("⚠️ Results inconclusive - may need more data or parameter tuning")
        print("="*70 + "\n")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
