"""
Main Trading Bot Loop
Orchestrates all services and executes trading strategy
"""
import asyncio
from datetime import datetime
import pandas as pd
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
        
        # Engine: read persisted choice from DB, fallback to config default
        from app.analysis.engine_registry import get_engine, get_engine_config
        try:
            from sqlalchemy import text as sa_text
            row = self.db.execute(sa_text("SELECT value FROM bot_settings WHERE key = 'engine_name'")).fetchone()
            if row and row[0]:
                settings.ENGINE_NAME = row[0]
                logger.info(f"🔧 Engine restored from DB: {settings.ENGINE_NAME}")
            else:
                logger.info(f"🔧 No saved engine in DB, using default: {settings.ENGINE_NAME}")
        except Exception as e:
            logger.warning(f"⚠️ Could not read engine from DB: {e}, using default: {settings.ENGINE_NAME}")
        self.signal_engine = get_engine(settings.ENGINE_NAME)
        self.engine_config = get_engine_config(settings.ENGINE_NAME)
        self.engine_name = settings.ENGINE_NAME
        logger.info(f"🔧 Live bot engine: {settings.ENGINE_NAME}")
        
        # Engine presets — driven entirely by the selected motor
        self.hurst_min = self.engine_config.get('hurst_min', 0.6)
        self.hurst_max = self.engine_config.get('hurst_max', 0.7)
        self.blocked_hours = set(self.engine_config.get('blocked_hours', []))
        self.min_confidence = self.engine_config.get('confidence_min', 0.60)
        logger.info(f"📊 Hurst range: [{self.hurst_min}, {self.hurst_max}], confidence_min: {self.min_confidence}")
        logger.info(f"🕐 Blocked hours (Col): {sorted(self.blocked_hours) if self.blocked_hours else 'ninguna'}")
        
        # Defensive filters — from engine config
        df_cfg = self.engine_config.get('defensive', {})
        self.enable_wr_monitor = df_cfg.get('enable_wr_monitor', True)
        self.wr_check_interval = df_cfg.get('wr_check_interval', 15)
        self.wr_pause_threshold = df_cfg.get('wr_pause_threshold', 0.45)
        self.wr_stop_threshold = df_cfg.get('wr_stop_threshold', 0.40)
        self.wr_pause_candles = df_cfg.get('wr_pause_candles', 30)
        self.wr_min_trades_pause = df_cfg.get('wr_min_trades_pause', 20)
        self.wr_min_trades_stop = df_cfg.get('wr_min_trades_stop', 30)
        
        self.enable_global_streak = df_cfg.get('enable_global_streak', True)
        self.global_streak_limit = df_cfg.get('global_streak_limit', 5)
        self.global_streak_pause = df_cfg.get('global_streak_pause', 60)
        
        self.dir_cooldown_losses = df_cfg.get('dir_cooldown_losses', 3)
        self.dir_cooldown_candles = df_cfg.get('dir_cooldown_candles', 30)
        
        self.enable_atr_gate = df_cfg.get('enable_atr_gate', True)
        self.atr_lookback = df_cfg.get('atr_lookback', 30)
        self.atr_low_mult = df_cfg.get('atr_low_mult', 0.5)
        self.atr_high_mult = df_cfg.get('atr_high_mult', 2.0)
        
        self.cooldown_candles = df_cfg.get('cooldown_candles', 3)
        logger.info(f"🛡️ Defensive filters: WR monitor={self.enable_wr_monitor}, streak={self.enable_global_streak}, ATR={self.enable_atr_gate}")
        
        # Runtime state for defensive filters
        self._trade_results = []  # list of 'WIN'/'LOSS'
        self._consecutive_losses = 0
        self._dir_losses = {'CALL': 0, 'PUT': 0}
        self._pause_until_candle = 0
        self._candle_count = 0
        self._day_stopped = False
        
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
            
            # ===== UPDATE DEFENSIVE FILTER STATE =====
            self._update_defensive_state(outcome, trade.direction or trade.contract_type)
            
        except Exception as e:
            logger.error(f"❌ Error processing contract update: {e}")

    def _update_defensive_state(self, outcome: str, direction: str):
        """Update defensive filter state after a trade result."""
        self._trade_results.append(outcome)
        
        # --- Global streak tracking ---
        if outcome == 'LOSS':
            self._consecutive_losses += 1
            # Direction-specific cooldown
            if direction in self._dir_losses:
                self._dir_losses[direction] += 1
                if self._dir_losses[direction] >= self.dir_cooldown_losses:
                    self._pause_until_candle = self._candle_count + self.dir_cooldown_candles
                    logger.warning(f"🔴 {self.dir_cooldown_losses} losses in {direction} → pausing {self.dir_cooldown_candles} candles")
                    self._dir_losses[direction] = 0
        else:
            self._consecutive_losses = 0
            # Reset dir losses on win
            if direction in self._dir_losses:
                self._dir_losses[direction] = max(0, self._dir_losses[direction] - 1)
        
        # --- Global streak protection ---
        if self.enable_global_streak and self._consecutive_losses >= self.global_streak_limit:
            self._pause_until_candle = self._candle_count + self.global_streak_pause
            logger.warning(f"🔴 {self._consecutive_losses} consecutive losses → pausing {self.global_streak_pause} candles")
            self._consecutive_losses = 0
        
        # --- WR monitor ---
        if self.enable_wr_monitor:
            total = len(self._trade_results)
            if total > 0 and total % self.wr_check_interval == 0:
                wins = sum(1 for r in self._trade_results if r == 'WIN')
                wr = wins / total
                
                if total >= self.wr_min_trades_stop and wr < self.wr_stop_threshold:
                    self._day_stopped = True
                    logger.warning(f"🛑 WR {wr:.1%} after {total} trades < {self.wr_stop_threshold:.0%} → DAY STOPPED")
                elif total >= self.wr_min_trades_pause and wr < self.wr_pause_threshold:
                    self._pause_until_candle = self._candle_count + self.wr_pause_candles
                    logger.warning(f"⏸️ WR {wr:.1%} after {total} trades < {self.wr_pause_threshold:.0%} → pausing {self.wr_pause_candles} candles")

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
        Perform analysis and execute trade if signal is strong.
        Uses TradingCore — THE SINGLE BRAIN — same as simulations.
        All filters are driven by the engine config.
        """
        try:
            self._candle_count += 1
            
            # ===== FILTER: Day stopped (WR too low) =====
            if self._day_stopped:
                logger.debug("🛑 Day stopped by WR monitor")
                return
            
            # ===== FILTER: Pause active (streak/cooldown) =====
            if self._candle_count < self._pause_until_candle:
                remaining = self._pause_until_candle - self._candle_count
                logger.debug(f"⏸️ Paused ({remaining} candles remaining)")
                return
            
            # ===== FILTER: Blocked hours (Colombia time) =====
            if self.blocked_hours:
                from datetime import timezone, timedelta
                col_tz = timezone(timedelta(hours=-5))
                col_hour = datetime.now(col_tz).hour
                if col_hour in self.blocked_hours:
                    logger.debug(f"🚫 Hour {col_hour:02d} blocked by engine {self.engine_name}")
                    return
            
            logger.info("🔍 Analyzing market...")
            
            # Get recent candles
            df = self.data_collector.get_recent_candles(count=250)
            
            if df.empty or len(df) < 50:
                logger.warning("⚠️ Not enough candle data yet")
                return
            
            # ===== FILTER: ATR volatility gate =====
            if self.enable_atr_gate and len(df) >= self.atr_lookback:
                try:
                    atr_series = (df['high'] - df['low']).rolling(self.atr_lookback).mean()
                    current_atr = atr_series.iloc[-1]
                    avg_atr = atr_series.mean()
                    if current_atr < avg_atr * self.atr_low_mult:
                        logger.info(f"📉 ATR too low ({current_atr:.4f} < {avg_atr * self.atr_low_mult:.4f}) — skipping")
                        return
                    if current_atr > avg_atr * self.atr_high_mult:
                        logger.info(f"📈 ATR too high ({current_atr:.4f} > {avg_atr * self.atr_high_mult:.4f}) — skipping")
                        return
                except Exception as e:
                    logger.debug(f"ATR gate error: {e}")
            
            # Resolve pending decision comparisons
            try:
                from app.services.decision_tracker import resolve_pending
                resolve_pending(self.db)
            except Exception as e:
                logger.debug(f"Decision resolver: {e}")
            
            # ===== THE SINGLE BRAIN — TradingCore =====
            from app.simulation.trading_core import TradingCore
            result = await TradingCore.analyze_async(
                engine=self.signal_engine,
                df=df,
                symbol=self.symbol,
                use_groq=settings.USE_GROQ_LAYER2,
                ai_provider='groq',
                hurst_min=self.hurst_min,
                hurst_max=self.hurst_max,
            )
            
            final_decision = result["action"]
            final_confidence = result["confidence"]
            l1_signal = result["l1_signal"]
            
            logger.info(f"📊 L1: {l1_signal} ({result['l1_confidence']:.2%}) → Final: {final_decision} ({final_confidence:.2%})")
            if result["groq_used"]:
                logger.success(f"🧠 AI ({result['ai_provider']}): {result['reasoning'][:150]}")
            
            # --- Save L1 vs AI decision for comparison ---
            if result["groq_used"]:
                try:
                    from app.services.decision_tracker import save_decision
                    save_decision(
                        db=self.db,
                        entry_price=result["entry_price"],
                        l1_signal=l1_signal,
                        l1_confidence=result["l1_confidence"],
                        groq_signal=final_decision,
                        groq_confidence=final_confidence,
                        duration=300
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to track decision: {e}")

            # --- SAVE ANALYSIS HISTORY FOR CHART ---
            try:
                from app.models.models import AnalysisHistory
                from app.analysis.hurst import HurstExponent
                
                # Compute HYBRID Hurst (fast VR + slow R/S)
                real_hurst = 0.5
                real_hurst_fast = 0.5
                real_regime = None
                try:
                    hurst_hybrid = HurstExponent.get_hybrid_signal(df['close'], fast_window=50, slow_window=200)
                    real_hurst = hurst_hybrid.get('hurst_slow', 0.5)
                    real_hurst_fast = hurst_hybrid.get('hurst_fast', 0.5)
                    real_regime = hurst_hybrid.get('regime', 'RANDOM_WALK')
                except Exception as he:
                    logger.debug(f"Hurst calculation: {he}")
                
                # Compute REAL O-U deviation using the model
                ou_dev = 0.0
                try:
                    from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
                    ou_model = OrnsteinUhlenbeckModel(window=200)
                    if ou_model.fit(df['close']):
                        ou_dev = ou_model.get_deviation(float(df['close'].iloc[-1]))
                except Exception as oue:
                    logger.debug(f"O-U deviation calc: {oue}")
                latest_row = df.iloc[-1]
                rsi_val = float(latest_row.get('rsi_14', 0)) if 'rsi_14' in df.columns else None
                ema9_val = float(latest_row.get('ema_9', 0)) if 'ema_9' in df.columns else None
                ema21_val = float(latest_row.get('ema_21', 0)) if 'ema_21' in df.columns else None
                
                history_entry = AnalysisHistory(
                    timestamp=datetime.utcnow(),
                    symbol=self.symbol,
                    hurst_value=real_hurst,
                    hurst_regime=real_regime,
                    ou_deviation=ou_dev,
                    ou_signal=result.get("l1_signal", "HOLD"),
                    final_signal=final_decision,
                    final_confidence=final_confidence,
                    current_price=result["entry_price"],
                    duration=300,
                    rsi_14=rsi_val,
                    ema_9=ema9_val,
                    ema_21=ema21_val,
                )
                self.db.add(history_entry)
                self.db.commit()
                
                # --- UPDATE LIVE CANDLE IN 'candles' TABLE ---
                # This ensures the Dashboard Chart (which reads 'candles') matches the Bot logic
                try:
                    # Update the latest candle with bot's analysis values
                    # (DataCollector handles per-candle Hurst; this is a safety net)
                    last_ts = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else df.iloc[-1]['open_time']
                    from sqlalchemy import text
                    self.db.execute(text("""
                        UPDATE candles 
                        SET hurst_exponent = :hurst,
                            hurst_fast = :hurst_fast,
                            ou_deviation = :ou_dev,
                            regime = :regime,
                            garch_volatility_forecast = :garch
                        WHERE symbol = :symbol 
                          AND open_time = :open_time
                    """), {
                        "hurst": float(real_hurst),
                        "hurst_fast": float(real_hurst_fast),
                        "ou_dev": float(ou_dev),
                        "regime": real_regime or 'RANDOM_WALK',
                        "garch": 0.0,
                        "symbol": self.symbol,
                        "open_time": last_ts
                    })
                    self.db.commit()
                    # logger.debug(f"✅ Updated candle indicators for {last_ts}")
                except Exception as ce:
                    logger.error(f"❌ Failed to update candle indicators: {ce}")
                    
            except Exception as e:
                logger.error(f"⚠️ Failed to save AnalysisHistory: {e}")
            
            if final_decision in ['CALL', 'PUT']:
                if final_confidence >= self.min_confidence:
                    
                    # Get current balance
                    self.risk_manager.refresh_state()
                    balance = float(self.risk_manager.bot_state.balance)
                    
                    # Build signal dict for trade executor (it expects specific keys)
                    trade_signal = {
                        'symbol': self.symbol,
                        'contract_type': final_decision,  # CALL or PUT
                        'decision': final_decision,
                        'final_signal': final_decision,
                        'confidence': final_confidence,
                        'final_confidence': final_confidence,
                        'current_price': result['entry_price'],
                        'suggested_stake_multiplier': 1.0,
                        'duration': 300,
                        'reasoning': result['reasoning'],
                        'hurst_signal': {'hurst': real_hurst},
                        'engine_name': settings.ENGINE_NAME,
                    }
                    
                    # Execute trade
                    trade = await self.trade_executor.execute_trade(trade_signal, balance)
                    
                    if trade:
                        logger.success(f"✅ Trade executed: {trade.id}")
                        # Apply cooldown after trade
                        self._pause_until_candle = self._candle_count + self.cooldown_candles
                    else:
                        logger.warning("⚠️ Trade execution blocked by risk management")
                else:
                    logger.info(f"📉 Confidence too low ({final_confidence:.2%} < 60%)")
            else:
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
