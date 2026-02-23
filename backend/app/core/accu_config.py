"""
Configuration for Accumulators Bot (Boom 1000 Index)
Completely separate from the main Rise/Fall bot config.
"""


class AccuConfig:
    """Accumulator bot settings — Boom 1000 Index"""

    # Symbol
    SYMBOL = "BOOM1000"

    # Contract parameters
    STAKE = 100.0              # USD - stake por contrato
    GROWTH_RATE = 0.01         # 1% growth rate — wider barriers, safer
    MAX_GROWTH_RATE = 0.05     # Maximum allowed growth rate
    MIN_GROWTH_RATE = 0.01     # Minimum growth rate
    TAKE_PROFIT = 50.0         # USD - take profit automático

    # Risk management
    MAX_OPEN_CONTRACTS = 1     # Solo 1 contrato ACCU abierto a la vez
    COOLDOWN_AFTER_LOSS = 30   # Segundos de cooldown tras barrera tocada
    MAX_CONSECUTIVE_LOSSES = 5 # Máximo de pérdidas consecutivas antes de pausa larga
    LONG_COOLDOWN = 300        # 5 min de pausa tras MAX_CONSECUTIVE_LOSSES

    # Analysis parameters (adjusted for Vol100 — smoother price action)
    SPIKE_LOOKBACK = 100       # Cuántos ticks atrás revisar para movimientos bruscos
    SPIKE_THRESHOLD_SIGMA = 3  # Cambio > 3σ = movimiento fuerte (Vol100 es más suave)
    VOLATILITY_WINDOW = 50     # Ventana de ticks para calcular volatilidad rolling
    MIN_TICKS_BEFORE_ENTRY = 50   # Pre-loaded candles give enough history

    # Volatility thresholds for entry
    MAX_VOLATILITY_FOR_ENTRY = 1.5   # Enter if vol < 1.5x (avoid only extreme spikes 3x+)
    MIN_TICKS_SINCE_SPIKE = 100      # Wait 100 ticks after any spike before entering

    # Growth rate adaptation based on volatility
    GROWTH_RATE_ADAPTIVE = True
    GROWTH_RATE_LOW_VOL = 0.02    # 2% cuando volatilidad baja
    GROWTH_RATE_NORMAL = 0.01     # 1% condiciones normales
    GROWTH_RATE_HIGH_VOL = 0.01   # 1% cuando volatilidad alta

    # Tick collection interval
    ANALYSIS_INTERVAL = 1  # Analizar cada tick (Accumulators es tick-by-tick)

    # Logging
    LOG_PREFIX = "🎰 [ACCU]"

