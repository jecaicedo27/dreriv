"""
Endpoint to expose latest Layer 1 analysis metrics
"""
from fastapi import APIRouter, Depends
from starlette.responses import Response
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Candle
from app.analysis.layer1_engine import Layer1SignalEngine
from app.analysis.indicators import TechnicalIndicators
import pandas as pd
import json
import numpy as np
import traceback as tb
from datetime import datetime
from decimal import Decimal

# Custom JSON encoder that handles numpy types
import math

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            val = float(obj)
            if math.isinf(val) or math.isnan(val):
                return None
            return val
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (pd.Timestamp, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def _sanitize(obj):
    """Replace Infinity/NaN with None recursively so JSON is valid."""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


router = APIRouter()

@router.get("/analysis-metrics")
async def get_analysis_metrics(db: Session = Depends(get_db)):
    """
    Get latest Layer 1 analysis metrics for dashboard visualization
    """
    try:
        # Fetch recent candles
        candles = db.query(Candle).order_by(Candle.open_time.desc()).limit(200).all()
        
        if len(candles) < 50:
            return {
                "status": "insufficient_data",
                "message": f"Only {len(candles)} candles available, need at least 50"
            }
        
        # Reverse to chronological order
        candles.reverse()
        
        # Convert to DataFrame
        df = pd.DataFrame([{
            'open_time': c.open_time,
            'open': float(c.open),
            'high': float(c.high),
            'low': float(c.low),
            'close': float(c.close),
            'volume': float(c.volume) if c.volume else 0
        } for c in candles])
        
        # Use the configured engine (same as live bot)
        from app.core.config import get_settings
        from app.analysis.engine_registry import get_engine, get_engine_config
        from app.simulation.trading_core import TradingCore
        _settings = get_settings()
        engine_name = _settings.ENGINE_NAME
        engine_cfg = get_engine_config(engine_name)
        engine = get_engine(engine_name)
        
        hurst_min = engine_cfg.get('hurst_min', 0.6)
        hurst_max = engine_cfg.get('hurst_max', 0.7)
        blocked_hours = engine_cfg.get('blocked_hours', [])
        
        # ===== ALWAYS calculate Hurst & O-U independently for dashboard display =====
        from app.analysis.hurst import HurstExponent
        from app.analysis.ornstein_uhlenbeck import OrnsteinUhlenbeckModel
        
        hurst_signal = {"hurst": 0.5, "regime": "UNKNOWN", "interpretation": ""}
        try:
            hurst_signal = HurstExponent.get_signal(df['close'], window=200)
        except Exception as e:
            logging.debug(f"Hurst calc error: {e}")
        
        ou_signal = {"signal": "HOLD", "deviation": 0, "confidence": 0}
        try:
            ou_model = OrnsteinUhlenbeckModel(window=200)
            ou_model.fit(df['close'].values)
            current_price = float(df['close'].iloc[-1])
            ou_signal = ou_model.get_signal(current_price, threshold=2.0)
        except Exception as e:
            logging.debug(f"O-U calc error: {e}")
        
        # ===== COMPUTE TECHNICAL INDICATORS (separate from engine) =====
        df = TechnicalIndicators.calculate_all(df)
        indicator_values = TechnicalIndicators.get_latest_values(df)
        
        # ===== ENGINE SIGNAL via TradingCore (consumes pre-calculated indicators) =====
        result = TradingCore.analyze(
            engine=engine,
            df=df,
            symbol='R_100',
            use_groq=False,
            hurst_min=hurst_min,
            hurst_max=hurst_max,
        )
        
        # Check if current hour is blocked (Colombia time)
        from datetime import timezone, timedelta
        col_tz = timezone(timedelta(hours=-5))
        col_hour = datetime.now(col_tz).hour
        hour_blocked = col_hour in blocked_hours
        
        # Map TradingCore output to display
        effective_signal = result.get('action', result.get('final_signal', 'HOLD'))
        effective_confidence = result.get('confidence', result.get('final_confidence', 0))
        effective_reasoning = result.get('reasoning', '')
        
        if hour_blocked:
            effective_signal = 'BLOCKED'
            effective_confidence = 0
            effective_reasoning = f'🚫 Hora {col_hour:02d} bloqueada por motor {engine_name}'
        
        response = {
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "current_price": result.get('entry_price', float(df['close'].iloc[-1])),
            
            # Engine info
            "engine": {
                "name": engine_name,
                "hurst_min": hurst_min,
                "hurst_max": hurst_max,
                "blocked_hours": blocked_hours,
                "current_hour_col": col_hour,
                "hour_blocked": hour_blocked,
            },
            
            # Hurst metrics (calculated independently — always live)
            "hurst": {
                "value": hurst_signal.get('hurst', 0.5),
                "regime": hurst_signal.get('regime', 'UNKNOWN'),
                "trend_strength": round(abs(float(hurst_signal.get('hurst', 0.5)) - 0.5), 3),
                "strength_threshold": 0.10,
                "strength_sufficient": abs(float(hurst_signal.get('hurst', 0.5)) - 0.5) >= 0.10,
                "interpretation": hurst_signal.get('interpretation', '')
            },
            
            # O-U metrics (calculated independently — always live)
            "ou": {
                "signal": ou_signal.get('signal', 'HOLD'),
                "deviation": ou_signal.get('deviation', 0),
                "confidence": ou_signal.get('confidence', 0),
                "half_life": ou_signal.get('half_life'),
                "theta": ou_signal.get('theta'),
                "reason": ou_signal.get('reason', '')
            },
            
            # GARCH metrics
            "garch": {
                "regime": result.get('garch_signal', {}).get('regime', 'N/A'),
                "current_vol": result.get('garch_signal', {}).get('current_vol'),
                "forecast_vol": result.get('garch_signal', {}).get('forecast_vol'),
                "stake_multiplier": result.get('garch_signal', {}).get('stake_multiplier', 1.0)
            },
            
            # Final signal (with engine filter applied)
            "signal": {
                "direction": effective_signal,
                "confidence": effective_confidence,
                "contract_type": result.get('contract_type'),
                "duration": result.get('duration', 300),
                "reasoning": effective_reasoning,
                "raw_signal": result.get('final_signal', 'HOLD'),
                "raw_confidence": result.get('final_confidence', 0),
            },
            
            # Technical indicators (calculated independently — always live)
            "indicators": indicator_values
        }
        
        # Use custom encoder to handle numpy types, and sanitize Infinity/NaN
        json_str = json.dumps(_sanitize(response), cls=NumpyEncoder)
        return Response(content=json_str, media_type="application/json")
        
    except Exception as e:
        import logging
        logging.error(f"analysis-metrics error: {e}\n{tb.format_exc()}")
        return Response(
            content=json.dumps({"status": "error", "message": str(e)}),
            media_type="application/json",
            status_code=500
        )
