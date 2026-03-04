"""
Forex REST API — frxEURUSD
All routes under /api/forex/*
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text as sa_text
from datetime import datetime, timezone
from typing import Optional, List
from loguru import logger

from app.core.database import get_db, SessionLocal
from app.models.models import ForexCandle, ForexTrade, ForexBotState

router = APIRouter(prefix="/api/forex", tags=["forex"])

FOREX_SYMBOL = "frxEURUSD"
TF           = "60s"


# ─────────────────────────────────────────────────────────────────────────────
#  CANDLE DATA
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/candles")
def get_forex_candles(
    limit: int  = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """Return last N forex candles (OHLCV)."""
    rows = (
        db.query(ForexCandle)
        .filter(ForexCandle.symbol == FOREX_SYMBOL, ForexCandle.timeframe == TF)
        .order_by(ForexCandle.open_time.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "time":   int(c.open_time.timestamp()) if c.open_time else None,
            "open":   float(c.open),
            "high":   float(c.high),
            "low":    float(c.low),
            "close":  float(c.close),
            "volume": float(c.volume) if c.volume else 0,
        }
        for c in reversed(rows)
    ]


@router.get("/candles-with-indicators")
def get_forex_candles_with_indicators(
    limit: int  = Query(300, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """Return forex candles including EMA, BB, RSI, ATR etc. for chart overlays."""
    rows = (
        db.query(ForexCandle)
        .filter(ForexCandle.symbol == FOREX_SYMBOL, ForexCandle.timeframe == TF)
        .order_by(ForexCandle.open_time.desc())
        .limit(limit)
        .all()
    )

    def _f(v):
        return float(v) if v is not None else None

    return [
        {
            "time":   int(c.open_time.timestamp()),
            "open":   _f(c.open), "high": _f(c.high),
            "low":    _f(c.low),  "close": _f(c.close),
            "volume": _f(c.volume) if c.volume else 0,
            # EMAs
            "ema_9":  _f(c.ema_9),
            "ema_21": _f(c.ema_21),
            "ema_50": _f(c.ema_50),
            # Oscillators
            "rsi_14":    _f(c.rsi_14),
            "atr_14":    _f(c.atr_14),
            "adx_14":    _f(c.adx_14),
            "macd_histogram": _f(c.macd_histogram),
            # Bollinger
            "bollinger_upper":  _f(c.bollinger_upper),
            "bollinger_middle": _f(c.bollinger_middle),
            "bollinger_lower":  _f(c.bollinger_lower),
            # Statistical
            "hurst_fast":     _f(c.hurst_fast),
            "hurst_exponent": _f(c.hurst_exponent),
            "regime":         c.regime,
            "momentum_5":     _f(c.momentum_5),
        }
        for c in reversed(rows)
    ]


# ─────────────────────────────────────────────────────────────────────────────
#  TRADES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trades")
def get_forex_trades(
    limit: int  = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Return last N forex trades."""
    trades = (
        db.query(ForexTrade)
        .order_by(ForexTrade.entry_time.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id":           str(t.id),
            "symbol":       t.symbol,
            "direction":    t.direction,
            "entry_time":   t.entry_time.isoformat() if t.entry_time else None,
            "entry_price":  float(t.entry_price),
            "stake":        float(t.stake),
            "duration":     t.duration_seconds,
            "exit_time":    t.exit_time.isoformat() if t.exit_time else None,
            "exit_price":   float(t.exit_price) if t.exit_price else None,
            "profit_loss":  float(t.profit_loss) if t.profit_loss else None,
            "outcome":      t.outcome,
            "confidence":   float(t.final_confidence) if t.final_confidence else None,
            "engine_name":  t.engine_name,
        }
        for t in trades
    ]


