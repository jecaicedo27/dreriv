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
        self.default_stake = self.config.get('stake', 60.0)
        self.payout_rate = self.config.get('payout_rate', 0.84)
        self.trade_duration_candles = self.config.get('duration_candles', 5)
        self.initial_balance = self.config.get('initial_balance', 10000.0)
        self.cooldown_candles = self.config.get('cooldown_candles', 3)
        self.use_groq = self.config.get('use_groq', True)

    def run(self, db: Session, date: str, symbol: str = 'R_100') -> Dict[str, Any]:
        """
        Run bot simulation on all candles for a given date.
        Uses asyncio to handle Groq async calls.
        """
        return asyncio.run(self._run_async(db, date, symbol))

    async def _run_async(self, db: Session, date: str, symbol: str = 'R_100') -> Dict[str, Any]:
        """Async simulation loop with Groq Layer 2 support"""

        # Load all candles for the date
        result = db.execute(text("""
            SELECT open_time, open, high, low, close,
                   rsi_14, ema_9, ema_21, ema_50,
                   macd, macd_signal, macd_histogram,
                   bollinger_upper, bollinger_middle, bollinger_lower,
                   hurst_exponent, ou_deviation, regime,
                   returns, momentum_5, volatility_realized, price_position,
                   atr_14
            FROM candles
            WHERE symbol = :symbol
              AND DATE(open_time AT TIME ZONE 'America/Bogota') = :date
            ORDER BY open_time ASC
        """), {"symbol": symbol, "date": date}).fetchall()

        if len(result) < 100:
            return {"error": f"Insufficient data: {len(result)} candles (need 100+)"}

        # Convert to DataFrame
        columns = [
            'open_time', 'open', 'high', 'low', 'close',
            'rsi_14', 'ema_9', 'ema_21', 'ema_50',
            'macd', 'macd_signal', 'macd_histogram',
            'bollinger_upper', 'bollinger_middle', 'bollinger_lower',
            'hurst_exponent', 'ou_deviation', 'regime',
            'returns', 'momentum_5', 'volatility_realized', 'price_position',
            'atr_14'
        ]
        df = pd.DataFrame([dict(zip(columns, row)) for row in result])

        # Convert numerics to float
        numeric_cols = [c for c in columns if c not in ('open_time', 'regime')]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)

        # Initialize engines
        from app.analysis.layer1_engine import Layer1SignalEngine
        engine = Layer1SignalEngine()

        # Initialize Groq Layer 2 if enabled
        layer2 = None
        if self.use_groq:
            try:
                from app.analysis.layer2_groq import get_layer2_engine
                layer2 = get_layer2_engine()
                logger.info("🧠 Groq Layer 2 enabled for simulation")
            except Exception as e:
                logger.warning(f"⚠️ Groq Layer 2 unavailable: {e} — falling back to L1 only")
                layer2 = None

        # Run simulation
        balance = self.initial_balance
        trades = []
        equity_curve = [{"index": 0, "balance": balance}]
        cooldown_until = 0

        total_candles = len(df)
        logger.info(f"🤖 Bot simulation: {total_candles} candles for {date} (Groq={'ON' if layer2 else 'OFF'})")

        groq_calls = 0
        groq_overrides = 0

        for i in range(50, total_candles - self.trade_duration_candles):
            # Skip if in cooldown
            if i < cooldown_until:
                continue

            # Get rolling window (last 250 candles or available)
            start_idx = max(0, i - 250)
            window = df.iloc[start_idx:i + 1].copy()

            try:
                # ===== LAYER 1: Statistical Analysis =====
                signal = engine.analyze(window, symbol)

                l1_signal = signal.get('final_signal', 'HOLD')
                l1_confidence = signal.get('final_confidence', 0.0)
                l1_reasoning = signal.get('reasoning', '')

                # ===== LAYER 2: Groq AI Meta-Analysis =====
                groq_used = False
                groq_reasoning_text = ""

                if layer2:
                    hurst_value = signal.get('hurst_signal', {}).get('hurst', 0.5)

                    # Same trigger logic as live bot
                    should_call_groq = (
                        l1_signal in ['CALL', 'PUT'] or
                        hurst_value >= 0.55
                    )

                    if should_call_groq:
                        try:
                            # Build candle objects for Groq context (last 25)
                            candle_start = max(0, i - 24)
                            candles_for_groq = [
                                SimpleCandle(df.iloc[j])
                                for j in range(candle_start, i + 1)
                            ]

                            # Call Groq (NO db writes — pass db=None)
                            groq_result = await layer2.analyze(
                                layer1_signal=signal,
                                candles=candles_for_groq,
                                db=None  # No DB writes in simulation
                            )

                            groq_calls += 1
                            groq_used = True

                            # Groq is the FINAL decision maker
                            final_signal = groq_result.get('decision', groq_result.get('final_signal', 'HOLD'))
                            confidence = groq_result.get('confidence', groq_result.get('final_confidence', 0.0))

                            # Extract reasoning
                            reasoning_chain = groq_result.get('reasoning_chain', {})
                            if isinstance(reasoning_chain, dict):
                                groq_reasoning_text = reasoning_chain.get(
                                    'step6_final_decision_rationale',
                                    str(reasoning_chain)[:200]
                                )
                            else:
                                groq_reasoning_text = str(reasoning_chain)[:200]

                            if final_signal != l1_signal:
                                groq_overrides += 1
                                logger.debug(f"🔄 Groq override @ {i}: L1={l1_signal} → Groq={final_signal}")

                        except Exception as e:
                            logger.warning(f"⚠️ Groq error @ candle {i}: {e}")
                            # Fallback to Layer 1
                            final_signal = l1_signal
                            confidence = l1_confidence
                            groq_used = False
                    else:
                        # Market not qualifying for Groq
                        final_signal = l1_signal
                        confidence = l1_confidence
                else:
                    # Groq disabled — pure Layer 1
                    final_signal = l1_signal
                    confidence = l1_confidence

                # ===== EXECUTE TRADE =====
                if final_signal in ('CALL', 'PUT') and confidence >= self.min_confidence:
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

                    pnl = self.default_stake * self.payout_rate if won else -self.default_stake
                    balance += pnl

                    trade = {
                        "index": i,
                        "time": str(entry_candle['open_time']),
                        "timestamp": int(entry_candle['open_time'].timestamp()),
                        "direction": final_signal,
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "exit_index": exit_idx,
                        "result": "WIN" if won else "LOSS",
                        "pnl": round(pnl, 2),
                        "balance_after": round(balance, 2),
                        "confidence": round(confidence, 3),
                        "groq_used": groq_used,
                        "l1_signal": l1_signal,
                        "l1_confidence": round(l1_confidence, 3),
                        "reasoning": groq_reasoning_text[:200] if groq_used else l1_reasoning[:200],
                        "groq_reasoning": groq_reasoning_text[:300] if groq_used else ""
                    }
                    trades.append(trade)
                    equity_curve.append({"index": i, "balance": round(balance, 2)})

                    # Set cooldown
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
            "groq_enabled": layer2 is not None,
            "groq_calls": groq_calls,
            "groq_overrides": groq_overrides
        }

        logger.success(
            f"✅ Bot sim complete: {total_trades} trades, {win_rate}% win, PnL=${total_pnl} "
            f"(Groq: {groq_calls} calls, {groq_overrides} overrides)"
        )

        return {
            "trades": trades,
            "summary": summary,
            "equity_curve": equity_curve
        }
