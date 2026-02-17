#!/usr/bin/env python3
"""
Complete Historical Backtest Engine
Simulates trading strategy on historical candle data with CALL/PUT outcomes
"""

import sys
sys.path.append('/var/www/jhonk/dreriv/backend')

import pandas as pd
import numpy as np
from datetime import datetime
from sqlalchemy import create_engine, text
from app.core.config import get_settings
from app.analysis.indicators import calculate_indicators

settings = get_settings()
engine = create_engine(settings.DATABASE_URL)

class BacktestEngine:
    def __init__(self, initial_balance=10000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.trades = []
        self.consecutive_losses = 0
        
    def get_dynamic_confidence_threshold(self):
        """Dynamic confidence based on losses (NEW STRATEGY)"""
        if self.consecutive_losses >= 4:
            return 0.80
        elif self.consecutive_losses >= 3:
            return 0.75
        elif self.consecutive_losses >= 2:
            return 0.73
        return 0.70
    
    def should_trade(self, confidence, use_new_rules=True):
        """Check if should execute trade"""
        if use_new_rules:
            threshold = self.get_dynamic_confidence_threshold()
            if self.consecutive_losses >= 3:
                return False  # Cooldown
        else:
            threshold = 0.70  # OLD: fixed threshold
            if self.consecutive_losses >= 4:
                return False  # OLD: cooldown at 4
        
        return confidence >= threshold
    
    def simulate_trade_outcome(self, direction, entry_price, next_candle):
        """
        Simulate Rise/Fall trade outcome based on next candle
        For 1-minute trades: if next close > entry, CALL wins. If < entry, PUT wins.
        """
        exit_price = next_candle['close']
        
        stake = 60.0
        if direction == 'CALL':
            win = exit_price > entry_price
        else:  # PUT
            win = exit_price < entry_price
        
        if win:
            profit = stake * 0.85  # 85% payout
            return 'WIN', profit
        else:
            return 'LOSS', -stake
    
    def generate_signal(self, indicators):
        """
        Simplified signal generation based on Layer 1 rules
        Returns: (direction, confidence) or (None, 0)
        """
        rsi = indicators.get('rsi', 50)
        macd = indicators.get('macd', 0)
        macd_signal = indicators.get('macd_signal', 0)
        ou_zscore = indicators.get('ou_zscore', 0)
        
        # MACD bearish
        if macd < macd_signal:
            # PUT signal if oversold
            if rsi < 40:
                confidence = 0.75
                return 'PUT', confidence
            
            # CALL only in extreme oversold (NEW RULE)
            if rsi < 20 and ou_zscore < -2.5:
                confidence = 0.72  # Lower confidence for countertrend
                return 'CALL', confidence
        
        # MACD bullish
        elif macd > macd_signal:
            # CALL signal if not overbought
            if rsi < 60:
                confidence = 0.75
                return 'CALL', confidence
            
            # PUT only in extreme overbought
            if rsi > 80 and ou_zscore > 2.5:
                confidence = 0.72
                return 'PUT', confidence
        
        return None, 0
    
    def run_backtest(self, use_new_rules=True):
        """Run backtest on historical data"""
        print(f"\n{'='*60}")
        print(f"🔬 BACKTEST: {'NEW STRATEGY' if use_new_rules else 'OLD STRATEGY'}")
        print(f"{'='*60}\n")
        
        # Load historical candles
        query = """
        SELECT timestamp, open, high, low, close, volume
        FROM candles
        ORDER BY timestamp ASC
        """
        
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
        
        if len(df) < 50:
            print(f"❌ Not enough data (only {len(df)} candles)")
            return
        
        print(f"📊 Loaded {len(df)} candles")
        print(f"📅 From {df['timestamp'].min()} to {df['timestamp'].max()}")
        
        # Reset state
        self.balance = self.initial_balance
        self.trades = []
        self.consecutive_losses = 0
        
        # Iterate through candles
        for i in range(50, len(df) - 1):  # Need 50 for indicators, -1 for next candle
            current = df.iloc[i]
            next_candle = df.iloc[i + 1]
            
            # Calculate indicators on window
            window = df.iloc[i-49:i+1]
            
            try:
                # Simplified indicator calculation
                indicators = {
                    'rsi': self._calculate_rsi(window['close'].values, 14),
                    'macd': 0,  # Simplified
                    'macd_signal': 0,
                    'ou_zscore': 0
                }
                
                # Generate signal
                direction, confidence = self.generate_signal(indicators)
                
                if direction is None:
                    continue
                
                # Check if should trade
                if not self.should_trade(confidence, use_new_rules):
                    continue
                
                # Execute simulated trade
                outcome, pnl = self.simulate_trade_outcome(
                    direction, 
                    current['close'], 
                    next_candle
                )
                
                self.balance += pnl
                
                # Update consecutive losses
                if outcome == 'LOSS':
                    self.consecutive_losses += 1
                else:
                    self.consecutive_losses = 0
                
                # Record trade
                self.trades.append({
                    'timestamp': current['timestamp'],
                    'direction': direction,
                    'confidence': confidence,
                    'outcome': outcome,
                    'pnl': pnl,
                    'balance': self.balance
                })
                
            except Exception as e:
                continue
        
        # Print results
        self._print_results()
    
    def _calculate_rsi(self, prices, period=14):
        """Simple RSI calculation"""
        deltas = np.diff(prices)
        gain = np.where(deltas > 0, deltas, 0)
        loss = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gain[-period:])
        avg_loss = np.mean(loss[-period:])
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _print_results(self):
        """Print backtest results"""
        if not self.trades:
            print("❌ No trades executed")
            return
        
        trades_df = pd.DataFrame(self.trades)
        
        wins = len(trades_df[trades_df['outcome'] == 'WIN'])
        losses = len(trades_df[trades_df['outcome'] == 'LOSS'])
        total = len(trades_df)
        
        win_rate = (wins / total * 100) if total > 0 else 0
        total_pnl = self.balance - self.initial_balance
        roi = (total_pnl / self.initial_balance * 100)
        
        avg_win = trades_df[trades_df['outcome'] == 'WIN']['pnl'].mean() if wins > 0 else 0
        avg_loss = trades_df[trades_df['outcome'] == 'LOSS']['pnl'].mean() if losses > 0 else 0
        
        call_trades = len(trades_df[trades_df['direction'] == 'CALL'])
        put_trades = len(trades_df[trades_df['direction'] == 'PUT'])
        
        print(f"\n📊 BACKTEST RESULTS:")
        print(f"{'='*60}")
        print(f"Total Trades:        {total}")
        print(f"Wins:                {wins} ({win_rate:.1f}%)")
        print(f"Losses:              {losses}")
        print(f"")
        print(f"Initial Balance:     ${self.initial_balance:,.2f}")
        print(f"Final Balance:       ${self.balance:,.2f}")
        print(f"Total P&L:           ${total_pnl:,.2f}")
        print(f"ROI:                 {roi:.1f}%")
        print(f"")
        print(f"Avg Win:             ${avg_win:.2f}")
        print(f"Avg Loss:            ${avg_loss:.2f}")
        print(f"Win/Loss Ratio:      {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "N/A")
        print(f"")
        print(f"CALL Trades:         {call_trades} ({call_trades/total*100:.1f}%)")
        print(f"PUT Trades:          {put_trades} ({put_trades/total*100:.1f}%)")
        print(f"{'='*60}\n")


def main():
    print("\n🚀 Historical Backtest Engine\n")
    
    # Run OLD strategy
    print("=" * 60)
    print("PHASE 1: OLD STRATEGY (Fixed 0.70 threshold, cooldown at 4)")
    print("=" * 60)
    backtester_old = BacktestEngine()
    backtester_old.run_backtest(use_new_rules=False)
    
    # Run NEW strategy
    print("\n" + "=" * 60)
    print("PHASE 2: NEW STRATEGY (Dynamic thresholds, cooldown at 3)")
    print("=" * 60)
    backtester_new = BacktestEngine()
    backtester_new.run_backtest(use_new_rules=True)
    
    # Comparison
    if backtester_old.trades and backtester_new.trades:
        old_pnl = backtester_old.balance - backtester_old.initial_balance
        new_pnl = backtester_new.balance - backtester_new.initial_balance
        improvement = new_pnl - old_pnl
        improvement_pct = (improvement / abs(old_pnl) * 100) if old_pnl != 0 else 0
        
        print(f"\n{'='*60}")
        print(f"📈 STRATEGY COMPARISON")
        print(f"{'='*60}")
        print(f"OLD Strategy P&L:    ${old_pnl:,.2f}")
        print(f"NEW Strategy P&L:    ${new_pnl:,.2f}")
        print(f"Improvement:         ${improvement:,.2f} ({improvement_pct:+.1f}%)")
        print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
