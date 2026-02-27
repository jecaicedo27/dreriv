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
    "bullish_v5": {
        "module": "app.analysis.ultimate_bull_engine",
        "class": "UltimateBullEngine",
        "description": "Ultimate Bull v6: GA-optimized buy-the-dip CALL (54.4% WR)",
        "version": "6.0",
        "hurst_min": 0.35,
        "hurst_max": 0.85,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [2, 3, 4, 5, 8, 9, 10, 12, 13, 16, 17, 18, 19],
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 7,
            "dir_cooldown_candles": 0,
        },
    },
    "bear_reject_v1": {
        "module": "app.analysis.bear_rejection_engine",
        "class": "ThreeRedCrowsEngine",
        "description": "Three Red Crows v4: GA-optimized (54.6% WR, stable Jan/Feb)",
        "version": "4.0",
        "hurst_min": 0.35,
        "hurst_max": 0.85,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [0, 3, 8, 9, 12, 13, 18, 20],
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 3,
            "dir_cooldown_candles": 0,
        },
    },
    "bull_soldiers_v1": {
        "module": "app.analysis.bull_soldiers_engine",
        "class": "ThreeWhiteSoldiersEngine",
        "description": "Three White Soldiers: 3 bullish candles equal bodies stepping up",
        "version": "1.0",
        "hurst_min": 0.35,
        "hurst_max": 0.85,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [5, 7, 10, 13, 16, 22, 23],
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 3,
            "dir_cooldown_candles": 0,
        },
    },
    "malicia_v1": {
        "module": "app.analysis.malicia_engine",
        "class": "MaliciaIndigenaEngine",
        "description": "Malicia Indígena: CALL agresivo en tendencia alcista confirmada",
        "version": "1.0",
        "hurst_min": 0.50,    # Only trade trending markets
        "hurst_max": 0.90,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "blocked_hours": [],   # No hour blocks — trends happen anytime
        "duration_candles": 2, # 2 min trades (ride short waves in uptrend)
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 1,       # Aggressive: 1 candle cooldown
            "dir_cooldown_candles": 0,   # No direction cooldown (always CALL)
            "enable_wr_monitor": False,  # Aggressive strategy — engine gates are enough
            "enable_global_streak": True,   # Pauses on loss streaks — improves WR from 51.6% to 53.2%
            "enable_atr_gate": False,
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
