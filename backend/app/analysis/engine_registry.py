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
        "slope_min": 0.0,        # No slope — buy-the-dip works in lateral markets too
        "slope_lookback": 20,    # Candles for linear regression window
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 7,
            "dir_cooldown_candles": 0,
        },
    },
    "bearish_v5": {
        "module": "app.analysis.ultimate_bear_engine",
        "class": "UltimateBearEngine",
        "description": "Ultimate Bear v5: Sell-the-rally PUT (mirror of bullish_v5)",
        "version": "5.0",
        "hurst_min": 0.35,
        "hurst_max": 0.85,
        "confidence_min": 0.60,
        "confidence_max": 1.0,
        "slope_min": 0.0,
        "slope_lookback": 20,
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 3,   # Sweep-optimized (was 7)
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
        "slope_min": 0.05,
        "slope_lookback": 20,
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
        "slope_min": 0.05,
        "slope_lookback": 20,
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 3,
            "dir_cooldown_candles": 0,
        },
    },

    # ============================================================
    #  FOREX ENGINES — EUR/USD (frxEURUSD) — prefixed forex_
    # ============================================================
    "forex_trend_v1": {
        "module": "app.analysis.forex_trend_engine",
        "class": "ForexTrendEngine",
        "description": "Forex Trend v1: EMA 9/21/50 alignment + sesión Londres/NY (EUR/USD)",
        "version": "1.0",
        "hurst_min": 0.52,
        "hurst_max": 0.90,
        "confidence_min": 0.63,
        "confidence_max": 1.0,
        "slope_min": 0.0,        # Forex uses session filter, not slope
        "slope_lookback": 20,
        "duration_candles": 5,
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 3,
            "dir_cooldown_candles": 0,
            "enable_wr_monitor": True,
            "enable_global_streak": True,
            "enable_atr_gate": False,
        },
    },
    "forex_smart_money_v1": {
        "module": "app.analysis.forex_smart_money_engine",
        "class": "ForexSmartMoneyEngine",
        "description": "Forex SMC v1: ChoCh + OB/FVG en EUR/USD con sesión activa",
        "version": "1.0",
        "hurst_min": 0.52,
        "hurst_max": 0.90,
        "confidence_min": 0.63,
        "confidence_max": 1.0,
        "slope_min": 0.0,
        "slope_lookback": 20,
        "duration_candles": 5,
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 5,
            "dir_cooldown_candles": 0,
            "enable_wr_monitor": False,
            "enable_global_streak": True,
            "enable_atr_gate": False,
        },
    },
    "forex_session_v1": {
        "module": "app.analysis.forex_session_engine",
        "class": "ForexSessionEngine",
        "description": "Forex Session v1: London Opening Range Breakout (EUR/USD)",
        "version": "1.0",
        "hurst_min": 0.50,
        "hurst_max": 0.90,
        "confidence_min": 0.63,
        "confidence_max": 1.0,
        "slope_min": 0.0,
        "slope_lookback": 20,
        "duration_candles": 5,
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 10,
            "dir_cooldown_candles": 0,
            "enable_wr_monitor": False,
            "enable_global_streak": True,
            "enable_atr_gate": False,
        },
    },
    "forex_buydip_v1": {
        "module": "app.analysis.forex_buydip_engine",
        "class": "ForexBuyDipEngine",
        "description": "Forex Buy-Dip v1: Buy-the-dip CALL expert (EUR/USD)",
        "version": "1.0",
        "hurst_min": 0.50,
        "hurst_max": 0.90,
        "confidence_min": 0.62,
        "confidence_max": 1.0,
        "slope_min": 0.0,
        "slope_lookback": 20,
        "duration_candles": 5,
        "defensive": {
            **_DEFAULT_DEFENSIVE,
            "cooldown_candles": 7,
            "dir_cooldown_candles": 0,
            "enable_wr_monitor": True,
            "enable_global_streak": True,
            "enable_atr_gate": False,
        },
    },
}


def list_forex_engines() -> list:
    """Return names of all forex engines (prefixed with forex_)."""
    return [k for k in _ENGINES if k.startswith("forex_")]


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
