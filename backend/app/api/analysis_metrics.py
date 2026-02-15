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
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (pd.Timestamp, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


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
        
        # Run Layer 1 analysis
        engine = Layer1SignalEngine()
        result = engine.analyze(df, 'R_100')
        
        response = {
            "status": "ok",
            "timestamp": result.get('timestamp'),
            "current_price": result.get('current_price'),
            
            # Hurst metrics
            "hurst": {
                "value": result['hurst_signal'].get('hurst', 0.5),
                "regime": result['hurst_signal'].get('regime', 'UNKNOWN'),
                "trend_strength": round(abs(float(result['hurst_signal'].get('hurst', 0.5)) - 0.5), 3),
                "strength_threshold": 0.10,
                "strength_sufficient": abs(float(result['hurst_signal'].get('hurst', 0.5)) - 0.5) >= 0.10,
                "interpretation": result['hurst_signal'].get('interpretation', '')
            },
            
            # O-U metrics
            "ou": {
                "signal": result['ou_signal'].get('signal', 'HOLD'),
                "deviation": result['ou_signal'].get('deviation', 0),
                "confidence": result['ou_signal'].get('confidence', 0),
                "half_life": result['ou_signal'].get('half_life'),
                "theta": result['ou_signal'].get('theta'),
                "reason": result['ou_signal'].get('reason', '')
            },
            
            # GARCH metrics
            "garch": {
                "regime": result['garch_signal'].get('regime', 'UNKNOWN'),
                "current_vol": result['garch_signal'].get('current_vol'),
                "forecast_vol": result['garch_signal'].get('forecast_vol'),
                "stake_multiplier": result['garch_signal'].get('stake_multiplier', 1.0)
            },
            
            # Final signal
            "signal": {
                "direction": result.get('final_signal', 'HOLD'),
                "confidence": result.get('final_confidence', 0),
                "contract_type": result.get('contract_type'),
                "duration": result.get('duration', 300),
                "reasoning": result.get('reasoning', '')
            },
            
            # Technical indicators
            "indicators": {
                "rsi_14": result['indicators'].get('rsi_14'),
                "ema_9": result['indicators'].get('ema_9'),
                "ema_21": result['indicators'].get('ema_21'),
                "macd": result['indicators'].get('macd'),
                "macd_signal": result['indicators'].get('macd_signal')
            }
        }
        
        # Use custom encoder to handle numpy types
        json_str = json.dumps(response, cls=NumpyEncoder)
        return Response(content=json_str, media_type="application/json")
        
    except Exception as e:
        import logging
        logging.error(f"analysis-metrics error: {e}\n{tb.format_exc()}")
        return Response(
            content=json.dumps({"status": "error", "message": str(e)}),
            media_type="application/json",
            status_code=500
        )
