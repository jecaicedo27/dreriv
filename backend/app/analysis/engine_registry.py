"""
Engine Registry — Factory for Analysis Engines

Central registry of all available analysis engines.
Use get_engine(name) to instantiate the selected engine.
Use list_engines() to get available engines for UI dropdowns.
"""
from typing import Dict, Any, List
from loguru import logger


# Default defensive filter config (conservative baseline)
_DEFAULT_DEFENSIVE = {
    "wr_check_interval": 15,
    "wr_pause_threshold": 0.45,
    "wr_stop_threshold": 0.40,
    "wr_pause_candles": 30,
    "wr_min_trades_pause": 20,
    "wr_min_trades_stop": 30,
    "enable_wr_monitor": True,
    "global_streak_limit": 5,
    "global_streak_pause": 60,
    "enable_global_streak": True,
    "dir_cooldown_candles": 30,
    "dir_cooldown_losses": 3,
    "atr_lookback": 30,
    "atr_low_mult": 0.5,
    "atr_high_mult": 2.0,
    "enable_atr_gate": True,
    "cooldown_candles": 3,
}

# Registry of available engines — each with full operational presets
_ENGINES = {
    "original_v1": {
        "module": "app.analysis.layer1_engine",
        "class": "Layer1SignalEngine",
        "description": "Original: Hurst + O-U + GARCH + EMA/RSI/MACD (3-vote)",
        "version": "1.0",
        "hurst_min": 0.6,
        "hurst_max": 0.7,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [],
        "defensive": {**_DEFAULT_DEFENSIVE},
    },
    "university_v2": {
        "module": "app.analysis.university_engine",
        "class": "UniversityEngine",
        "description": "University: StochRSI + Confluencia Ponderada + Candlestick Patterns",
        "version": "2.0",
        "hurst_min": 0.6,
        "hurst_max": 0.7,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [],
        "defensive": {**_DEFAULT_DEFENSIVE},
    },
    "bullish_v3": {
        "module": "app.analysis.bullish_engine",
        "class": "BullishBreakoutEngine",
        "description": "Bullish Breakout v3 (legacy): Solo CALL en tendencias alcistas",
        "version": "3.0",
        "hurst_min": 0.6,
        "hurst_max": 0.7,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [],
        "defensive": {**_DEFAULT_DEFENSIVE},
    },
    "bullish_v4": {
        "module": "app.analysis.bullish_engine",
        "class": "BullishBreakoutEngine",
        "description": "Bullish v5: Disciplined Bull — solo CALL con alta convicción",
        "version": "5.0",
        "hurst_min": 0.52,
        "hurst_max": 0.75,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [],
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 1,         # Fast re-entry for trending bull
            "dir_cooldown_candles": 0,     # Disabled — bull only does CALL, dir cooldown unfairly penalizes
        },
    },
    "bullish_v5": {
        "module": "app.analysis.ultimate_bull_engine",
        "class": "UltimateBullEngine",
        "description": "Ultimate Bull v5: Momentum + Pullbacks (60%+ Edge)",
        "version": "5.0",
        "hurst_min": 0.60,
        "hurst_max": 0.85,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [],
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 1,
            "dir_cooldown_candles": 0,
        },
    },

    "reversal_v5": {
        "module": "app.analysis.reversal_engine",
        "class": "ReversalSniperEngine",
        "description": "Reversal Sniper v5: Mean-reversion counter-trend con edges data-mined",
        "version": "5.0",
        "hurst_min": 0.0,
        "hurst_max": 1.0,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [],
        "defensive": {**_DEFAULT_DEFENSIVE},
    },
    "bearish_v6": {
        "module": "app.analysis.bearish_engine",
        "class": "BearishBreakdownEngine",
        "description": "Bearish v7: Disciplined Bear — solo PUT confirmado",
        "version": "7.0",
        "hurst_min": 0.6,
        "hurst_max": 0.7,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [],
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 1,
            "dir_cooldown_candles": 0,     # Disabled — bear only does PUT
        },
    },

}


def get_engine(name: str = "original_v1"):
    """
    Instantiate and return the named analysis engine.
    
    Args:
        name: Engine identifier (e.g. 'original_v1', 'university_v2')
        
    Returns:
        Instance of BaseAnalysisEngine subclass
    """
    if name not in _ENGINES:
        logger.warning(f"⚠️ Unknown engine '{name}', falling back to original_v1")
        name = "original_v1"
    
    entry = _ENGINES[name]
    
    try:
        import importlib
        mod = importlib.import_module(entry["module"])
        cls = getattr(mod, entry["class"])
        engine = cls()
        logger.info(f"🔧 Engine loaded: {name} ({entry['description']})")
        return engine
    except Exception as e:
        logger.error(f"❌ Failed to load engine '{name}': {e}")
        # Fallback to original
        if name != "original_v1":
            logger.info("↩️ Falling back to original_v1")
            return get_engine("original_v1")
        raise


def get_engine_config(name: str = "original_v1") -> Dict[str, Any]:
    """
    Return the full configuration dict for an engine.
    Includes hurst_min, hurst_max, blocked_hours, defensive filters.
    """
    if name not in _ENGINES:
        name = "original_v1"
    return _ENGINES[name]


def list_engines() -> List[Dict[str, Any]]:
    """
    Return list of available engines for UI display.
    Includes full config so frontend reads from single source of truth.
    
    Returns:
        List of dicts with name, description, version, hurst, blocked_hours, defensive
    """
    return [
        {
            "name": key,
            "description": entry["description"],
            "version": entry["version"],
            "hurst_min": entry.get("hurst_min", 0.6),
            "hurst_max": entry.get("hurst_max", 0.7),
            "confidence_min": entry.get("confidence_min", 0.60),
            "confidence_max": entry.get("confidence_max", 1.0),
            "blocked_hours": entry.get("blocked_hours", []),
            "defensive": entry.get("defensive", {}),
        }
        for key, entry in _ENGINES.items()
    ]


def register_engine(name: str, module: str, cls_name: str, description: str, version: str = "1.0"):
    """
    Register a new engine at runtime.
    
    Args:
        name: Unique engine identifier
        module: Python module path (e.g. 'app.analysis.my_engine')
        cls_name: Class name within the module
        description: Human-readable description
        version: Version string
    """
    _ENGINES[name] = {
        "module": module,
        "class": cls_name,
        "description": description,
        "version": version,
    }
    logger.info(f"📦 Registered engine: {name} ({description})")
