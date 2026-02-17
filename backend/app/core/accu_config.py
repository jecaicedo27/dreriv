"""
Configuration for Accumulators Bot (Boom 1000 Index)
Completely separate from the main Rise/Fall bot config.
"""


class AccuConfig:
    """Accumulator bot settings"""

    # Symbol
    SYMBOL = "BOOM1000"

    # Contract parameters
    STAKE = 10.0               # USD - stake por contrato
    GROWTH_RATE = 0.02         # 2% growth rate (range: 0.01 - 0.05)
    MAX_GROWTH_RATE = 0.05     # Maximum allowed growth rate
    MIN_GROWTH_RATE = 0.01     # Minimum growth rate
    TAKE_PROFIT = 50.0         # USD - take profit automático

    # Risk management
    MAX_OPEN_CONTRACTS = 1     # Solo 1 contrato ACCU abierto a la vez
    COOLDOWN_AFTER_LOSS = 30   # Segundos de cooldown tras barrera tocada
    MAX_CONSECUTIVE_LOSSES = 5 # Máximo de pérdidas consecutivas antes de pausa larga
    LONG_COOLDOWN = 300        # 5 min de pausa tras MAX_CONSECUTIVE_LOSSES

    # Analysis parameters
    SPIKE_LOOKBACK = 100       # Cuántos ticks atrás revisar para spikes
    SPIKE_THRESHOLD_SIGMA = 4  # Cambio > 4σ = spike detectado
    VOLATILITY_WINDOW = 50     # Ventana de ticks para calcular volatilidad rolling
    MIN_TICKS_BEFORE_ENTRY = 200  # Mínimo de ticks recolectados antes de operar

    # Volatility thresholds for entry
    MAX_VOLATILITY_FOR_ENTRY = 0.7   # Solo entrar si vol normalizada < 0.7x (zona verde/calma)
    MIN_TICKS_SINCE_SPIKE = 30       # Mínimo de ticks desde último spike para entrar

    # Growth rate adaptation based on volatility
    # Low vol → higher growth rate, High vol → lower growth rate
    GROWTH_RATE_ADAPTIVE = True
    GROWTH_RATE_LOW_VOL = 0.03    # 3% cuando volatilidad baja
    GROWTH_RATE_NORMAL = 0.02     # 2% condiciones normales
    GROWTH_RATE_HIGH_VOL = 0.01   # 1% cuando volatilidad alta

    # Tick collection interval
    ANALYSIS_INTERVAL = 1  # Analizar cada tick (Accumulators es tick-by-tick)

    # Logging
    LOG_PREFIX = "🎰 [ACCU]"