@router.get("/trades/stats")
def get_forex_trade_stats(db: Session = Depends(get_db)):
    """Aggregated win/loss/PnL for the forex bot."""
    trades = db.query(ForexTrade).filter(ForexTrade.outcome.in_(["WIN", "LOSS"])).all()
    wins   = [t for t in trades if t.outcome == "WIN"]
    losses = [t for t in trades if t.outcome == "LOSS"]
    total_pnl = sum(float(t.profit_loss or 0) for t in trades)
    wr = len(wins) / len(trades) if trades else 0

    return {
        "total_trades": len(trades),
        "wins":         len(wins),
        "losses":       len(losses),
        "win_rate":     round(wr, 4),
        "total_pnl":    round(total_pnl, 2),
        "pending":      db.query(ForexTrade).filter(ForexTrade.outcome == "PENDING").count(),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  ENGINE CONTROLS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/engines")
def get_forex_engines(db: Session = Depends(get_db)):
    """Return list of forex engines with their active status."""
    from app.analysis.engine_registry import list_forex_engines, _ENGINES
    engines = []
    for name in list_forex_engines():
        cfg = _ENGINES.get(name, {})
        try:
            row = db.execute(
                sa_text(f"SELECT value FROM bot_settings WHERE key = 'engine_active_{name}'")
            ).fetchone()
            active = (row[0] == 'true') if row else True
        except Exception:
            active = True
        engines.append({
            "name":        name,
            "description": cfg.get("description", ""),
            "version":     cfg.get("version", "1.0"),
            "active":      active,
            "duration_candles": cfg.get("duration_candles", 5),
            "hurst_min":   cfg.get("hurst_min", 0.52),
        })
    return engines


@router.post("/engines/{engine_name}/toggle")
def toggle_forex_engine(engine_name: str, active: bool = Query(...), db: Session = Depends(get_db)):
    """Toggle a forex engine ON or OFF."""
    from app.analysis.engine_registry import list_forex_engines
    if engine_name not in list_forex_engines():
        return {"error": f"Engine '{engine_name}' is not a forex engine"}

    key = f"engine_active_{engine_name}"
    val = "true" if active else "false"
    try:
        existing = db.execute(sa_text(f"SELECT value FROM bot_settings WHERE key = '{key}'")).fetchone()
        if existing:
            db.execute(sa_text(f"UPDATE bot_settings SET value = '{val}' WHERE key = '{key}'"))
        else:
            db.execute(sa_text(f"INSERT INTO bot_settings (key, value) VALUES ('{key}', '{val}')"))
        db.commit()
        logger.info(f"[FOREX] Engine {engine_name} set to {val}")
        return {"engine": engine_name, "active": active}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  BOT STATUS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/bot-status")
def get_forex_bot_status(db: Session = Depends(get_db)):
    """Forex bot running state and today stats."""
    from app.forex_bot import _forex_running, _last_close
    today = datetime.now(timezone.utc).date()
    today_trades = (
        db.query(ForexTrade)
        .filter(ForexTrade.entry_time >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
        .all()
    )
    wins   = [t for t in today_trades if t.outcome == "WIN"]
    losses = [t for t in today_trades if t.outcome == "LOSS"]
    pnl    = sum(float(t.profit_loss or 0) for t in today_trades if t.outcome != "PENDING")
    wr     = len(wins) / (len(wins) + len(losses)) if (wins or losses) else 0

    # Deriv account balance
    deriv_balance = None
    deriv_account_type = None
    try:
        bot_state = db.query(ForexBotState).first()
        if bot_state:
            deriv_balance = float(bot_state.balance)
            deriv_account_type = "DEMO"
    except Exception:
        pass

    return {
        "running":       _forex_running,
        "symbol":        FOREX_SYMBOL,
        "current_price": round(_last_close, 5),
        "deriv_balance": deriv_balance,
        "deriv_account_type": deriv_account_type,
        "today": {
            "trades":  len(today_trades),
            "wins":    len(wins),
            "losses":  len(losses),
            "pending": len([t for t in today_trades if t.outcome == "PENDING"]),
            "pnl":     round(pnl, 2),
            "win_rate": round(wr, 4),
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
#  HISTORICAL DATA DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/download-history")
async def download_forex_history(
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Download historical EUR/USD candles from Deriv into forex_candles table.
    Runs in background and returns immediately."""
    import asyncio
    asyncio.create_task(_run_forex_history_download(days))
    return {"status": "started", "days": days, "symbol": FOREX_SYMBOL}


async def _run_forex_history_download(days: int):
    """Background download of historical forex data from Deriv."""
    from app.services.deriv_client import DerivWebSocketClient
    from datetime import timedelta
    import time

    db = SessionLocal()
    try:
        ws = DerivWebSocketClient()
        if not await ws.connect():
            logger.error("[FOREX] Could not connect for history download")
            return
        ws.running = True
        asyncio.create_task(ws.message_handler_loop())
        await ws.authorize()

        # Fetch historical candles (Deriv returns up to 5000 per request)
        end_epoch   = int(time.time())
        start_epoch = end_epoch - days * 24 * 3600

        resp = await ws.send_request({
            "ticks_history": FOREX_SYMBOL,
            "adjust_start_time": 1,
            "count": min(days * 24 * 60, 5000),
            "end": str(end_epoch),
            "start": str(start_epoch),
            "granularity": 60,
            "style": "candles",
        })

        candles_data = resp.get("candles", [])
        if not candles_data:
            logger.warning(f"[FOREX] No historical data returned: {resp}")
            return

        inserted = 0
        for c in candles_data:
            open_time = datetime.fromtimestamp(int(c['epoch']), tz=timezone.utc)
            # Skip if already exists
            exists = db.query(ForexCandle).filter(
                ForexCandle.symbol == FOREX_SYMBOL,
                ForexCandle.open_time == open_time,
            ).first()
            if exists:
                continue
            fc = ForexCandle(
                symbol=FOREX_SYMBOL,
                timeframe=TF,
                open_time=open_time,
                close_time=open_time.replace(second=59),
                open=float(c['open']),
                high=float(c['high']),
                low=float(c['low']),
                close=float(c['close']),
                volume=0,
            )
            db.add(fc)
            inserted += 1
            if inserted % 500 == 0:
                db.commit()

        db.commit()
        logger.success(f"[FOREX] Inserted {inserted} historical candles for {FOREX_SYMBOL}")

        # Now compute indicators for all downloaded candles
        await _compute_indicators_bulk(db)
    except Exception as e:
        logger.error(f"[FOREX] History download error: {e}")
    finally:
        db.close()
        await ws.stop()


async def _compute_indicators_bulk(db: Session):
    """Compute indicators for all forex_candles that lack ema_21."""
    try:
        rows = (
            db.query(ForexCandle)
            .filter(ForexCandle.symbol == FOREX_SYMBOL)
            .order_by(ForexCandle.open_time.asc())
            .all()
        )
        if len(rows) < 50:
            return

        df = pd.DataFrame([{
            'open': float(c.open), 'high': float(c.high),
            'low': float(c.low),   'close': float(c.close),
            'volume': float(c.volume) if c.volume else 0,
        } for c in rows])

        import pandas as pd
        df = TechnicalIndicators.calculate_all(df)

        for i, candle in enumerate(rows):
            if i >= len(df):
                break
            row = df.iloc[i]
            candle.ema_9  = row.get('ema_9')
            candle.ema_21 = row.get('ema_21')
            candle.ema_50 = row.get('ema_50')
            candle.rsi_14 = row.get('rsi_14')
            candle.atr_14 = row.get('atr_14')
            candle.adx_14 = row.get('adx_14')
            candle.macd_histogram  = row.get('macd_histogram')
            candle.bollinger_upper  = row.get('bollinger_upper')
            candle.bollinger_middle = row.get('bollinger_middle')
            candle.bollinger_lower  = row.get('bollinger_lower')
            candle.momentum_5 = row.get('momentum_5')
            candle.returns    = row.get('returns')
            candle.log_returns = row.get('log_returns')
            candle.adx_14     = row.get('adx_14')
            candle.stoch_rsi  = row.get('stoch_rsi')
            candle.plus_di    = row.get('plus_di')
            candle.minus_di   = row.get('minus_di')

            if i % 200 == 0:
                db.commit()

        # Hurst on full series for last 200+ rows
        from app.analysis.hurst import HurstExponent
        if len(df) >= 200:
            prices = df['close']
            for j, candle in enumerate(rows):
                if j < 200:
                    continue
                sub = prices.iloc[j-200:j]
                candle.hurst_fast = HurstExponent.calculate_fast(sub, window=50)

        db.commit()
        logger.success(f"[FOREX] Indicators computed for {len(rows)} candles")
    except Exception as e:
        logger.error(f"[FOREX] Bulk indicator error: {e}")



from app.analysis.indicators import TechnicalIndicators


# ─────────────────────────────────────────────────────────────────────────────
#  FOREX SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/simulation/dates")
def get_forex_sim_dates(db: Session = Depends(get_db)):
    """Available dates in the forex_candles table (30+ candles/day)."""
    rows = db.execute(sa_text("""
        SELECT DATE(open_time AT TIME ZONE 'America/Bogota') AS trade_date,
               COUNT(*) AS candle_count,
               MIN(open_time) AS first_candle,
               MAX(open_time) AS last_candle
        FROM forex_candles
        WHERE symbol = 'frxEURUSD'
        GROUP BY DATE(open_time AT TIME ZONE 'America/Bogota')
        HAVING COUNT(*) >= 30
        ORDER BY trade_date DESC
    """)).fetchall()
    return {"dates": [
        {"date": str(r.trade_date), "candle_count": int(r.candle_count),
         "first": str(r.first_candle), "last": str(r.last_candle)}
        for r in rows
    ], "total": len(rows)}


@router.get("/simulation/candles")
def get_forex_sim_candles(
    date: str = Query(..., description="YYYY-MM-DD"),
    index: int = Query(0),
    db: Session = Depends(get_db),
):
    """Return forex candles for a simulation date, up to `index` candles revealed."""
    rows = db.execute(sa_text("""
        SELECT open_time, open, high, low, close,
               rsi_14, ema_9, ema_21, ema_50, atr_14, adx_14,
               macd, macd_signal, macd_histogram,
               bollinger_upper, bollinger_middle, bollinger_lower,
               hurst_fast, hurst_exponent, regime, momentum_5, stoch_rsi
        FROM forex_candles
        WHERE symbol = 'frxEURUSD'
          AND DATE(open_time AT TIME ZONE 'America/Bogota') = :d
        ORDER BY open_time ASC
    """), {"d": date}).fetchall()

    total = len(rows)
    reveal = rows[:index] if index > 0 else rows

    def _s(v): return float(v) if v is not None else None

    candles = [{"time": int(r.open_time.timestamp()),
                "open": _s(r.open), "high": _s(r.high), "low": _s(r.low), "close": _s(r.close),
                "rsi_14": _s(r.rsi_14), "ema_9": _s(r.ema_9), "ema_21": _s(r.ema_21),
                "ema_50": _s(r.ema_50), "atr_14": _s(r.atr_14), "adx_14": _s(r.adx_14),
                "macd_histogram": _s(r.macd_histogram),
                "bollinger_upper": _s(r.bollinger_upper), "bollinger_middle": _s(r.bollinger_middle),
                "bollinger_lower": _s(r.bollinger_lower),
                "hurst_fast": _s(r.hurst_fast), "regime": r.regime, "momentum_5": _s(r.momentum_5)}
               for r in reveal]
    return {"candles": candles, "total": total, "shown": len(candles)}


@router.post("/simulation/run")
def run_forex_simulation(
    date: str   = Query(..., description="YYYY-MM-DD"),
    engine_name: str = Query("forex_trend_v1"),
    stake: float = Query(100.0),
    payout: float = Query(0.85),
    duration_candles: int = Query(5),
    db: Session = Depends(get_db),
):
    """Run a full forex simulation for a given date using the selected engine.
    Returns candle-by-candle results, trades, and summary stats."""
    import pandas as pd
    from app.analysis.engine_registry import get_engine, _ENGINES
    from app.simulation.trading_core import TradingCore

    # Load 300 lookback + date candles from forex_candles
    rows = db.execute(sa_text("""
        SELECT open_time, open, high, low, close, volume,
               rsi_14, ema_9, ema_21, ema_50, atr_14, adx_14,
               macd, macd_signal, macd_histogram,
               bollinger_upper, bollinger_middle, bollinger_lower,
               hurst_fast, hurst_exponent, regime, momentum_5, stoch_rsi,
               plus_di, minus_di, returns, log_returns, momentum_10,
               atf_basis, atf_upper, atf_lower, atf_trend, atf_slope
        FROM forex_candles
        WHERE symbol = 'frxEURUSD'
          AND open_time < (
              SELECT MIN(open_time) FROM forex_candles
              WHERE symbol = 'frxEURUSD'
                AND DATE(open_time AT TIME ZONE 'America/Bogota') = :d
          ) + INTERVAL '300 minutes'
          AND open_time >= (
              SELECT MIN(open_time) FROM forex_candles
              WHERE symbol = 'frxEURUSD'
                AND DATE(open_time AT TIME ZONE 'America/Bogota') = :d
          ) - INTERVAL '300 minutes'
        ORDER BY open_time ASC
    """), {"d": date}).fetchall()

    if not rows:
        return {"error": "No data for this date in forex_candles. Download history first."}

    # Convert to DataFrame
    cols = ["open_time", "open", "high", "low", "close", "volume",
            "rsi_14", "ema_9", "ema_21", "ema_50", "atr_14", "adx_14",
            "macd", "macd_signal", "macd_histogram",
            "bollinger_upper", "bollinger_middle", "bollinger_lower",
            "hurst_fast", "hurst_exponent", "regime", "momentum_5", "stoch_rsi",
            "plus_di", "minus_di", "returns", "log_returns", "momentum_10",
            "atf_basis", "atf_upper", "atf_lower", "atf_trend", "atf_slope"]
    full_df = pd.DataFrame([dict(zip(cols, r)) for r in rows])
    for col in ["open", "high", "low", "close", "volume", "rsi_14", "ema_9", "ema_21", "ema_50",
                "atr_14", "adx_14", "macd_histogram", "bollinger_upper", "bollinger_middle",
                "bollinger_lower", "hurst_fast", "hurst_exponent", "momentum_5", "stoch_rsi"]:
        if col in full_df.columns:
            full_df[col] = pd.to_numeric(full_df[col], errors='coerce')

    # Find day slice (Bogota = UTC-5)
    full_df["date_bogota"] = pd.to_datetime(full_df["open_time"]).dt.tz_convert("America/Bogota").dt.date
    import datetime as _dt
    target_date = _dt.date.fromisoformat(date)
    day_indices = full_df[full_df["date_bogota"] == target_date].index.tolist()

    if not day_indices:
        return {"error": f"No candles on {date} in loaded data."}

    engine = get_engine(engine_name)
    cfg    = _ENGINES.get(engine_name, {})
    hurst_min  = cfg.get("hurst_min", 0.52)
    hurst_max  = cfg.get("hurst_max", 0.90)
    slope_min  = cfg.get("slope_min", 0.0)
    slope_lookback = cfg.get("slope_lookback", 20)
    min_conf   = cfg.get("confidence_min", 0.63)

    # Simulation loop
    trades = []
    candle_results = []
    balance  = 10000.0
    cooldown = 0
    pending_trade = None   # {exit_idx, direction, stake}

    for i, day_idx in enumerate(day_indices):
        # Context window for analysis: all candles up to and including this one
        ctx = full_df.iloc[:day_idx + 1].copy()
        ctx_len = len(ctx)
        if ctx_len < 50:
            candle_results.append({"index": i, "signal": "HOLD", "confidence": 0, "reason": "warm-up"})
            continue

        # Settle pending trade
        if pending_trade and i >= pending_trade["exit_idx"]:
            entry_close = pending_trade["entry_close"]
            exit_close  = float(full_df.iloc[day_idx]["close"])
            won = (pending_trade["direction"] == "CALL" and exit_close > entry_close) or \
                  (pending_trade["direction"] == "PUT"  and exit_close < entry_close)
            pnl = round(stake * payout if won else -stake, 2)
            balance = round(balance + pnl, 2)
            trades.append({
                "candle":    pending_trade["entry_i"],
                "direction": pending_trade["direction"],
                "confidence": pending_trade["confidence"],
                "entry_price": entry_close,
                "exit_price":  exit_close,
                "outcome":  "WIN" if won else "LOSS",
                "pnl":      pnl,
                "balance":  balance,
            })
            pending_trade = None

        # Cooldown
        if cooldown > 0:
            cooldown -= 1
            candle_results.append({"index": i, "signal": "COOLDOWN", "confidence": 0})
            continue

        # Analyze
        try:
            result = TradingCore.analyze(
                engine, ctx, symbol="frxEURUSD",
                hurst_min=hurst_min, hurst_max=hurst_max,
                slope_min=slope_min, slope_lookback=slope_lookback,
            )
        except Exception as e:
            candle_results.append({"index": i, "signal": "ERROR", "confidence": 0, "reason": str(e)})
            continue

        signal = result.get("final_signal", "HOLD")
        conf   = result.get("final_confidence", 0.0)
        reasoning = result.get("reasoning", "")

        candle_result = {"index": i, "signal": signal, "confidence": round(conf, 4),
                         "reason": reasoning[:120] if reasoning else ""}
        candle_results.append(candle_result)

        if signal in ("CALL", "PUT") and conf >= min_conf and pending_trade is None:
            entry_close = float(full_df.iloc[day_idx]["close"])
            exit_idx    = i + duration_candles
            pending_trade = {
                "entry_i": i, "direction": signal, "confidence": conf,
                "entry_close": entry_close, "exit_idx": exit_idx
            }
            cooldown = cfg.get("defensive", {}).get("cooldown_candles", 3)

    # Compute summary
    wins   = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    total_pnl = sum(t["pnl"] for t in trades)
    wr = len(wins) / len(trades) if trades else 0

    return {
        "date": date, "engine": engine_name,
        "summary": {
            "total_trades": len(trades),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(wr, 4),
            "total_pnl": round(total_pnl, 2),
            "final_balance": round(balance, 2),
            "profit_factor": round(sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses)) if losses else 0, 2),
        },
        "trades": trades,
        "candle_results": candle_results[-len(day_indices):],  # only day candles
    }

