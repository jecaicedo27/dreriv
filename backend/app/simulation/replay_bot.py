"""
ReplayBotSimulator - Run bot logic on historical replay data
Replicates FULL live bot pipeline: Layer 1 + Groq Layer 2
Completely isolated from live bot, no DB writes
"""

import asyncio
import pandas as pd
import numpy as np
from typing import Dict, Any, List
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import text


class SimpleCandle:
    """Lightweight candle object for Groq context formatting"""
    def __init__(self, row):
        self.open = float(row['open'])
        self.high = float(row['high'])
        self.low = float(row['low'])
        self.close = float(row['close'])
        self.open_time = row.get('open_time')


class ReplayBotSimulator:
    """
    Runs the same Layer1 + Groq Layer2 pipeline used by the live bot
    on historical candles. Simulates binary options trades and tracks P&L.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.min_confidence = self.config.get('min_confidence', 0.60)
        self.max_confidence = self.config.get('max_confidence', 1.0)
        self.default_stake = self.config.get('stake', 60.0)
        self.payout_rate = self.config.get('payout_rate', 0.95)
        self.trade_duration_candles = self.config.get('duration_candles', 5)
        self.initial_balance = self.config.get('initial_balance', 10000.0)
        self.cooldown_candles = self.config.get('cooldown_candles', 3)
        self.use_groq = self.config.get('use_groq', True)
        self.hurst_min = self.config.get('hurst_min', 0.6)
        self.hurst_max = self.config.get('hurst_max', 0.7)
        self.blocked_hours = set(self.config.get('blocked_hours', []))  # Colombia time hours to skip
        self.engine_name = self.config.get('engine_name', 'original_v1')
        self.dir_cooldown_candles = self.config.get('dir_cooldown_candles', 30)  # 0 to disable
        self.dir_cooldown_losses = self.config.get('dir_cooldown_losses', 3)
        
        # ===== DEFENSIVE FILTERS =====
        # Filter 1: Real-time WR monitoring (early stop)
        self.wr_check_interval = self.config.get('wr_check_interval', 15)  # Check every N trades
        self.wr_pause_threshold = self.config.get('wr_pause_threshold', 0.45)  # Pause if WR < this after 20+ trades
        self.wr_stop_threshold = self.config.get('wr_stop_threshold', 0.40)   # Stop day if WR < this after 30+ trades
        self.wr_pause_candles = self.config.get('wr_pause_candles', 30)  # How long to pause
        self.wr_min_trades_pause = self.config.get('wr_min_trades_pause', 20)  # Min trades before pause check
        self.wr_min_trades_stop = self.config.get('wr_min_trades_stop', 30)   # Min trades before stop check
        self.enable_wr_monitor = self.config.get('enable_wr_monitor', True)
        
        # Filter 2: Global streak protection (any direction)
        self.global_streak_limit = self.config.get('global_streak_limit', 5)  # Consecutive losses any dir → pause
        self.global_streak_pause = self.config.get('global_streak_pause', 60)  # Pause candles after global streak
        self.enable_global_streak = self.config.get('enable_global_streak', True)
        
        # Filter 3: ATR volatility gate
        self.atr_lookback = self.config.get('atr_lookback', 30)  # ATR lookback window
        self.atr_low_mult = self.config.get('atr_low_mult', 0.5)   # Skip if ATR < avg * this
        self.atr_high_mult = self.config.get('atr_high_mult', 2.0)  # Skip if ATR > avg * this  
        self.enable_atr_gate = self.config.get('enable_atr_gate', True)

    def run(self, db: Session, date: str, symbol: str = 'R_100') -> Dict[str, Any]:
        """
        Run bot simulation on all candles for a given date.
        Uses asyncio to handle Groq async calls.
        """
        return asyncio.run(self._run_async(db, date, symbol))

    async def _run_async(self, db: Session, date: str, symbol: str = 'R_100') -> Dict[str, Any]:
        """Async simulation loop with Groq Layer 2 support"""

        # === PERF: Suppress heavy DEBUG logging during simulation ===
        import logging as _logging
        _noisy_loggers = [
            'app.analysis.garch', 'app.analysis.hurst',
            'app.analysis.ornstein_uhlenbeck', 'app.analysis.indicators',
            'app.analysis.reversal_engine',
            'app.analysis.bullish_engine', 'app.analysis.university_engine',
        ]
        _saved_levels = {}
        for _lg_name in _noisy_loggers:
            _lg = _logging.getLogger(_lg_name)
            _saved_levels[_lg_name] = _lg.level
            _lg.setLevel(_logging.WARNING)

        from app.simulation.trading_core import TradingCore  # Import once, not per-candle

        # Load lookback (300 prior candles) + all candles for the date
        # This matches bot_step which uses 300 lookback candles for indicator context
        # Load lookback (300 prior candles) + all candles for the date
        # This matches bot_step which uses 300 lookback candles for indicator context
        result = db.execute(text("""
            WITH date_candles AS (
            SELECT open_time, open, high, low, close,
                   rsi_14, ema_9, ema_21, ema_50,
                   macd, macd_signal, macd_histogram,
                   bollinger_upper, bollinger_middle, bollinger_lower,
                   hurst_exponent, hurst_fast, ou_deviation, regime,
                   returns, momentum_5, volatility_realized, price_position,
                   atr_14, garch_volatility_forecast,
                   adx_14, plus_di, minus_di
            FROM candles
            WHERE symbol = :symbol
              AND DATE(open_time AT TIME ZONE 'America/Bogota') = :date
            ORDER BY open_time ASC
        ),
        lookback_candles AS (
            SELECT open_time, open, high, low, close,
                   rsi_14, ema_9, ema_21, ema_50,
                   macd, macd_signal, macd_histogram,
                   bollinger_upper, bollinger_middle, bollinger_lower,
                   hurst_exponent, hurst_fast, ou_deviation, regime,
                   returns, momentum_5, volatility_realized, price_position,
                   atr_14, garch_volatility_forecast,
                   adx_14, plus_di, minus_di
            FROM candles
            WHERE symbol = :symbol
              AND open_time < (SELECT MIN(open_time) FROM date_candles)
            ORDER BY open_time DESC
            LIMIT 300
        )
            SELECT * FROM (SELECT * FROM lookback_candles ORDER BY open_time ASC) lb
            UNION ALL
            SELECT * FROM date_candles
        """), {"symbol": symbol, "date": date}).fetchall()

        # Count lookback vs date candles
        from datetime import datetime as dt_parser, timedelta
        date_obj = dt_parser.strptime(date, "%Y-%m-%d").date()
        lookback_count = 0
        for row in result:
            col_time = row.open_time - timedelta(hours=5) if row.open_time.tzinfo else row.open_time
            if col_time.date() < date_obj:
                lookback_count += 1
            else:
                break

        date_candle_count = len(result) - lookback_count
        if date_candle_count < 100:
            return {"error": f"Insufficient date candles: {date_candle_count} (need 100+)"}

        # Convert to DataFrame
        columns = [
            'open_time', 'open', 'high', 'low', 'close',
            'rsi_14', 'ema_9', 'ema_21', 'ema_50',
            'macd', 'macd_signal', 'macd_histogram',
            'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
            'hurst_exponent', 'hurst_fast', 'ou_deviation', 'regime',
            'returns', 'momentum_5', 'volatility_realized', 'price_position',
            'atr_14', 'garch_volatility_forecast',
            'adx_14', 'plus_di', 'minus_di'
        ]
        df = pd.DataFrame([dict(zip(columns, row)) for row in result])

        # Convert numerics to float
        numeric_cols = [c for c in columns if c not in ('open_time', 'regime')]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)
            
        # Add required missing indicators in one batch to prevent safe_analyze from recalculating per-candle
        from app.analysis.indicators import TechnicalIndicators
        df = TechnicalIndicators.calculate_all(df)

        # Initialize analysis engine via registry
        from app.analysis.engine_registry import get_engine
        engine = get_engine(self.engine_name)

        # Direction-aware consecutive loss tracking (matches frontend exactly)
        consec_losses_same_dir = 0
        last_loss_dir = None
        dir_cooldown_until = 0

        # ===== DEFENSIVE STATE =====
        # Filter 1: WR monitor
        day_wins = 0
        day_losses = 0
        day_stopped = False  # True if WR monitor or PnL stop halted the day
        wr_pause_until = 0   # Candle index to resume after WR pause
        
        # Filter 2: Global streak protection
        global_consec_losses = 0
        global_streak_pause_until = 0
        

        # Run simulation
        balance = self.initial_balance
        trades = []
        equity_curve = [{"index": 0, "balance": balance}]
        cooldown_until = 0

        total_candles = len(df)
        logger.info(f"🤖 Bot simulation: {date_candle_count} date candles + {lookback_count} lookback (Groq={'ON' if self.use_groq else 'OFF'})")

        # Iterate only over date candles (after lookback)
        for i in range(lookback_count, total_candles - self.trade_duration_candles):
            # ===== FILTER 1: WR MONITOR — day stopped =====
            if day_stopped:
                break
            
            # Skip if in post-trade cooldown
            if i < cooldown_until:
                continue

            # Skip if in direction-aware cooldown (3 consecutive losses in same direction → 30 candle pause)
            if i < dir_cooldown_until:
                continue
            
            # ===== FILTER 1: WR MONITOR — pause check =====
            if self.enable_wr_monitor and i < wr_pause_until:
                continue
            
            # ===== FILTER 2: GLOBAL STREAK — pause check =====
            if self.enable_global_streak and i < global_streak_pause_until:
                continue

            try:
                # ===== HOUR FILTER: skip blocked hours (Colombia time = UTC-5) =====
                if self.blocked_hours:
                    candle_time = df.iloc[i]['open_time']
                    col_hour = (candle_time - timedelta(hours=5)).hour if hasattr(candle_time, 'hour') else -1
                    if col_hour in self.blocked_hours:
                        continue
                
                # ===== FILTER 3: ATR VOLATILITY GATE =====
                if self.enable_atr_gate and i >= self.atr_lookback:
                    recent_atrs = df.iloc[i - self.atr_lookback:i]['atr_14'].values
                    avg_atr = float(recent_atrs.mean()) if len(recent_atrs) > 0 else 0
                    current_atr = float(df.iloc[i]['atr_14']) if df.iloc[i]['atr_14'] else 0
                    if avg_atr > 0 and current_atr > 0:
                        atr_ratio = current_atr / avg_atr
                        if atr_ratio < self.atr_low_mult:
                            continue  # Market too quiet, no edge

                # ===== THE SINGLE BRAIN — TradingCore =====
                candle_window = df.iloc[max(0, i - 249):i + 1]  # View, no copy
                result = await TradingCore.analyze_async(
                    engine=engine,
                    df=candle_window,
                    symbol=symbol,
                    use_groq=self.use_groq,
                    ai_provider=self.config.get('ai_provider', 'groq'),
                    hurst_min=self.hurst_min,
                    hurst_max=self.hurst_max,
                )

                final_signal = result["action"]
                confidence = result["confidence"]

                # ===== EXECUTE TRADE =====
                if final_signal in ('CALL', 'PUT') and confidence >= self.min_confidence and confidence < self.max_confidence:
                    entry_candle = df.iloc[i]
                    exit_idx = i + self.trade_duration_candles
                    exit_candle = df.iloc[exit_idx]

                    entry_price = float(entry_candle['close'])
                    exit_price = float(exit_candle['close'])

                    # Determine outcome
                    if final_signal == 'CALL':
                        won = exit_price > entry_price
                    else:
                        won = exit_price < entry_price

                    # === Kelly stake — EXACT same formula as frontend ===
                    conf = max(confidence, 0.60)
                    stake_pct = 0.013 + (min(conf, 0.95) - 0.60) * ((0.015 - 0.013) / (0.95 - 0.60))
                    stake_pct = max(0.013, min(0.015, stake_pct))
                    stake = max(0.35, balance * stake_pct)

                    # Payout = 0.95 (matches frontend)
                    pnl = stake * 0.95 if won else -stake
                    balance += pnl

                    # === Direction-aware consecutive loss tracking (matches frontend) ===
                    if not won:
                        day_losses += 1
                        global_consec_losses += 1
                        if last_loss_dir == final_signal:
                            consec_losses_same_dir += 1
                        else:
                            consec_losses_same_dir = 1
                            last_loss_dir = final_signal
                        # Trigger configurable direction cooldown
                        if self.dir_cooldown_candles > 0 and consec_losses_same_dir >= self.dir_cooldown_losses:
                            dir_cooldown_until = exit_idx + self.dir_cooldown_candles
                            consec_losses_same_dir = 0
                            logger.info(f"⏸️ Direction cooldown: {self.dir_cooldown_losses} {final_signal} losses → pause until candle {dir_cooldown_until}")
                        
                        # ===== FILTER 2: GLOBAL STREAK CHECK =====
                        if self.enable_global_streak and global_consec_losses >= self.global_streak_limit:
                            global_streak_pause_until = exit_idx + self.global_streak_pause
                            global_consec_losses = 0
                            logger.info(f"🛑 Global streak: {self.global_streak_limit} consecutive losses → pause {self.global_streak_pause} candles")
                    else:
                        day_wins += 1
                        # Win resets all consecutive counters
                        consec_losses_same_dir = 0
                        last_loss_dir = None
                        global_consec_losses = 0
                    
                    # ===== FILTER 1: WR MONITOR CHECK =====
                    total_day_trades = day_wins + day_losses
                    if self.enable_wr_monitor and total_day_trades > 0:
                        current_wr = day_wins / total_day_trades
                        # Hard stop: WR too low after enough trades
                        if total_day_trades >= self.wr_min_trades_stop and current_wr < self.wr_stop_threshold:
                            day_stopped = True
                            logger.info(f"🚫 WR Monitor STOP: {current_wr:.1%} WR after {total_day_trades} trades — stopping day")
                        # Soft pause: WR concerning
                        elif total_day_trades >= self.wr_min_trades_pause and current_wr < self.wr_pause_threshold:
                            wr_pause_until = exit_idx + self.wr_pause_candles
                            logger.info(f"⏸️ WR Monitor PAUSE: {current_wr:.1%} WR after {total_day_trades} trades — pause {self.wr_pause_candles} candles")
                    

                    trade = {
                        "index": i,
                        "candle_index": i - lookback_count,
                        "exit_candle_index": exit_idx - lookback_count,
                        "time": str(entry_candle['open_time'] - timedelta(hours=5)),
                        "timestamp": int(entry_candle['open_time'].timestamp()),
                        "direction": final_signal,
                        "stake": round(stake, 2),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "exit_index": exit_idx,
                        "result": "WIN" if won else "LOSS",
                        "pnl": round(pnl, 2),
                        "balance_after": round(balance, 2),
                        "confidence": round(confidence, 3),
                        "groq_used": result["groq_used"],
                        "l1_signal": result["l1_signal"],
                        "l1_confidence": result["l1_confidence"],
                        "reasoning": result["reasoning"][:200],
                        "groq_reasoning": result["groq_reasoning"][:300] if result["groq_used"] else "",
                        # Technical indicators at entry
                        "hurst": result.get("hurst", 0),
                        "rsi_14": result.get("rsi_14", 0),
                        "ema_9": result.get("ema_9", 0),
                        "ema_21": result.get("ema_21", 0),
                        "macd_histogram": result.get("macd_histogram", 0),
                        "bb_width": result.get("bb_width", 0),
                    }
                    trades.append(trade)
                    equity_curve.append({"index": i, "balance": round(balance, 2)})

                    # Set post-trade cooldown (exit_index + 3, same as frontend BOT_COOLDOWN)
                    cooldown_until = exit_idx + self.cooldown_candles

            except Exception as e:
                continue

        # Calculate summary
        total_trades = len(trades)
        wins = sum(1 for t in trades if t['result'] == 'WIN')
        losses = total_trades - wins
        win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0
        total_pnl = round(balance - self.initial_balance, 2)

        # Max drawdown
        max_balance = self.initial_balance
        max_drawdown = 0
        for t in trades:
            if t['balance_after'] > max_balance:
                max_balance = t['balance_after']
            dd = ((max_balance - t['balance_after']) / max_balance) * 100
            if dd > max_drawdown:
                max_drawdown = dd

        groq_trades = sum(1 for t in trades if t.get('groq_used'))

        summary = {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "final_balance": round(balance, 2),
            "initial_balance": self.initial_balance,
            "max_drawdown_pct": round(max_drawdown, 1),
            "payout_rate": self.payout_rate,
            "stake": self.default_stake,
            "date": date,
            "lookback_count": lookback_count,
            "groq_enabled": self.use_groq,
            "groq_calls": groq_trades,
            "groq_overrides": 0
        }

        logger.success(
            f"✅ Bot sim complete: {total_trades} trades, {win_rate}% win, PnL=${total_pnl} "
            f"(Groq: {groq_trades} trades)"
        )

        # === PERF: Restore log levels ===
        for _lg_name, _lvl in _saved_levels.items():
            _logging.getLogger(_lg_name).setLevel(_lvl)

        return {
            "trades": trades,
            "summary": summary,
            "equity_curve": equity_curve
        }
