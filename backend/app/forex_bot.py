"""
Forex Trading Bot — EUR/USD (frxEURUSD)
Mirrors the R_100 bot architecture but uses:
- symbol = 'frxEURUSD'
- ForexCandle / ForexTrade / ForexBotState tables
- forex_* engines from the registry
- Per-engine multi-bot loop (same as R_100 bot)
"""
import asyncio
from datetime import datetime, timezone, date
import pandas as pd
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import text as sa_text

from app.core.database import SessionLocal
from app.core.config import get_settings
from app.models.models import ForexCandle, ForexTrade, ForexBotState
from app.analysis.indicators import TechnicalIndicators
from app.analysis.hurst import HurstExponent
from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel

settings = get_settings()

FOREX_SYMBOL     = "frxEURUSD"
TIMEFRAME_SEC    = 60
CANDLE_LIMIT     = 500   # candles for analysis


# ─── in-memory state shared between tick handler and main loop ───────────────
_current_candle: dict = {}
_candle_start_time: datetime | None = None
_last_close: float = 0.0
_forex_running: bool = False
# ─────────────────────────────────────────────────────────────────────────────


class ForexDataCollector:
    """Tick aggregator — builds 1-minute ForexCandle rows from raw ticks."""

    def __init__(self, db: Session):
        self.db = db
        self.current: dict = {}
        self.start_time: datetime | None = None

    async def on_tick(self, tick: dict):
        global _last_close
        try:
            epoch = int(tick['epoch'])
            quote = float(tick['quote'])
            ts = datetime.fromtimestamp(epoch, tz=timezone.utc)
            _last_close = quote

            # Round down to minute
            minute_start = ts.replace(second=0, microsecond=0)

            if self.start_time and minute_start > self.start_time:
                await self._finalise()

            if not self.current or minute_start > self.start_time:
                self.start_time = minute_start
                self.current = {
                    'open': quote, 'high': quote, 'low': quote,
                    'close': quote, 'ticks': 1
                }
            else:
                self.current['high']   = max(self.current['high'], quote)
                self.current['low']    = min(self.current['low'],  quote)
                self.current['close']  = quote
                self.current['ticks'] += 1
        except Exception as e:
            logger.error(f"[FOREX collector] tick error: {e}")

    async def _finalise(self):
        if not self.current or not self.start_time:
            return
        try:
            candle = ForexCandle(
                symbol=FOREX_SYMBOL,
                timeframe=f"{TIMEFRAME_SEC}s",
                open_time=self.start_time,
                close_time=self.start_time.replace(second=59),
                open=self.current['open'],
                high=self.current['high'],
                low=self.current['low'],
                close=self.current['close'],
                volume=self.current['ticks'],
            )
            self.db.add(candle)
            self.db.commit()
            logger.debug(f"[FOREX] Candle saved: {FOREX_SYMBOL} @ {self.start_time}")
            asyncio.create_task(self._calc_indicators())
        except Exception as e:
            logger.error(f"[FOREX collector] finalise error: {e}")
            self.db.rollback()

    async def _calc_indicators(self):
        """Compute indicators on last 300 candles and write to DB."""
        try:
            candles = (
                self.db.query(ForexCandle)
                .filter(ForexCandle.symbol == FOREX_SYMBOL)
                .order_by(ForexCandle.open_time.desc())
                .limit(300)
                .all()
            )
            if len(candles) < 50:
                return

            df = pd.DataFrame([{
                'open': float(c.open), 'high': float(c.high),
                'low': float(c.low),  'close': float(c.close),
                'volume': float(c.volume) if c.volume else 0,
            } for c in reversed(candles)])

            df = TechnicalIndicators.calculate_all(df)

            # Update newest 10 candles (DESC order: candles[0] = newest)
            for i, candle in enumerate(candles[:10]):
                idx = len(df) - 1 - i
                if 0 <= idx < len(df):
                    row = df.iloc[idx]
                    candle.ema_9  = row.get('ema_9')
                    candle.ema_21 = row.get('ema_21')
                    candle.ema_50 = row.get('ema_50')
                    candle.rsi_14 = row.get('rsi_14')
                    candle.atr_14 = row.get('atr_14')
                    candle.adx_14 = row.get('adx_14')
                    candle.plus_di  = row.get('plus_di')
                    candle.minus_di = row.get('minus_di')
                    candle.macd           = row.get('macd')
                    candle.macd_signal    = row.get('macd_signal')
                    candle.macd_histogram = row.get('macd_histogram')
                    candle.bollinger_upper  = row.get('bollinger_upper')
                    candle.bollinger_middle = row.get('bollinger_middle')
                    candle.bollinger_lower  = row.get('bollinger_lower')
                    candle.returns             = row.get('returns')
                    candle.log_returns         = row.get('log_returns')
                    candle.momentum_5          = row.get('momentum_5')
                    candle.momentum_10         = row.get('momentum_10')
                    candle.volatility_realized = row.get('volatility_realized')
                    candle.price_position      = row.get('price_position')
                    candle.stoch_rsi   = row.get('stoch_rsi')
                    candle.volume_delta = row.get('volume_delta')
                    candle.atf_basis   = row.get('atf_basis')
                    candle.atf_upper   = row.get('atf_upper')
                    candle.atf_lower   = row.get('atf_lower')
                    candle.atf_trend   = int(row.get('atf_trend', 0)) if pd.notna(row.get('atf_trend')) else 0
                    candle.atf_slope   = row.get('atf_slope')

            # Hurst + O-U on latest candle
            if len(df) >= 200:
                try:
                    prices = df['close']
                    latest = candles[0]
                    latest.hurst_exponent = HurstExponent.calculate(prices, window=200)
                    latest.hurst_fast     = HurstExponent.calculate_fast(prices, window=50)
                    hybrid = HurstExponent.get_hybrid_signal(prices, fast_window=50, slow_window=200)
                    latest.regime = hybrid.get('regime', 'RANDOM_WALK')
                    ou = OrnsteinUhlenbeckModel(window=200)
                    if ou.fit(prices):
                        latest.ou_deviation = ou.get_deviation(float(latest.close))
                except Exception as he:
                    logger.debug(f"[FOREX] Hurst/OU error: {he}")

            self.db.commit()
        except Exception as e:
            logger.error(f"[FOREX] indicator calc error: {e}")


