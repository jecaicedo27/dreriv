"""
Accumulator Trading Bot for Boom 1000 Index
============================================

Completely separate bot from the Rise/Fall bot (bot.py).
Trades ACCU (Accumulator) contracts on BOOM1000.

Strategy:
- Subscribes to tick stream for BOOM1000
- Analyzes each tick for entry conditions (low volatility, no recent spikes)
- Buys ACCU contracts with adaptive growth rate
- Monitors open contract via proposal_open_contract subscription
- Auto-closes on take_profit or barrier hit

Usage:
    python -m app.accu_bot
"""
import asyncio
import os
from datetime import datetime, timedelta
from loguru import logger

from app.core.accu_config import AccuConfig
from app.core.database import SessionLocal
from app.core.config import get_settings
from app.services.deriv_client import DerivWebSocketClient
from app.services.telegram_notifier import telegram_notifier
from app.analysis.accu_analysis import AccuAnalysisEngine
from app.api.accu_status import update_accu_state, accu_bot_state, log_accu_trade, push_accu_candle, set_candle_cache, push_accu_tick
from app.services.accu_db import save_accu_trade

settings = get_settings()


class AccumulatorBot:
    """
    Autonomous Accumulator trading bot for Boom 1000 Index.
    
    Lifecycle:
    1. Connect → Authorize → Subscribe to BOOM1000 ticks
    2. Collect ticks → Analyze → Wait for ENTER signal
    3. Buy ACCU contract → Monitor → Close/Profit
    4. Cooldown if loss → Repeat
    """

    def __init__(self, config: AccuConfig = None):
        self.config = config or AccuConfig()
        self.db = SessionLocal()

        # Own WebSocket client with ACCU-specific app_id (separate from Rise/Fall bot)
        accu_app_id = int(os.environ.get('DERIV_ACCU_APP_ID', '127388'))
        self.accu_api_token = os.environ.get('DERIV_ACCU_API_TOKEN', '')
        self.ws_client = DerivWebSocketClient(app_id=accu_app_id)
        self.analysis_engine = AccuAnalysisEngine(self.config)

        # State
        self.is_running = False
        self.balance = 0.0

        # Contract tracking
        self.open_contract_id = None
        self.open_contract_buy_price = 0.0
        self.open_contract_start_time = None
        self.open_contract_current_pnl = 0.0

        # Risk state
        self.consecutive_losses = 0
        self.cooldown_until = None
        self.total_trades = 0
        self.total_wins = 0

        # Entry lock to prevent concurrent buy attempts
        self._entry_lock = asyncio.Lock()
        self._is_entering = False
        self.total_losses = 0
        self.session_pnl = 0.0

    async def start(self):
        """Start the Accumulator bot"""
        prefix = self.config.LOG_PREFIX
        logger.info(f"{prefix} Starting Accumulator Bot for {self.config.SYMBOL}...")

        # Connect
        logger.info(f"{prefix} 🔌 Connecting to Deriv...")
        if not await self.ws_client.connect():
            logger.critical(f"{prefix} ❌ Failed to connect")
            return

        # Start message handler
        self.ws_client.running = True
        asyncio.create_task(self.ws_client.message_handler_loop())

        # Authorize with ACCU-specific token
        auth_data = await self.ws_client.authorize(api_token=self.accu_api_token)
        if not auth_data:
            logger.critical(f"{prefix} ❌ Failed to authorize")
            return

        self.balance = float(auth_data.get('balance', 0))
        account_type = "DEMO" if auth_data.get('is_virtual') else "REAL"
        logger.info(f"{prefix} 💰 Balance: ${self.balance:.2f} ({account_type})")

        # Set callbacks
        self.ws_client.set_tick_callback(self._on_tick)
        self.ws_client.set_balance_callback(self._on_balance_update)
        self.ws_client.set_contract_callback(self._on_contract_update)

        # Check for existing open ACCU contracts (orphan detection)
        try:
            portfolio = await self.ws_client.get_portfolio()
            accu_contracts = [c for c in portfolio if c.get('contract_type') == 'ACCU' 
                             and c.get('symbol') == self.config.SYMBOL]
            if accu_contracts:
                orphan = accu_contracts[0]
                self.open_contract_id = orphan.get('contract_id')
                self.open_contract_buy_price = float(orphan.get('buy_price', 0))
                self.open_contract_start_time = datetime.now()
                logger.warning(f"{prefix} 🔍 Found orphan ACCU contract: {self.open_contract_id} — adopting it")
                # Subscribe to updates for this contract
                await self.ws_client.send_request({
                    "proposal_open_contract": 1,
                    "contract_id": self.open_contract_id,
                    "subscribe": 1
                })
            else:
                logger.info(f"{prefix} ✅ No orphan ACCU contracts found")
        except Exception as e:
            logger.warning(f"{prefix} ⚠️ Portfolio check failed: {e}")

        # Subscribe to balance
        await self.ws_client.subscribe_balance()

        # Subscribe to BOOM1000 ticks
        logger.info(f"{prefix} 📊 Subscribing to {self.config.SYMBOL} ticks...")
        sub_id = await self.ws_client.subscribe_to_ticks(self.config.SYMBOL)
        if not sub_id:
            logger.critical(f"{prefix} ❌ Failed to subscribe to {self.config.SYMBOL}")
            return

        # Fetch proper 1-minute historical candles (one-shot, NOT from subscription)
        logger.info(f"{prefix} 🕯️ Fetching 1m historical candles for {self.config.SYMBOL}...")
        hist_request = {
            "ticks_history": self.config.SYMBOL,
            "adjust_start_time": 1,
            "count": 500,
            "end": "latest",
            "granularity": 60,
            "start": 1,
            "style": "candles",
        }
        hist_response = await self.ws_client.send_request(hist_request)
        if hist_response and "candles" in hist_response:
            historical = hist_response["candles"]
            for c in historical:
                push_accu_candle({
                    "time": int(c.get("epoch", 0)),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                })
            logger.success(f"{prefix} 📊 Loaded {len(historical)} actual 1m candles")
        else:
            logger.warning(f"{prefix} ⚠️ No 1m historical candle data")

        # Pre-fetch 5m, 1h, 1D candles so timeframe switching is instant
        for granularity, label, count in [(300, '5m', 500), (3600, '1h', 500), (86400, '1D', 365)]:
            logger.info(f"{prefix} 🕯️ Pre-fetching {label} candles...")
            try:
                tf_request = {
                    "ticks_history": self.config.SYMBOL,
                    "adjust_start_time": 1,
                    "count": count,
                    "end": "latest",
                    "granularity": granularity,
                    "start": 1,
                    "style": "candles",
                }
                tf_response = await self.ws_client.send_request(tf_request)
                if tf_response and "candles" in tf_response:
                    candles = [{
                        "time": int(c.get("epoch", 0)),
                        "open": float(c.get("open", 0)),
                        "high": float(c.get("high", 0)),
                        "low": float(c.get("low", 0)),
                        "close": float(c.get("close", 0)),
                    } for c in tf_response["candles"]]
                    set_candle_cache(granularity, candles)
                    logger.success(f"{prefix} 📊 Pre-loaded {len(candles)} {label} candles")
            except Exception as e:
                logger.warning(f"{prefix} ⚠️ Failed to pre-fetch {label}: {e}")

        # Subscribe to BOOM1000 candles for LIVE streaming only (ignore subscription history)
        logger.info(f"{prefix} 🕯️ Subscribing to {self.config.SYMBOL} live candle stream...")
        self.ws_client.set_candle_callback(self._on_candle)
        await self.ws_client.subscribe_to_candles(self.config.SYMBOL, granularity=60)

        # Notify startup
        await telegram_notifier.send_message(
            f"🎰 **Accumulator Bot Started**\n"
            f"📊 Symbol: {self.config.SYMBOL}\n"
            f"💰 Balance: ${self.balance:.2f}\n"
            f"💎 Stake: ${self.config.STAKE}\n"
            f"📈 Growth Rate: {self.config.GROWTH_RATE*100}%\n"
            f"🎯 Take Profit: ${self.config.TAKE_PROFIT}"
        )

        self.is_running = True
        logger.success(f"{prefix} ✅ Bot started — waiting for ticks...")

        # Keep alive
        while self.is_running:
            await asyncio.sleep(5)

            # Log status periodically + update API state
            if self.analysis_engine.total_ticks % 500 == 0 and self.analysis_engine.total_ticks > 0:
                stats = self.analysis_engine.get_stats()
                logger.info(
                    f"{prefix} 📈 Status: {stats['total_ticks']} ticks, "
                    f"{stats['spikes_detected']} spikes, "
                    f"P&L: ${self.session_pnl:+.2f}, "
                    f"W/L: {self.total_wins}/{self.total_losses}"
                )

            # Update shared API state every cycle
            update_accu_state(self)

    async def _on_tick(self, tick_data: dict):
        """Process each incoming tick"""
        try:
            price = float(tick_data.get('quote', 0))
            epoch = int(tick_data.get('epoch', 0))
            symbol = tick_data.get('symbol', '')

            # Only process our symbol
            if symbol != self.config.SYMBOL:
                return

            # Push tick to chart storage
            push_accu_tick({"time": epoch, "value": price})

            # Run analysis
            analysis = self.analysis_engine.process_tick(price)

            # Check if we have an open contract
            if self.open_contract_id:
                # If volatility spikes while contract is open → sell early
                if analysis['ready'] and analysis['metrics'].get('volatility_score', 0) > 2.0:
                    logger.warning(
                        f"{self.config.LOG_PREFIX} ⚠️ Volatility spike during open contract! "
                        f"Vol: {analysis['metrics']['volatility_score']:.2f}x — selling early"
                    )
                    await self.ws_client.sell_contract(self.open_contract_id)
                return

            # Check cooldown
            if self.cooldown_until and datetime.now() < self.cooldown_until:
                return

            # Not ready yet
            if not analysis['ready']:
                if self.analysis_engine.total_ticks % 50 == 0:
                    logger.debug(f"{self.config.LOG_PREFIX} {analysis['reasoning']}")
                return

            # Update API state with latest signal
            accu_bot_state['last_signal'] = analysis['signal']
            accu_bot_state['last_reasoning'] = analysis['reasoning']
            accu_bot_state['volatility_score'] = analysis['metrics'].get('volatility_score', 0)

            # Check for entry signal
            if analysis['signal'] == 'ENTER' and not self._is_entering:
                await self._execute_entry(analysis)

        except Exception as e:
            logger.error(f"{self.config.LOG_PREFIX} ❌ Tick processing error: {e}")

    async def _execute_entry(self, analysis: dict):
        """Execute an ACCU contract purchase (with lock to prevent race conditions)"""
        if self._entry_lock.locked():
            return  # Another entry attempt is already in progress

        async with self._entry_lock:
            self._is_entering = True
            try:
                await self._do_entry(analysis)
            finally:
                self._is_entering = False

    async def _do_entry(self, analysis: dict):
        """Actually execute the entry (called under lock)"""
        prefix = self.config.LOG_PREFIX

        # Safety: don't enter if we already have an open contract
        if self.open_contract_id:
            return

        growth_rate = analysis['growth_rate']
        metrics = analysis['metrics']

        logger.info(
            f"{prefix} 🎯 ENTRY SIGNAL! "
            f"Price: {metrics['current_price']}, "
            f"Vol: {metrics['volatility_score']:.2f}x, "
            f"Growth: {growth_rate*100}%"
        )

        # Buy accumulator (with reconnect retry)
        contract = None
        for attempt in range(3):
            contract = await self.ws_client.buy_accumulator(
                symbol=self.config.SYMBOL,
                amount=self.config.STAKE,
                growth_rate=growth_rate,
                take_profit=self.config.TAKE_PROFIT
            )
            if contract:
                break

            # Failed — try reconnect
            logger.warning(f"{prefix} ⚡ Buy attempt {attempt+1}/3 failed, reconnecting...")
            try:
                # Close existing connection
                if self.ws_client.ws:
                    try:
                        await self.ws_client.ws.close()
                    except Exception:
                        pass
                self.ws_client.is_connected = False
                self.ws_client.running = False
                await asyncio.sleep(2)
                if not await self.ws_client.connect():
                    logger.error(f"{prefix} ❌ Reconnect failed")
                    continue
                self.ws_client.running = True
                asyncio.create_task(self.ws_client.message_handler_loop())
                auth = await self.ws_client.authorize(api_token=self.accu_api_token)
                if not auth:
                    logger.error(f"{prefix} ❌ Re-auth failed")
                    continue
                self.balance = float(auth.get('balance', 0))
                # Re-subscribe ticks
                self.ws_client.set_tick_callback(self._on_tick)
                self.ws_client.set_contract_callback(self._on_contract_update)
                await self.ws_client.subscribe_to_ticks(self.config.SYMBOL)
                logger.info(f"{prefix} ✅ Reconnected, retrying buy...")
                await asyncio.sleep(1)
            except Exception as re_err:
                logger.error(f"{prefix} ❌ Reconnect error: {re_err}")

        if contract:
            self.open_contract_id = contract.get('contract_id')
            self.open_contract_buy_price = float(contract.get('buy_price', 0))
            self.open_contract_start_time = datetime.now()
            self.open_contract_current_pnl = 0.0
            self.total_trades += 1

            logger.success(
                f"{prefix} ✅ ACCU opened! "
                f"ID: {self.open_contract_id}, "
                f"Price: ${self.open_contract_buy_price:.2f}, "
                f"Growth: {growth_rate*100}%"
            )

            # Telegram notification
            await telegram_notifier.send_message(
                f"🎰 **ACCU Opened**\n"
                f"📊 {self.config.SYMBOL}\n"
                f"💲 Stake: ${self.config.STAKE}\n"
                f"📈 Growth: {growth_rate*100}%\n"
                f"🎯 TP: ${self.config.TAKE_PROFIT}\n"
                f"📉 Vol: {metrics['volatility_score']:.2f}x\n"
                f"#{self.total_trades}"
            )
        else:
            logger.error(f"{prefix} ❌ Failed to open ACCU contract after 3 attempts")

    async def _on_contract_update(self, contract_data: dict):
        """Handle contract updates (profit, barriers, close)"""
        try:
            contract_id = contract_data.get('contract_id')

            # Only process our contract
            if str(contract_id) != str(self.open_contract_id):
                return

            prefix = self.config.LOG_PREFIX
            status = contract_data.get('status')
            profit = float(contract_data.get('profit', 0))
            is_sold = contract_data.get('is_sold')
            is_expired = contract_data.get('is_expired')
            is_valid_to_sell = contract_data.get('is_valid_to_sell')
            current_spot = contract_data.get('current_spot')
            sell_price = float(contract_data.get('sell_price', 0))
            exit_tick = contract_data.get('exit_tick')

            self.open_contract_current_pnl = profit

            # Determine if contract is closed
            # Deriv uses multiple signals: is_sold, is_expired, status, exit_tick
            contract_closed = (
                is_sold 
                or is_expired 
                or status in ['sold', 'won', 'lost', 'ended', 'cancelled']
                or (exit_tick is not None and is_valid_to_sell == 0)
            )

            if not contract_closed:
                # Contract still open — log progress
                if abs(profit) > 0:
                    logger.debug(
                        f"{prefix} 💰 ACCU P&L: ${profit:+.2f} | "
                        f"Spot: {current_spot} | Status: {status}"
                    )
                return

            # Contract closed!
            if profit > 0:
                outcome = 'WIN'
                self.total_wins += 1
                self.consecutive_losses = 0
                emoji = '🏆'
            else:
                outcome = 'LOSS'
                self.total_losses += 1
                self.consecutive_losses += 1
                emoji = '😞'

            self.session_pnl += profit

            duration = (datetime.now() - self.open_contract_start_time).total_seconds() if self.open_contract_start_time else 0

            logger.info(
                f"{prefix} {emoji} ACCU CLOSED: {outcome} "
                f"${profit:+.2f} | Duration: {duration:.0f}s | "
                f"Total P&L: ${self.session_pnl:+.2f} | "
                f"W/L: {self.total_wins}/{self.total_losses}"
            )

            # Telegram notification
            win_rate = (self.total_wins / self.total_trades * 100) if self.total_trades > 0 else 0
            await telegram_notifier.send_message(
                f"{emoji} **ACCU {outcome}**\n"
                f"💰 P&L: ${profit:+.2f}\n"
                f"⏱️ Duration: {duration:.0f}s\n"
                f"📊 Session: ${self.session_pnl:+.2f}\n"
                f"🎯 Win Rate: {win_rate:.0f}% ({self.total_wins}W/{self.total_losses}L)\n"
                f"💎 Balance: ${self.balance:.2f}"
            )

            # Log trade to in-memory API state
            log_accu_trade({
                'outcome': outcome,
                'pnl': profit,
                'growth_rate': accu_bot_state.get('growth_rate', 0.02),
                'duration': f'{duration:.0f}',
                'time': datetime.now().strftime('%H:%M:%S'),
            })

            # Persist trade to PostgreSQL
            save_accu_trade({
                'symbol': self.config.SYMBOL,
                'deriv_contract_id': str(contract_id),
                'entry_time': self.open_contract_start_time or datetime.now(),
                'entry_price': self.open_contract_buy_price,
                'stake': self.config.STAKE,
                'growth_rate': accu_bot_state.get('growth_rate', self.config.GROWTH_RATE),
                'take_profit': self.config.TAKE_PROFIT,
                'exit_time': datetime.now(),
                'exit_price': float(current_spot) if current_spot else None,
                'profit_loss': profit,
                'outcome': outcome,
                'duration_seconds': int(duration),
                'volatility_score': accu_bot_state.get('volatility_score'),
                'signal': accu_bot_state.get('last_signal'),
                'reasoning': accu_bot_state.get('last_reasoning'),
            })

            # Reset contract state AFTER saving
            self.open_contract_id = None
            self.open_contract_buy_price = 0.0
            self.open_contract_start_time = None
            self.open_contract_current_pnl = 0.0

            # Apply cooldown if loss
            if outcome == 'LOSS':
                if self.consecutive_losses >= self.config.MAX_CONSECUTIVE_LOSSES:
                    cooldown = self.config.LONG_COOLDOWN
                    logger.warning(
                        f"{prefix} ⛔ {self.consecutive_losses} consecutive losses! "
                        f"Long cooldown: {cooldown}s"
                    )
                else:
                    cooldown = self.config.COOLDOWN_AFTER_LOSS
                    logger.info(f"{prefix} ⏳ Cooldown: {cooldown}s after loss")

                self.cooldown_until = datetime.now() + timedelta(seconds=cooldown)

        except Exception as e:
            logger.error(f"{self.config.LOG_PREFIX} ❌ Contract update error: {e}")

    async def _on_balance_update(self, balance_data: dict):
        """Update balance"""
        try:
            self.balance = float(balance_data.get('balance', 0))
        except Exception as e:
            logger.error(f"{self.config.LOG_PREFIX} ❌ Balance update error: {e}")

    async def _on_candle(self, candle_data):
        """Process incoming candle data and push to API for charting"""
        try:
            if isinstance(candle_data, dict):
                push_accu_candle({
                    "time": int(candle_data.get("epoch", candle_data.get("open_time", 0))),
                    "open": float(candle_data.get("open", 0)),
                    "high": float(candle_data.get("high", 0)),
                    "low": float(candle_data.get("low", 0)),
                    "close": float(candle_data.get("close", 0)),
                })
            elif isinstance(candle_data, list):
                for c in candle_data:
                    push_accu_candle({
                        "time": int(c.get("epoch", 0)),
                        "open": float(c.get("open", 0)),
                        "high": float(c.get("high", 0)),
                        "low": float(c.get("low", 0)),
                        "close": float(c.get("close", 0)),
                    })
        except Exception as e:
            logger.error(f"{self.config.LOG_PREFIX} ❌ Candle processing error: {e}")

    async def stop(self):
        """Stop the bot gracefully"""
        prefix = self.config.LOG_PREFIX
        logger.warning(f"{prefix} ⏸️ Stopping Accumulator Bot...")

        self.is_running = False

        # Sell open contract if any
        if self.open_contract_id:
            logger.info(f"{prefix} 💸 Selling open contract {self.open_contract_id}...")
            await self.ws_client.sell_contract(self.open_contract_id)

        await self.ws_client.stop()
        self.db.close()

        # Final report
        win_rate = (self.total_wins / self.total_trades * 100) if self.total_trades > 0 else 0
        logger.success(
            f"{prefix} ✅ Bot stopped.\n"
            f"  Trades: {self.total_trades}\n"
            f"  Wins: {self.total_wins}\n"
            f"  Losses: {self.total_losses}\n"
            f"  Win Rate: {win_rate:.1f}%\n"
            f"  Session P&L: ${self.session_pnl:+.2f}"
        )

        await telegram_notifier.send_message(
            f"⏸️ **Accumulator Bot Stopped**\n"
            f"📊 Trades: {self.total_trades}\n"
            f"🏆 Wins: {self.total_wins} | 😞 Losses: {self.total_losses}\n"
            f"🎯 Win Rate: {win_rate:.0f}%\n"
            f"💰 Session P&L: ${self.session_pnl:+.2f}\n"
            f"💎 Final Balance: ${self.balance:.2f}"
        )


# === Entry Point ===

async def main():
    """Run the Accumulator Bot"""
    bot = AccumulatorBot()

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.warning("⚠️ Keyboard interrupt")
        await bot.stop()
    except Exception as e:
        logger.critical(f"🚨 Fatal error: {e}")
        import traceback
        traceback.print_exc()
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
