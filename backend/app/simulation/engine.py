"""
Simulation Engine - Isolated Backtesting
Runs strategies on historical data without affecting production
"""

import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy import create_engine, text
from loguru import logger

from app.core.config import get_settings
from app.simulation.strategy import Strategy


class SimulationEngine:
    """
    Backtesting engine that runs strategies on historical candles
    Completely isolated from live trading bot
    """
    
    def __init__(
        self,
        run_id: int,
        strategy: Strategy,
        initial_balance: float = 10000.0,
        config: dict = None
    ):
        """
        Initialize simulation engine
        
        Args:
            run_id: Simulation run ID from database
            strategy: Strategy instance to test
            initial_balance: Starting balance
            config: Additional configuration
        """
        self.run_id = run_id
        self.strategy = strategy
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.config = config or {}
        
        # Trading state
        self.trades = []
        self.current_trade = None
        self.consecutive_losses = 0
        
        # Stats
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        # Database
        settings = get_settings()
        self.engine = create_engine(settings.DATABASE_URL)
    
    def load_historical_candles(
        self,
        start_date: datetime,
        end_date: datetime,
        symbol: str = 'R_100'
    ) -> pd.DataFrame:
        """Load historical candles from database"""
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    open_time, close_time, open, high, low, close, volume,
                    rsi_14, ema_9, ema_21, ema_50,
                    macd, macd_signal, macd_histogram,
                    bollinger_upper, bollinger_middle, bollinger_lower,
                    atr_14, returns, momentum_5, volatility_realized, price_position
                FROM historical_candles
                WHERE symbol = :symbol
                  AND open_time >= :start_date
                  AND open_time <= :end_date
                ORDER BY open_time ASC
            """), {
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date
            })
            
            candles = pd.DataFrame(result.fetchall(), columns=result.keys())
        
        logger.info(f"📊 Loaded {len(candles)} historical candles for simulation")
        return candles
    
    def simulate_trade(
        self,
        direction: str,
        entry_price: float,
        exit_price: float,
        stake: float
    ) -> Dict[str, Any]:
        """
        Simulate binary options trade outcome
        
        Args:
            direction: 'CALL' or 'PUT'
            entry_price: Entry price
            exit_price: Exit price
            stake: Stake amount
        
        Returns:
            {'result': 'WIN'|'LOSS', 'pnl': float}
        """
        
        # Binary options: CALL wins if exit > entry, PUT wins if exit < entry
        if direction == 'CALL':
            won = exit_price > entry_price
        else:  # PUT
            won = exit_price < entry_price
        
        if won:
            # Deriv payout ~ 0.84x stake (84% payout)
            payout = stake * 1.84
            pnl = payout - stake  # Net profit = 0.84x stake
            result = 'WIN'
        else:
            pnl = -stake  # Lose entire stake
            result = 'LOSS'
        
        return {'result': result, 'pnl': pnl}
    
    async def run(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Run simulation on date range
        
        Args:
            start_date: Start date
            end_date: End date
        
        Returns:
            Simulation results summary
        """
        
        logger.info(f"🚀 Starting simulation: {start_date} → {end_date}")
        
        # Update run status
        with self.engine.connect() as conn:
            conn.execute(text("""
                UPDATE simulation_runs
                SET status = 'RUNNING', started_at = :now
                WHERE id = :run_id
            """), {'run_id': self.run_id, 'now': datetime.now(timezone.utc)})
            conn.commit()
        
        try:
            # Load candles
            candles = self.load_historical_candles(start_date, end_date)
            
            if len(candles) < 100:
                raise ValueError(f"Insufficient data: only {len(candles)} candles")
            
            # Run simulation
            logger.info(f"🔬 Simulating {len(candles)} candles...")
            
            for i in range(len(candles) - 1):
                current = candles.iloc[i]
                next_candle = candles.iloc[i + 1]
                history = candles.iloc[:i+1]
                
                # Get strategy decision
                decision = await self.strategy.analyze(current, history)
                
                if decision['signal'] != 'HOLD':
                    # Execute trade
                    stake = decision.get('stake', 60.0)
                    
                    # Extract duration from strategy signal
                    duration_seconds = decision.get('duration', 300)
                    
                    # Calculate exit time based on duration
                    from datetime import timedelta
                    entry_time = current['open_time']
                    exit_time = entry_time + timedelta(seconds=duration_seconds)
                    
                    # Find candle at or after exit_time
                    future_candles = candles[candles['open_time'] >= exit_time]
                    if len(future_candles) > 0:
                        exit_candle = future_candles.iloc[0]
                    else:
                        exit_candle = candles.iloc[-1]
                    
                    outcome = self.simulate_trade(
                        direction=decision['signal'],
                        entry_price=float(current['close']),
                        exit_price=float(exit_candle['close']),
                        stake=stake
                    )
                    
                    # Update balance
                    self.balance += outcome['pnl']
                    
                    # Track stats
                    self.total_trades += 1
                    if outcome['result'] == 'WIN':
                        self.winning_trades += 1
                        self.consecutive_losses = 0
                    else:
                        self.losing_trades += 1
                        self.consecutive_losses += 1
                    
                    # Save trade
                    trade = {
                        'entry_time': current['open_time'],
                        'exit_time': exit_time,
                        'duration_seconds': duration_seconds,
                        'direction': decision['signal'],
                        'entry_price': float(current['close']),
                        'exit_price': float(exit_candle['close']),
                        'stake': stake,
                        'outcome': outcome['result'],
                        'profit_loss': outcome['pnl'],
                        'balance_after': self.balance,
                        'confidence': decision.get('confidence', 0.0),
                        'reasoning': decision.get('reasoning', '')
                    }
                    
                    self.trades.append(trade)
                    self._save_trade(trade)
                
                # Progress
                if (i + 1) % 5000 == 0:
                    progress = ((i + 1) / len(candles)) * 100
                    logger.info(f"  Progress: {progress:.1f}% ({i+1:,}/{len(candles):,} candles)")
            
            # Calculate results
            results = self._calculate_results()
            
            # Save results
            self._save_results(results)
            
            logger.success(f"✅ Simulation complete: {self.total_trades} trades, {results['win_rate']:.1f}% win rate")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Simulation failed: {e}")
            
            # Mark as failed
            with self.engine.connect() as conn:
                conn.execute(text("""
                    UPDATE simulation_runs
                    SET status = 'FAILED', error_message = :error, completed_at = :now
                    WHERE id = :run_id
                """), {
                    'run_id': self.run_id,
                    'error': str(e),
                    'now': datetime.now(timezone.utc)
                })
                conn.commit()
            
            raise
    
    def _save_trade(self, trade: dict):
        """Save simulated trade to database"""
        
        with self.engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO simulation_trades
                (run_id, entry_time, exit_time, direction, entry_price, exit_price,
                 stake, outcome, profit_loss, balance_after, confidence, reasoning, duration_seconds)
                VALUES
                (:run_id, :entry_time, :exit_time, :direction, :entry_price, :exit_price,
                 :stake, :outcome, :profit_loss, :balance_after, :confidence, :reasoning, :duration_seconds)
            """), {
                'run_id': self.run_id,
                **trade
            })
            conn.commit()
    
    def _calculate_results(self) -> Dict[str, Any]:
        """Calculate simulation results"""
        
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        total_pnl = self.balance - self.initial_balance
        
        # Calculate max drawdown
        max_balance = self.initial_balance
        max_drawdown = 0
        
        for trade in self.trades:
            balance = trade['balance_after']
            if balance > max_balance:
                max_balance = balance
            
            drawdown = ((max_balance - balance) / max_balance) * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        return {
            'final_balance': self.balance,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'max_drawdown_pct': max_drawdown
        }
    
    def _save_results(self, results: dict):
        """Save simulation results to database"""
        
        with self.engine.connect() as conn:
            conn.execute(text("""
                UPDATE simulation_runs
                SET 
                    status = 'COMPLETED',
                    final_balance = :final_balance,
                    total_trades = :total_trades,
                    winning_trades = :winning_trades,
                    losing_trades = :losing_trades,
                    win_rate = :win_rate,
                    total_pnl = :total_pnl,
                    max_drawdown_pct = :max_drawdown_pct,
                    completed_at = :now
                WHERE id = :run_id
            """), {
                'run_id': self.run_id,
                'now': datetime.now(timezone.utc),
                **results
            })
            conn.commit()