def _get_candle_df(db: Session, limit: int = CANDLE_LIMIT) -> pd.DataFrame:
    """Return the last `limit` forex candles as a DataFrame."""
    rows = (
        db.query(ForexCandle)
        .filter(ForexCandle.symbol == FOREX_SYMBOL)
        .order_by(ForexCandle.open_time.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([{
        'open_time': c.open_time,
        'open': float(c.open), 'high': float(c.high),
        'low': float(c.low),  'close': float(c.close),
        'volume': float(c.volume) if c.volume else 0,
        'ema_9':  float(c.ema_9)  if c.ema_9  else None,
        'ema_21': float(c.ema_21) if c.ema_21 else None,
        'ema_50': float(c.ema_50) if c.ema_50 else None,
        'rsi_14': float(c.rsi_14) if c.rsi_14 else None,
        'atr_14': float(c.atr_14) if c.atr_14 else None,
        'adx_14': float(c.adx_14) if c.adx_14 else None,
        'macd_histogram': float(c.macd_histogram) if c.macd_histogram else None,
        'bollinger_upper':  float(c.bollinger_upper)  if c.bollinger_upper  else None,
        'bollinger_middle': float(c.bollinger_middle) if c.bollinger_middle else None,
        'bollinger_lower':  float(c.bollinger_lower)  if c.bollinger_lower  else None,
        'momentum_5': float(c.momentum_5) if c.momentum_5 else None,
        'hurst_fast':     float(c.hurst_fast)     if c.hurst_fast     else None,
        'hurst_exponent': float(c.hurst_exponent) if c.hurst_exponent else None,
    } for c in reversed(rows)])
    return df


class ForexBot:
    """
    Forex trading bot — mirrors bot.py TradingBot but dedicated to EUR/USD.
    Runs all active forex_* engines every candle close.
    """

    def __init__(self):
        self.db = SessionLocal()
        self.symbol = FOREX_SYMBOL
        self.collector = ForexDataCollector(self.db)
        self._active_engines: list = []
        self._cooldown_map: dict[str, int] = {}   # engine_name → candle countdown
        self._candle_count: int = 0
        self._is_running = False
        self._payout_rate = 0.85   # Forex binary payout (conservative)
        self._stake = 100.0        # Stake per forex trade
        self._min_confidence = 0.63

    async def start(self):
        global _forex_running
        _forex_running = True
        self._is_running = True

        # Import deriv_client (shared with R_100 bot)
        from app.services.deriv_client import deriv_client as dc

        logger.info("🌍 [FOREX] Starting EUR/USD Forex Bot...")

        # Read active forex engines from bot_settings DB
        self._load_active_engines()

        # Set tick callback (the shared deriv_client already handles ticks;
        # we piggyback via a secondary callback mechanism)
        # Since deriv_client only supports one tick_callback, we subscribe
        # separately using a new connection to avoid conflicts with R_100.
        from app.services.deriv_client import DerivWebSocketClient
        forex_ws = DerivWebSocketClient()

        if not await forex_ws.connect():
            logger.critical("[FOREX] Could not connect WebSocket for forex bot")
            return

        forex_ws.running = True
        asyncio.create_task(forex_ws.message_handler_loop())
        # Use separate Forex API token if configured, otherwise fall back to main token
        forex_token = settings.DERIV_FOREX_API_TOKEN or settings.DERIV_API_TOKEN
        await forex_ws.authorize(api_token=forex_token)

        forex_ws.set_tick_callback(self.collector.on_tick)
        await forex_ws.subscribe_to_ticks(self.symbol)

        logger.success(f"[FOREX] Subscribed to {self.symbol} ticks")

        # Main analysis loop — runs every 60s
        asyncio.create_task(self._trade_settlement_loop(forex_ws))
        await self._main_loop()

    def _load_active_engines(self):
        """Load which forex engines are toggled ON in bot_settings."""
        from app.analysis.engine_registry import list_forex_engines, get_engine, get_engine_config
        self._active_engines = []
        forex_names = list_forex_engines()
        for name in forex_names:
            try:
                row = self.db.execute(
                    sa_text(f"SELECT value FROM bot_settings WHERE key = 'engine_active_{name}'")
                ).fetchone()
                active = (row and row[0] == 'true') if row else True  # default ON
                if active:
                    engine = get_engine(name)
                    if engine:
                        self._active_engines.append((name, engine, get_engine_config(name)))
                        logger.info(f"[FOREX] Engine active: {name}")
            except Exception as e:
                logger.warning(f"[FOREX] Could not load engine {name}: {e}")

    async def _main_loop(self):
        """Main loop: analyze on every completed candle."""
        last_candle_time: datetime | None = None

        while self._is_running:
            try:
                await asyncio.sleep(10)  # Poll every 10s for a new candle

                df = _get_candle_df(self.db)
                if df.empty or len(df) < 50:
                    continue

                latest_time = df.iloc[-1]['open_time']
                if last_candle_time == latest_time:
                    continue   # Same candle — no new close

                last_candle_time = latest_time
                self._candle_count += 1
                logger.info(f"[FOREX] 🕯️ New candle #{self._candle_count} @ {latest_time}, running {len(self._active_engines)} engines")

                await self._run_engines(df)
            except Exception as e:
                logger.error(f"[FOREX] Main loop error: {e}")
                await asyncio.sleep(5)

    async def _run_engines(self, df: pd.DataFrame):
        """Run each active forex engine and execute trades on signal."""
        from app.services.deriv_client import DerivWebSocketClient
        price = _last_close

        for engine_name, engine, cfg in self._active_engines:
            try:
                # Cooldown check
                if self._cooldown_map.get(engine_name, 0) > 0:
                    self._cooldown_map[engine_name] -= 1
                    logger.debug(f"[FOREX] {engine_name}: cooldown {self._cooldown_map[engine_name]} candles remaining")
                    continue

                # Slope filter (if configured)
                slope_min = cfg.get('slope_min', 0.0)
                if slope_min > 0:
                    from app.analysis.indicators import TechnicalIndicators
                    slope_info = TechnicalIndicators.compute_ema_slope(df, cfg.get('slope_lookback', 20))
                    if slope_info and slope_info.get('abs_slope', 0) < slope_min:
                        continue

                result = engine.analyze(df, symbol=self.symbol)
                signal = result.get('final_signal', 'HOLD')
                conf   = result.get('final_confidence', 0.0)

                logger.info(f"[FOREX] 📊 {engine_name}: {signal} conf={conf:.3f} (min={self._min_confidence})")

                if signal == 'HOLD' or conf < self._min_confidence:
                    continue

                # Execute trade
                logger.info(f"[FOREX] 🎯 {engine_name}: {signal} conf={conf:.3f} price={price:.5f}")
                await self._execute_trade(engine_name, signal, conf, price)

                # Set cooldown
                cd = cfg.get('defensive', {}).get('cooldown_candles', 3)
                self._cooldown_map[engine_name] = cd

            except Exception as e:
                logger.error(f"[FOREX] Engine {engine_name} error: {e}")

    async def _execute_trade(self, engine_name: str, direction: str, confidence: float, entry_price: float):
        """Place the binary option trade on Deriv and record it."""
        from app.services.deriv_client import DerivWebSocketClient
        contract_type = "CALL" if direction == "CALL" else "PUT"
        duration_sec  = 300   # 5-minute binary for forex

        try:
            # Record in DB first
            trade = ForexTrade(
                symbol=FOREX_SYMBOL,
                contract_type=contract_type,
                direction=direction,
                entry_time=datetime.now(timezone.utc),
                entry_price=entry_price,
                stake=self._stake,
                duration_seconds=duration_sec,
                outcome="PENDING",
                layer1_signal=direction,
                layer1_confidence=confidence,
                final_confidence=confidence,
                engine_name=engine_name,
            )
            self.db.add(trade)
            self.db.commit()
            logger.success(f"[FOREX] Trade recorded: {contract_type} @ {entry_price:.5f}")
        except Exception as e:
            logger.error(f"[FOREX] Trade record error: {e}")
            self.db.rollback()

    async def _trade_settlement_loop(self, ws):
        """Check PENDING forex trades and settle them (simplified)."""
        while self._is_running:
            try:
                await asyncio.sleep(60)
                pending = (
                    self.db.query(ForexTrade)
                    .filter(ForexTrade.outcome == "PENDING")
                    .all()
                )
                now = datetime.now(timezone.utc)
                for t in pending:
                    age = (now - t.entry_time.replace(tzinfo=timezone.utc)).total_seconds()
                    if age >= t.duration_seconds:
                        # Simple settlement: compare entry vs current price
                        ep = float(t.entry_price)
                        cp = _last_close
                        won = (t.direction == "CALL" and cp > ep) or (t.direction == "PUT" and cp < ep)
                        t.outcome     = "WIN" if won else "LOSS"
                        t.exit_price  = cp
                        t.exit_time   = now
                        t.profit_loss = round(self._stake * self._payout_rate if won else -self._stake, 2)
                        logger.info(f"[FOREX] Trade settled: {t.direction} → {t.outcome} PnL={t.profit_loss}")
                self.db.commit()
            except Exception as e:
                logger.error(f"[FOREX] Settlement error: {e}")


# ─── Global instance ─────────────────────────────────────────────────────────
forex_bot = ForexBot()


async def start_forex_bot():
    """Entry point called from main.py on startup."""
    await forex_bot.start()
