"""
Main Trading Bot Loop
Orchestrates all services and executes trading strategy
"""
import asyncio
from datetime import datetime
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import get_settings
from app.services.deriv_client import deriv_client
from app.services.data_collector import DataCollector
from app.services.risk_manager import RiskManager
from app.services.trade_executor import TradeExecutor
from app.services.telegram_notifier import telegram_notifier
from app.analysis.layer1_engine import Layer1SignalEngine
from app.models.models import BotState, Candle

settings = get_settings()


class TradingBot:
    """
    Main trading bot orchestrator
    """
    
    def __init__(self):
        self.db: Session = SessionLocal()
        self.symbol = "R_100"  # Volatility 100 Index
        self.timeframe_seconds = 60  # 1 minute candles
        
        # Services
        self.data_collector = DataCollector(self.db, self.symbol, self.timeframe_seconds)
        self.risk_manager = RiskManager(self.db)
        self.trade_executor = TradeExecutor(self.db)
        self.signal_engine = Layer1SignalEngine()
        
        # State
        self.is_running = False
        self.last_analysis_time = None
        self.analysis_interval = 60  # Analyze every 60 seconds
    
    async def start(self):
        """Start the trading bot"""
        logger.info("🤖 Starting Deriv Trading Bot V2...")
        
        # Initialize bot state
        await self._initialize_state()
        
        # Connect to Deriv WebSocket
        # Connect to Deriv WebSocket
        logger.info("🔌 Connecting to Deriv...")
        if not await deriv_client.connect():
            logger.critical("❌ Failed to connect to Deriv")
            return
        
        # Start Deriv message handler loop in background *BEFORE* auth
        # (Auth requires handler to receive response)
        deriv_client.running = True  # Enable message handler
        logger.info("🔄 Starting WebSocket message handler (Trading Only)...")
        asyncio.create_task(deriv_client.message_handler_loop())
        
        # Authorize
        auth_data = await deriv_client.authorize()
        if not auth_data:
            logger.critical("❌ Failed to authorize with Deriv")
            return
            
        # Initialize/Update balance from auth data
        initial_balance = float(auth_data.get('balance', 0))
        is_virtual = auth_data.get('is_virtual')
        account_type_detected = "DEMO" if is_virtual else "REAL"
        
        logger.info(f"💳 Identified Account Type: {account_type_detected}")
        logger.info(f"💰 Initial Balance from Deriv: ${initial_balance:.2f}")
        
        # Verify against settings
        if settings.DERIV_ACCOUNT_TYPE.upper() != account_type_detected:
            logger.warning(f"⚠️ Account mismatch! Config: {settings.DERIV_ACCOUNT_TYPE.upper()}, Detected: {account_type_detected}")
        
        self.risk_manager.update_balance(initial_balance)
        
        # Set callbacks
        deriv_client.set_tick_callback(self._on_tick)
        deriv_client.set_balance_callback(self._on_balance_update)
        deriv_client.set_contract_callback(self._on_contract_update)
        
        # Subscribe to balance updates
        logger.info("💰 Subscribing to balance updates...")
        await deriv_client.subscribe_balance()
        
        # Subscribe to ticks - DISABLED (Handled by feeder)
        # logger.info(f"📊 Subscribing to {self.symbol}...")
        # await deriv_client.subscribe_to_ticks(self.symbol)
        
        # Send startup notification
        await telegram_notifier.notify_bot_started()
        
        self.is_running = True
        deriv_client.running = True  # Enable message handler for trading responses
        
        # Start settlement loop
        asyncio.create_task(self._check_trades_loop())
        
        # Start main loop
        logger.success("✅ Bot started - entering main loop")
        await self._main_loop()
    
    async def _initialize_state(self):
        """Initialize or load bot state"""
        state = self.db.query(BotState).filter(BotState.id == 1).first()
        
        if not state:
            # First run - initialize
            logger.info("📝 Initializing bot state...")
            
            # Get balance from Deriv (already done in authorize)
            # For now, set a default
            initial_balance = 1000.0  # TODO: Get from Deriv
            
            state = BotState(
                id=1,
                balance=initial_balance,
                initial_balance=initial_balance,
                peak_balance=initial_balance
            )
            self.db.add(state)
            self.db.commit()
            
            logger.info(f"💰 Initial balance: ${initial_balance:.2f}")
        else:
            logger.info(f"💰 Current balance: ${state.balance:.2f}")
            
            # Reset daily counters if new day
            self.risk_manager.reset_daily_counters()
    
    async def _on_tick(self, tick_data: dict):
        """
        Callback for incoming ticks
        """
        # Process tick (save and update candles)
        # DISABLED: Data collection handled by feeder service
        # await self.data_collector.process_tick(tick_data)
        pass
    
    async def _on_balance_update(self, balance_data: dict):
        """
        Callback for balance updates
        """
        try:
            balance = float(balance_data.get('balance', 0))
            self.risk_manager.update_balance(balance)
        except Exception as e:
            logger.error(f"❌ Error updating balance: {e}")

    async def _on_contract_update(self, contract_data: dict):
        """
        Callback for contract updates (trade outcomes)
        """
        try:
            from app.models.models import Trade
            
            contract_id = str(contract_data.get('contract_id'))
            status = contract_data.get('status')
            
            # Only process when contract is sold/closed
            if status not in ['sold', 'won', 'lost']:
                return
            
            # Find trade by contract ID
            trade = self.db.query(Trade).filter(
                Trade.deriv_contract_id == contract_id
            ).first()
            
            if not trade:
                logger.warning(f"⚠️ Contract {contract_id} not found in database")
                return
            
            # Already processed
            if trade.outcome != 'PENDING':
                return
            
            # Extract outcome data
            sell_price = float(contract_data.get('sell_price', 0))
            buy_price = float(contract_data.get('buy_price', 0))
            profit = sell_price - buy_price
            
            # Determine outcome
            if profit > 0:
                outcome = 'WIN'
            elif profit < 0:
                outcome = 'LOSS'
            else:
                outcome = 'BREAK_EVEN'
            
            # Close trade
            await self.trade_executor.close_trade(
                trade=trade,
                outcome=outcome,
                exit_price=sell_price,
                profit_loss=profit
            )
            
            logger.success(f"✅ Trade {trade.id} closed: {outcome} {profit:+.2f} USD")
            
        except Exception as e:
            logger.error(f"❌ Error processing contract update: {e}")

    async def _main_loop(self):
        """
        Main trading loop
        Analyzes market and executes trades
        """
        while self.is_running:
            try:
                # Check if it's time to analyze
                current_time = datetime.now()
                
                if self.last_analysis_time is None or \
                   (current_time - self.last_analysis_time).total_seconds() >= self.analysis_interval:
                    
                    await self._analyze_and_trade()
                    self.last_analysis_time = current_time
                
                # Sleep briefly
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}")
                await asyncio.sleep(30)
    
    async def _analyze_and_trade(self):
        """
        Perform analysis and execute trade if signal is strong
        """
        try:
            logger.info("🔍 Analyzing market...")
            
            # Get recent candles
            df = self.data_collector.get_recent_candles(count=250)
            
            if df.empty or len(df) < 50:
                logger.warning("⚠️ Not enough candle data yet")
                return
            
            # Resolve pending decision comparisons
            try:
                from app.services.decision_tracker import resolve_pending
                resolve_pending(self.db)
            except Exception as e:
                logger.debug(f"Decision resolver: {e}")
            
            # Run Layer 1 analysis
            signal = self.signal_engine.analyze(df, self.symbol)
            
            logger.info(f"📊 Layer 1 Signal: {signal['final_signal']} (confidence: {signal['final_confidence']:.2%})")
            logger.info(f"💡 Reasoning: {signal['reasoning']}")
            
            # Layer 2: Groq AI meta-analysis (if enabled)
            # ARCHITECTURE: Groq is the FINAL decision maker
            # It receives ALL L1 technical data and makes its own decision
            # L1 filters (RSI, momentum, etc.) inform Groq but don't block it
            
            l1_signal = signal.get('final_signal', 'HOLD')
            hurst_regime = signal.get('hurst_signal', {}).get('regime', 'UNKNOWN')
            hurst_value = signal.get('hurst_signal', {}).get('hurst', 0.5)
            
            # Call Groq ONLY when L1 has a directional signal
            # L1 is the gatekeeper — if L1 says HOLD, we HOLD
            should_call_groq = l1_signal in ['CALL', 'PUT']
            
            if settings.USE_GROQ_LAYER2:
                if should_call_groq:
                    try:
                        from app.analysis.layer2_groq import get_layer2_engine
                        layer2 = get_layer2_engine()
                        
                        # Get candles for context (30 for better trend visibility)
                        candles = self.db.query(Candle).order_by(Candle.open_time.desc()).limit(30).all()
                        candles.reverse()
                        
                        logger.info(f"🚀 Triggering Groq Analysis (L1: {l1_signal}, Hurst: {hurst_value:.3f}, Regime: {hurst_regime})")
                        
                        # Run Layer 2 analysis — Groq sees ALL L1 data and decides
                        signal = await layer2.analyze(
                            layer1_signal=signal,
                            candles=candles,
                            db=self.db
                        )
                        
                        logger.success(
                            f"🧠 Layer 2 (Groq) Final: {signal['decision']} "
                            f"(confidence: {signal['confidence']:.2%})"
                        )
                    except Exception as e:
                        logger.error(f"❌ Layer 2 error, falling back to Layer 1: {e}")
                        # signal remains unchanged (Layer 1 only)
                    
                    # --- Save L1 vs Groq decision for comparison ---
                    try:
                        from app.services.decision_tracker import save_decision
                        groq_decision_signal = signal.get('decision', signal.get('final_signal', 'HOLD'))
                        groq_decision_conf = signal.get('confidence', signal.get('final_confidence', 0))
                        save_decision(
                            db=self.db,
                            entry_price=signal.get('current_price', 0),
                            l1_signal=l1_signal,
                            l1_confidence=signal.get('layer1_confidence', signal.get('final_confidence', 0)),
                            groq_signal=groq_decision_signal,
                            groq_confidence=groq_decision_conf,
                            duration=signal.get('duration', 300)
                        )
                    except Exception as e:
                        logger.error(f"❌ Failed to track decision: {e}")
                    
                else:
                    logger.info(f"💤 Market not trending (Hurst={hurst_value:.3f}) — Skipping Groq")
                    # No connection made to Groq API

            
            # Execute trade if signal is strong enough
            final_decision = signal.get('decision', signal.get('final_signal'))
            final_confidence = signal.get('confidence', signal.get('final_confidence', 0))

            # --- SAVE ANALYSIS HISTORY FOR CHART ---
            try:
                from app.models.models import AnalysisHistory
                
                # Extract metrics safely (handle both L1 and L2 structures)
                hurst_sig = signal.get('hurst_signal', {})
                ou_sig = signal.get('ou_signal', {})
                
                history_entry = AnalysisHistory(
                    timestamp=datetime.utcnow(), # Use UTC to match DB convention
                    symbol=self.symbol,
                    hurst_value=hurst_sig.get('hurst'),
                    hurst_regime=hurst_sig.get('regime'),
                    ou_signal=ou_sig.get('signal'),
                    ou_deviation=ou_sig.get('deviation'),
                    ou_confidence=ou_sig.get('confidence'),
                    final_signal=final_decision,
                    final_confidence=final_confidence,
                    current_price=signal.get('current_price'),
                    duration=signal.get('duration', 300)
                )
                self.db.add(history_entry)
                self.db.commit()
            except Exception as e:
                logger.error(f"⚠️ Failed to save AnalysisHistory: {e}")
            # ---------------------------------------
            
            if final_decision in ['CALL', 'PUT']:
                # Minimum confidence threshold
                if final_confidence >= 0.60:
                    
                    # Get current balance
                    self.risk_manager.refresh_state()
                    balance = float(self.risk_manager.bot_state.balance)
                    
                    # Execute trade
                    trade = await self.trade_executor.execute_trade(signal, balance)
                    
                    if trade:
                        logger.success(f"✅ Trade executed: {trade.id}")
                    else:
                        logger.warning("⚠️ Trade execution blocked by risk management")
                else:
                    logger.info(f"📉 Confidence too low ({final_confidence:.2%} < 60%)")
            else:
                logger.info("⏸️ No trading signal - HOLD")
                
                logger.info("⏸️ No trading signal - HOLD")
                
        except Exception as e:
            logger.error(f"❌ Analysis error: {e}")
            
    async def _check_trades_loop(self):
        """
        Background task to check pending trades
        """
        logger.info("🔄 Starting trade settlement loop...")
        while self.is_running:
            try:
                # Check pending trades
                await self.trade_executor.check_pending_trades()
                
                # Sleep
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Error in trade settlement loop: {e}")
                await asyncio.sleep(60)
    
    async def stop(self):
        """Stop the trading bot gracefully"""
        logger.warning("⏸️ Stopping bot...")
        self.is_running = False
        await deriv_client.stop()
        self.db.close()
        logger.success("✅ Bot stopped")


# Main entry point
async def main():
    """Run the trading bot"""
    bot = TradingBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.warning("⚠️ Keyboard interrupt received")
        await bot.stop()
    except Exception as e:
        logger.critical(f"🚨 Fatal error: {e}")
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
