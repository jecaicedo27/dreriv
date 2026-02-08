# PROMPT DE DESARROLLO — BOT DE AUTOTRADING PARA ÍNDICES SINTÉTICOS DE DERIV
# VERSIÓN 2.0 — OPTIMIZADA PARA MÁXIMA RENTABILIDAD

## Para: Equipo de Desarrollo Antigravity
## Cliente: Popping Boba International — Jhonk
## Fecha: Febrero 2026
## Versión: 2.0 (Optimizada)

---

# CONTEXTO GENERAL DEL PROYECTO

Necesitamos desarrollar un bot de autotrading de última generación para operar índices sintéticos de Deriv.com (Volatility 75, Volatility 100, Crash 1000, Crash 500, Boom 1000, Boom 500). El bot funciona 24/7 en un VPS dedicado. La inteligencia se basa en un sistema híbrido de tres capas: (1) Modelos estadísticos especializados por tipo de instrumento, (2) Búsqueda de patrones por similitud vectorial con pgvector, y (3) Groq API con modelo premium como capa final de decisión y filtrado. El sistema incluye un framework de A/B testing integrado para medir continuamente si cada componente aporta rentabilidad real, un motor de detección de cambios de régimen, y un dashboard web profesional en tiempo real.

[MEJORADO] Se agrega la arquitectura de tres capas con A/B testing. El original trataba a Groq como cerebro único; ahora cada capa tiene una función específica y se mide independientemente. Esto permite identificar qué componente genera el edge real.

---

# 1. ARQUITECTURA GENERAL DEL SISTEMA [MEJORADO]

## 1.1 Stack Tecnológico

- **Backend Principal:** Python 3.12+ con FastAPI (async nativo para WebSocket de Deriv)
- **Motor de IA:** Groq API — modelo `llama-3.3-70b-versatile` (plan premium, inferencia ultra rápida ~200 tokens/s)
- **Modelos Estadísticos:** NumPy, SciPy, statsmodels (GARCH, Poisson, Ornstein-Uhlenbeck)
- **Base de Datos:** PostgreSQL 16+ con extensiones:
  - `pgvector` — búsqueda de similitud vectorial para detección de patrones de velas
  - `TimescaleDB` — series de tiempo optimizadas para datos de ticks y velas
- **Cache en Memoria:** Redis — para estado del bot, últimos ticks, cola de señales, y cache de decisiones recientes
- **Dashboard Frontend:** Next.js 14+ con React, Tailwind CSS, y Recharts/TradingView Lightweight Charts
- **WebSocket en Tiempo Real:** Socket.IO para comunicación dashboard ↔ backend
- **Broker API:** Deriv WebSocket API v3 (`wss://ws.derivws.com/websockets/v3`)
- **Containerización:** Docker + Docker Compose para deployment en VPS
- **Monitoreo:** Prometheus + Grafana para métricas del sistema
- **Notificaciones:** Telegram Bot API para alertas de trades y errores críticos

## 1.2 Diagrama de Arquitectura

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           VPS SERVIDOR 24/7                              │
│                                                                          │
│  ┌──────────────┐    ┌───────────────────────────────────────────────┐   │
│  │  Dashboard    │◄──►│            FastAPI Backend                    │   │
│  │  Next.js      │    │                                               │   │
│  │  Socket.IO    │    │  ┌─────────────┐    ┌──────────────────┐     │   │
│  └──────────────┘    │  │ Market Data  │    │  Trading Engine   │     │   │
│                       │  │ Collector    │    │  (Ejecución)      │     │   │
│  ┌──────────────┐    │  └──────┬──────┘    └───────▲──────────┘     │   │
│  │  Telegram     │◄──│         │                    │                 │   │
│  │  Alerts       │    │  ┌─────▼────────────────────┤                 │   │
│  └──────────────┘    │  │    CAPA 1: Análisis       │                 │   │
│                       │  │    Estadístico Mecánico   │                 │   │
│  ┌──────────────┐    │  │  - Regime Detector (HMM)  │                 │   │
│  │  PostgreSQL   │◄──│  │  - GARCH Volatility       │                 │   │
│  │  + pgvector   │    │  │  - Poisson Spikes         │                 │   │
│  │  + TimescaleDB│───►│  │  - O-U Mean Reversion    │                 │   │
│  └──────────────┘    │  │  - Structure Analysis      │                 │   │
│                       │  └─────────────┬─────────────┘                 │   │
│  ┌──────────────┐    │  ┌─────────────▼─────────────┐                 │   │
│  │  Redis        │◄──►│  │    CAPA 2: Pattern Match  │                 │   │
│  └──────────────┘    │  │    pgvector Similarity     │                 │   │
│                       │  │  + Temporal Decay          │                 │   │
│                       │  │  + Regime-Aware Filter     │                 │   │
│                       │  └─────────────┬─────────────┘                 │   │
│  ┌──────────────┐    │  ┌─────────────▼─────────────┐                 │   │
│  │  A/B Testing  │◄──│  │    CAPA 3: Groq AI        │─────────────────┘   │
│  │  Framework    │    │  │    Decision + Filter      │                     │
│  └──────────────┘    │  │  + Devil's Advocate        │                     │
│                       │  │  + Meta-Confidence         │                     │
│                       │  └───────────────────────────┘                     │
│                       └───────────────────────────────────────────────┘     │
│                                                                              │
│                      ┌──────────────────────┐                               │
│                      │  Deriv WebSocket API │ ◄── Internet                   │
│                      └──────────────────────┘                               │
└──────────────────────────────────────────────────────────────────────────┘
```

[MEJORADO] Se separa la arquitectura en 3 capas explícitas. Cada capa genera una señal independiente que se puede medir. Se agrega Regime Detector (HMM), modelos estadísticos especializados, temporal decay en pgvector, y meta-confidence en Groq.

---

# 2. MÓDULO DE CONEXIÓN A DERIV API

## 2.1 Autenticación y Conexión WebSocket

Implementar un cliente WebSocket persistente con reconexión automática que se conecte a `wss://ws.derivws.com/websockets/v3`. El cliente debe:

- Autenticarse con API token de Deriv (almacenado en variables de entorno, nunca hardcoded)
- Mantener heartbeat con ping/pong cada 30 segundos
- Reconectar automáticamente con backoff exponencial (1s, 2s, 4s, 8s, máx 60s)
- Manejar múltiples suscripciones simultáneas (ticks de varios instrumentos)
- Loggear todos los eventos de conexión/desconexión
- [NUEVO] Implementar circuit breaker: si hay 5+ reconexiones en 10 minutos, pausar el bot y alertar por Telegram
- [NUEVO] Medir latencia de cada mensaje recibido para detectar degradación de conexión

## 2.2 Suscripción a Instrumentos Sintéticos

El bot debe suscribirse a los siguientes instrumentos simultáneamente:

| Instrumento | Símbolo Deriv | Tipo | Prioridad |
|-------------|---------------|------|-----------|
| Volatility 75 Index | R_75 | Volatility | ALTA |
| Volatility 100 Index | R_100 | Volatility | ALTA |
| Crash 1000 Index | CRASH1000 | Crash/Boom | ALTA |
| Boom 1000 Index | BOOM1000 | Crash/Boom | ALTA |
| Crash 500 Index | CRASH500 | Crash/Boom | MEDIA |
| Boom 500 Index | BOOM500 | Crash/Boom | MEDIA |
| Volatility 50 Index | R_50 | Volatility | BAJA |
| Volatility 25 Index | R_25 | Volatility | BAJA |

[MEJORADO] Se sube prioridad de CRASH1000 y BOOM1000 a ALTA porque son los instrumentos con mayor edge estadístico explotable (spikes predecibles por distribución de Poisson).

## 2.3 Tipos de Contratos a Operar

Implementar soporte para los siguientes tipos de contrato, priorizados por edge estadístico:

| Tipo de Contrato | Instrumentos | Edge Esperado | Prioridad |
|------------------|-------------|---------------|-----------|
| Rise/Fall (CALL/PUT) | Todos | Moderado — depende de análisis direccional | ALTA |
| Higher/Lower | Volatility | Alto — permite definir barrera precisa | ALTA |
| Even/Odd | Volatility | Bajo — 50/50 teórico, pero explotable con análisis de dígitos | MEDIA |
| Over/Under | Volatility | Moderado — edge con análisis de distribución de último dígito | MEDIA |
| Matches/Differs | Volatility | Bajo — solo con ventaja estadística demostrada | BAJA |

[MEJORADO] Se agrega tabla de prioridad por edge esperado. El original listaba todos los contratos igual. Rise/Fall y Higher/Lower deben ser el foco principal porque es donde el análisis técnico y estadístico aporta más valor.

## 2.4 Ejemplo de Flujo de Conexión

```python
# Referencia de flujo — implementar con manejo completo de errores
import asyncio
import websockets
import json
from datetime import datetime

DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

class DerivClient:
    def __init__(self):
        self.ws = None
        self.reconnect_count = 0
        self.last_tick_time = None
        self.latency_buffer = []
    
    async def connect(self):
        async with websockets.connect(DERIV_WS_URL) as ws:
            self.ws = ws
            
            # Autorizar
            await ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
            auth_response = json.loads(await ws.recv())
            
            if "error" in auth_response:
                raise AuthenticationError(auth_response["error"]["message"])
            
            # Suscribirse a ticks
            await ws.send(json.dumps({"ticks": "R_75", "subscribe": 1}))
            
            # Suscribirse a velas OHLC (múltiples timeframes)
            for granularity in [60, 300, 900, 3600]:  # 1m, 5m, 15m, 1h
                await ws.send(json.dumps({
                    "ticks_history": "R_75",
                    "adjust_start_time": 1,
                    "count": 1000,
                    "end": "latest",
                    "granularity": granularity,
                    "style": "candles",
                    "subscribe": 1
                }))
            
            async for message in ws:
                received_at = datetime.utcnow()
                data = json.loads(message)
                
                # [NUEVO] Medir latencia
                if 'tick' in data:
                    tick_epoch = data['tick']['epoch']
                    latency_ms = (received_at.timestamp() - tick_epoch) * 1000
                    self.latency_buffer.append(latency_ms)
                
                await self.process_market_data(data)
```

---

# 3. BASE DE DATOS — POSTGRESQL + PGVECTOR + TIMESCALEDB [MEJORADO]

## 3.1 Schema de Base de Datos

### Tabla: raw_ticks (TimescaleDB hypertable)

```sql
CREATE TABLE raw_ticks (
    id BIGSERIAL,
    symbol VARCHAR(20) NOT NULL,
    tick_time TIMESTAMPTZ NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    epoch BIGINT NOT NULL,
    -- [NUEVO] Tracking de dígitos para estrategia Even/Odd
    last_digit SMALLINT GENERATED ALWAYS AS (
        CAST(SUBSTRING(CAST(price AS TEXT) FROM '.$') AS SMALLINT)
    ) STORED,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('raw_ticks', 'tick_time');
CREATE INDEX idx_ticks_symbol_time ON raw_ticks (symbol, tick_time DESC);
-- [NUEVO] Índice para análisis de dígitos
CREATE INDEX idx_ticks_digit ON raw_ticks (symbol, last_digit, tick_time DESC);

SELECT add_retention_policy('raw_ticks', INTERVAL '30 days');
```

### Tabla: candles (TimescaleDB hypertable) [MEJORADO]

```sql
CREATE TABLE candles (
    id BIGSERIAL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    close_time TIMESTAMPTZ NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) DEFAULT 0,
    tick_count INTEGER DEFAULT 0,
    
    -- Indicadores técnicos precalculados
    ema_9 DECIMAL(20, 8),
    ema_21 DECIMAL(20, 8),
    ema_50 DECIMAL(20, 8),
    ema_200 DECIMAL(20, 8),  -- [NUEVO] Agregada EMA 200 para z-score
    rsi_14 DECIMAL(10, 4),
    atr_14 DECIMAL(20, 8),
    bollinger_upper DECIMAL(20, 8),
    bollinger_middle DECIMAL(20, 8),
    bollinger_lower DECIMAL(20, 8),
    macd_line DECIMAL(20, 8),
    macd_signal DECIMAL(20, 8),
    macd_histogram DECIMAL(20, 8),
    
    -- Features para análisis estadístico
    body_size DECIMAL(20, 8),
    upper_wick DECIMAL(20, 8),
    lower_wick DECIMAL(20, 8),
    is_bullish BOOLEAN,
    body_to_range_ratio DECIMAL(5, 4),
    
    -- [NUEVO] Features avanzados para vectorización mejorada
    returns DECIMAL(20, 8),              -- (close - prev_close) / prev_close
    log_returns DECIMAL(20, 8),          -- ln(close / prev_close)
    momentum_5 DECIMAL(20, 8),           -- close / close_5_periods_ago - 1
    momentum_10 DECIMAL(20, 8),          -- close / close_10_periods_ago - 1
    volatility_realized DECIMAL(20, 8),  -- std(returns) sobre últimas 20 velas
    volume_delta DECIMAL(20, 8),         -- tick_count / avg(tick_count, 20)
    price_position DECIMAL(5, 4),        -- (close - low_20) / (high_20 - low_20) [0-1]
    
    -- Smart Money Concepts (adaptado a sintéticos)
    is_order_block BOOLEAN DEFAULT FALSE,
    is_fair_value_gap BOOLEAN DEFAULT FALSE,
    is_break_of_structure BOOLEAN DEFAULT FALSE,
    is_change_of_character BOOLEAN DEFAULT FALSE,
    liquidity_level DECIMAL(20, 8),
    
    -- [NUEVO] Detección de régimen de mercado
    regime VARCHAR(20),  -- 'trending_up', 'trending_down', 'ranging_tight', 'ranging_wide', 'volatile_expansion'
    regime_confidence DECIMAL(5, 4),
    regime_duration INTEGER,  -- cuántas velas lleva en este régimen
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timeframe, open_time)
);

SELECT create_hypertable('candles', 'open_time');
CREATE INDEX idx_candles_lookup ON candles (symbol, timeframe, open_time DESC);
CREATE INDEX idx_candles_regime ON candles (symbol, timeframe, regime);
```

[MEJORADO] Se agregan 7 features nuevos: returns, log_returns, momentum (5 y 10), volatilidad realizada, volume delta, y price position. Estos capturan dinámica que el OHLC crudo no captura. También se agrega detección de régimen directamente en la vela.

### Tabla: candle_patterns (pgvector) [MEJORADO]

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE candle_patterns (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    pattern_time TIMESTAMPTZ NOT NULL,
    
    -- [MEJORADO] Vector con 12 features por vela × 30 velas = 360 dimensiones
    -- Features: [open_norm, high_norm, low_norm, close_norm, rsi_norm, atr_norm,
    --            returns, momentum_5, volatility_realized, volume_delta, price_position, regime_encoded]
    pattern_vector vector(360),
    
    -- Metadata del patrón
    pattern_type VARCHAR(50),
    market_phase VARCHAR(20),
    
    -- [NUEVO] Contexto del régimen de mercado cuando se formó el patrón
    regime_at_formation VARCHAR(20),
    regime_confidence_at_formation DECIMAL(5, 4),
    
    -- Resultado real después del patrón
    outcome_direction VARCHAR(4),
    outcome_pips DECIMAL(20, 8),
    outcome_duration_minutes INTEGER,
    outcome_max_adverse DECIMAL(20, 8),
    -- [NUEVO] Resultado por tipo de contrato
    outcome_rise_fall_result VARCHAR(4),   -- 'won' o 'lost' si se hubiera jugado Rise/Fall
    outcome_higher_lower_result VARCHAR(4), -- ídem para Higher/Lower
    
    -- Confiabilidad calculada con decaimiento temporal
    pattern_quality_score DECIMAL(5, 4),
    -- [NUEVO] Decaimiento temporal del patrón
    last_used_at TIMESTAMPTZ,
    times_matched INTEGER DEFAULT 0,
    times_correct INTEGER DEFAULT 0,
    -- [NUEVO] Score ajustado por tiempo: quality_score * decay_factor
    -- decay_factor = exp(-lambda * days_since_creation)
    -- lambda = 0.01 → vida media ≈ 69 días
    temporal_decay_lambda DECIMAL(8, 6) DEFAULT 0.01,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- [MEJORADO] Índice HNSW con parámetros optimizados para 360 dimensiones
CREATE INDEX idx_pattern_vector ON candle_patterns 
    USING hnsw (pattern_vector vector_cosine_ops)
    WITH (m = 24, ef_construction = 128);

CREATE INDEX idx_patterns_symbol_tf ON candle_patterns (symbol, timeframe);
CREATE INDEX idx_patterns_type ON candle_patterns (pattern_type);
CREATE INDEX idx_patterns_outcome ON candle_patterns (outcome_direction);
CREATE INDEX idx_patterns_regime ON candle_patterns (regime_at_formation);
CREATE INDEX idx_patterns_quality ON candle_patterns (pattern_quality_score DESC);
```

[MEJORADO] Cambios críticos para rentabilidad:
- Vector ampliado de 140 a 360 dimensiones (12 features × 30 velas). Las 7 features originales omitían información dinámica crucial (momentum, volatility regime, returns).
- Ventana ampliada de 20 a 30 velas para capturar contexto más amplio.
- Se agrega decaimiento temporal exponencial: patrones recientes pesan más. Lambda 0.01 da vida media de ~69 días, después de eso el patrón vale menos de la mitad.
- Se registra el régimen de mercado al momento de formación para filtrar patrones por régimen actual.
- HNSW parámetros ajustados: m=24 y ef_construction=128 para mejor recall con vectores más grandes.

### Tabla: trades [MEJORADO]

```sql
CREATE TABLE trades (
    id BIGSERIAL PRIMARY KEY,
    trade_id VARCHAR(100) UNIQUE,
    symbol VARCHAR(20) NOT NULL,
    contract_type VARCHAR(20) NOT NULL,
    
    -- Parámetros del trade
    stake DECIMAL(20, 8) NOT NULL,
    entry_price DECIMAL(20, 8),
    exit_price DECIMAL(20, 8),
    barrier DECIMAL(20, 8),
    duration INTEGER,
    duration_unit VARCHAR(5),
    
    -- [NUEVO] Sizing info
    kelly_fraction DECIMAL(5, 4),        -- fracción de Kelly usada
    effective_stake_pct DECIMAL(5, 4),   -- % real del balance apostado
    
    -- Resultado
    status VARCHAR(20) DEFAULT 'open',
    payout DECIMAL(20, 8),
    profit_loss DECIMAL(20, 8),
    
    -- Contexto de la decisión
    groq_analysis TEXT,
    groq_confidence DECIMAL(5, 4),
    groq_reasoning TEXT,
    signal_source VARCHAR(50),
    market_phase VARCHAR(20),
    
    -- [NUEVO] Señales por capa (para A/B testing)
    layer1_signal VARCHAR(10),           -- señal del análisis mecánico
    layer1_confidence DECIMAL(5, 4),
    layer2_signal VARCHAR(10),           -- señal de pgvector
    layer2_confidence DECIMAL(5, 4),
    layer3_signal VARCHAR(10),           -- señal de Groq
    layer3_confidence DECIMAL(5, 4),
    layers_agreement INTEGER,            -- cuántas capas estuvieron de acuerdo (1-3)
    
    -- [NUEVO] Decision path (para debugging de rentabilidad)
    decision_path VARCHAR(20),           -- 'mechanical_only', 'pgvector_confirmed', 'groq_override', 'full_agreement'
    
    -- [NUEVO] Contexto de régimen
    regime_at_entry VARCHAR(20),
    regime_confidence_at_entry DECIMAL(5, 4),
    
    -- [NUEVO] Control de correlación
    correlated_open_trades INTEGER,      -- cuántos trades correlacionados estaban abiertos al momento
    
    -- Patrones que llevaron a la decisión
    matched_pattern_ids BIGINT[],
    pattern_similarity_scores DECIMAL(5,4)[],
    
    -- Indicadores al momento de entrada
    rsi_at_entry DECIMAL(10, 4),
    atr_at_entry DECIMAL(20, 8),
    ema_alignment VARCHAR(20),
    zscore_at_entry DECIMAL(10, 4),     -- [NUEVO]
    
    -- Timestamps
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_symbol ON trades (symbol, opened_at DESC);
CREATE INDEX idx_trades_status ON trades (status);
CREATE INDEX idx_trades_profit ON trades (profit_loss);
CREATE INDEX idx_trades_path ON trades (decision_path);
CREATE INDEX idx_trades_regime ON trades (regime_at_entry);
CREATE INDEX idx_trades_layers ON trades (layers_agreement);
```

### Tabla: bot_state

```sql
CREATE TABLE bot_state (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO bot_state (key, value) VALUES
    ('trading_mode', '"demo"'),
    ('is_active', 'true'),
    ('daily_loss_limit_pct', '8.0'),
    ('max_concurrent_trades', '3'),
    ('current_balance', '0'),
    ('daily_pnl', '0'),
    ('total_trades_today', '0'),
    ('consecutive_losses', '0'),
    ('max_consecutive_losses_allowed', '4'),
    -- [NUEVO] Estado de confianza meta en Groq
    ('groq_meta_confidence', '1.0'),
    ('groq_recent_accuracy_20', '0.5'),
    -- [NUEVO] Estado del régimen por instrumento
    ('current_regimes', '{}'),
    -- [NUEVO] Flag de A/B testing
    ('ab_test_active', 'false'),
    ('ab_test_mode', '"full_system"');
```

### Tabla: groq_decisions_log [MEJORADO]

```sql
CREATE TABLE groq_decisions_log (
    id BIGSERIAL PRIMARY KEY,
    request_timestamp TIMESTAMPTZ DEFAULT NOW(),
    symbol VARCHAR(20),
    timeframe VARCHAR(5),
    
    -- Request a Groq
    prompt_sent TEXT,
    context_data JSONB,
    similar_patterns JSONB,
    
    -- Response de Groq
    response_text TEXT,
    decision VARCHAR(10),
    confidence DECIMAL(5, 4),
    reasoning TEXT,
    -- [NUEVO] Devil's advocate
    counter_arguments TEXT,             -- razones para NO entrar que Groq identificó
    risk_factors TEXT,                  -- factores de riesgo mencionados
    
    -- Performance
    response_time_ms INTEGER,
    tokens_used INTEGER,
    model_used VARCHAR(50),
    
    -- Resultado posterior
    was_correct BOOLEAN,
    actual_outcome TEXT,
    
    -- [NUEVO] Comparación con capas anteriores
    mechanical_would_have_traded BOOLEAN,
    mechanical_direction VARCHAR(10),
    pgvector_direction VARCHAR(10),
    pgvector_win_rate DECIMAL(5, 4),
    -- ¿Groq contradijo a las otras capas?
    groq_overrode_mechanical BOOLEAN,
    groq_override_was_correct BOOLEAN   -- ¿Tenía razón al contradecir?
);

CREATE INDEX idx_groq_log_time ON groq_decisions_log (request_timestamp DESC);
CREATE INDEX idx_groq_log_decision ON groq_decisions_log (decision, confidence);
CREATE INDEX idx_groq_log_override ON groq_decisions_log (groq_overrode_mechanical, groq_override_was_correct);
```

### [NUEVO] Tabla: regime_history

```sql
CREATE TABLE regime_history (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    regime VARCHAR(20) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_minutes INTEGER,
    confidence DECIMAL(5, 4),
    
    -- Performance del bot durante este régimen
    trades_during_regime INTEGER DEFAULT 0,
    win_rate_during_regime DECIMAL(5, 4),
    pnl_during_regime DECIMAL(20, 8),
    
    -- Mejor estrategia durante este régimen
    best_strategy VARCHAR(50),
    best_strategy_win_rate DECIMAL(5, 4)
);

CREATE INDEX idx_regime_symbol ON regime_history (symbol, started_at DESC);
CREATE INDEX idx_regime_type ON regime_history (regime);
```

[NUEVO] Esta tabla permite al sistema aprender qué estrategias funcionan en qué regímenes. Si el régimen actual es "ranging_tight" y históricamente mean_reversion tiene 72% win rate en ese régimen vs 45% de momentum, el sistema automáticamente prioriza mean_reversion.

### [NUEVO] Tabla: ab_test_results

```sql
CREATE TABLE ab_test_results (
    id BIGSERIAL PRIMARY KEY,
    test_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    
    -- Grupo A: sistema completo (3 capas)
    group_a_trades INTEGER DEFAULT 0,
    group_a_wins INTEGER DEFAULT 0,
    group_a_pnl DECIMAL(20, 8) DEFAULT 0,
    group_a_profit_factor DECIMAL(10, 4),
    
    -- Grupo B: sistema sin Groq (solo capas 1+2)
    group_b_trades INTEGER DEFAULT 0,
    group_b_wins INTEGER DEFAULT 0,
    group_b_pnl DECIMAL(20, 8) DEFAULT 0,
    group_b_profit_factor DECIMAL(10, 4),
    
    -- Grupo C: solo capa mecánica
    group_c_trades INTEGER DEFAULT 0,
    group_c_wins INTEGER DEFAULT 0,
    group_c_pnl DECIMAL(20, 8) DEFAULT 0,
    group_c_profit_factor DECIMAL(10, 4),
    
    -- Resultado
    winner VARCHAR(1),  -- 'A', 'B', o 'C'
    statistical_significance DECIMAL(5, 4),  -- p-value
    
    notes TEXT
);
```

[NUEVO] Framework de A/B testing integrado. Cada trade registra qué habría hecho cada capa independientemente. Después de N trades se puede calcular cuál sistema es más rentable con significancia estadística.

### [NUEVO] Tabla: spike_events (específica para Crash/Boom)

```sql
CREATE TABLE spike_events (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    spike_time TIMESTAMPTZ NOT NULL,
    spike_direction VARCHAR(4) NOT NULL,  -- 'down' para Crash, 'up' para Boom
    spike_magnitude DECIMAL(20, 8),        -- magnitud del spike en pips
    ticks_since_previous_spike INTEGER,    -- ticks desde el spike anterior
    price_before DECIMAL(20, 8),
    price_after DECIMAL(20, 8),
    
    -- [NUEVO] Contexto pre-spike para análisis predictivo
    pre_spike_volatility DECIMAL(20, 8),
    pre_spike_trend VARCHAR(10),
    pre_spike_rsi DECIMAL(10, 4),
    pre_spike_ticks_velocity DECIMAL(20, 8)  -- velocidad de cambio de precio pre-spike
);

CREATE INDEX idx_spikes_symbol ON spike_events (symbol, spike_time DESC);
CREATE INDEX idx_spikes_interval ON spike_events (symbol, ticks_since_previous_spike);
```

[NUEVO] Tabla dedicada a spikes de Crash/Boom. Almacena cada spike con su contexto pre-spike para entrenar el modelo de Poisson y detectar patrones que preceden a los spikes.

---

# 4. MOTOR DE ANÁLISIS — PIPELINE DE PROCESAMIENTO [MEJORADO]

## 4.1 Paso 1: Recolección y Construcción de Velas

El Market Data Collector debe:

- Recibir cada tick en tiempo real vía WebSocket de Deriv
- Almacenar el tick crudo en `raw_ticks`
- Construir velas OHLC para múltiples timeframes simultáneamente: 1m, 5m, 15m, 1h
- Al cerrar cada vela, calcular automáticamente todos los indicadores técnicos
- Calcular TODOS los features de la vela (incluidos los nuevos: returns, momentum, volatility realized, volume delta, price position)
- Ejecutar detección de régimen (ver 4.4.5)
- Almacenar la vela completa en `candles`
- [NUEVO] Para Crash/Boom: detectar spikes en tiempo real y almacenar en `spike_events`

[MEJORADO] Se reduce a 4 timeframes (1m, 5m, 15m, 1h) eliminando 4h. Los sintéticos no tienen sesiones de mercado, así que los ciclos de 4h no tienen significado real. 1h es suficiente como timeframe superior.

### 4.1.1 [NUEVO] Detección de Spikes en Tiempo Real (Crash/Boom)

```python
# Lógica de detección de spikes
# Un spike es un movimiento de precio > X desviaciones estándar en 1-3 ticks

class SpikeDetector:
    def __init__(self, symbol, window=100):
        self.symbol = symbol
        self.ticks_buffer = []
        self.last_spike_tick_count = 0
        self.total_ticks_since_spike = 0
        
    def on_tick(self, price):
        self.ticks_buffer.append(price)
        self.total_ticks_since_spike += 1
        
        if len(self.ticks_buffer) < 10:
            return None
        
        # Calcular cambio porcentual del último tick
        pct_change = abs(price - self.ticks_buffer[-2]) / self.ticks_buffer[-2]
        
        # Calcular desviación estándar de cambios recientes
        recent_changes = [abs(self.ticks_buffer[i] - self.ticks_buffer[i-1]) / self.ticks_buffer[i-1] 
                         for i in range(max(1, len(self.ticks_buffer)-100), len(self.ticks_buffer)-1)]
        std_change = np.std(recent_changes) if recent_changes else 0
        
        # Spike = cambio > 4 desviaciones estándar
        if std_change > 0 and pct_change > 4 * std_change:
            spike = {
                "symbol": self.symbol,
                "direction": "down" if price < self.ticks_buffer[-2] else "up",
                "magnitude": pct_change,
                "ticks_since_previous": self.total_ticks_since_spike
            }
            self.total_ticks_since_spike = 0
            return spike
        
        return None
```

## 4.2 Paso 2: Feature Extraction y Vectorización [MEJORADO]

Cuando se completa una nueva vela:

1. Tomar las últimas **30 velas** del mismo timeframe y símbolo
2. Normalizar usando **z-score normalization** (no min-max, porque z-score es más robusto a outliers y preserva la escala relativa entre features):
   ```python
   feature_norm = (feature - mean(feature, window=100)) / std(feature, window=100)
   ```
3. Crear vector de **360 dimensiones** (30 velas × 12 features por vela):
   - Features por vela: `[open_norm, high_norm, low_norm, close_norm, rsi_norm, atr_norm, returns, momentum_5, volatility_realized, volume_delta, price_position, regime_encoded]`
   - `regime_encoded`: trending_up=1.0, trending_down=-1.0, ranging_tight=0.0, ranging_wide=0.2, volatile_expansion=0.5
4. Almacenar el vector en `candle_patterns` con metadata del régimen actual

[MEJORADO] Cambios críticos:
- 30 velas en vez de 20: captura contexto más amplio sin demasiado ruido
- Z-score en vez de min-max: más robusto, no se distorsiona por un solo outlier
- 12 features en vez de 7: agrega momentum, volatility realized, volume delta, price position, y regime encoding. Estos son los features que más discriminan entre patrones rentables y no rentables según la literatura de ML aplicado a trading.
- Regime encoding: permite que pgvector busque patrones que ocurrieron en regímenes SIMILARES al actual.

## 4.3 Paso 3: Búsqueda de Patrones Similares con pgvector [MEJORADO]

Para cada nuevo vector de patrón, buscar los patrones históricos más similares CON decaimiento temporal y filtro de régimen:

```sql
-- Buscar los 15 patrones más similares con decaimiento temporal
-- El score final = similarity * temporal_decay * quality_score
SELECT 
    cp.id,
    cp.pattern_type,
    cp.outcome_direction,
    cp.outcome_pips,
    cp.outcome_max_adverse,
    cp.pattern_quality_score,
    cp.regime_at_formation,
    1 - (cp.pattern_vector <=> $1) as raw_similarity,
    
    -- [NUEVO] Decaimiento temporal exponencial
    EXP(-cp.temporal_decay_lambda * EXTRACT(EPOCH FROM (NOW() - cp.created_at)) / 86400) as temporal_decay,
    
    -- [NUEVO] Score compuesto final
    (1 - (cp.pattern_vector <=> $1)) 
    * EXP(-cp.temporal_decay_lambda * EXTRACT(EPOCH FROM (NOW() - cp.created_at)) / 86400)
    * COALESCE(cp.pattern_quality_score, 0.5)
    as composite_score
    
FROM candle_patterns cp
WHERE cp.symbol = $2
  AND cp.timeframe = $3
  AND cp.outcome_direction IS NOT NULL
  -- [NUEVO] Filtrar por régimen compatible
  AND cp.regime_at_formation IN ($4, $5)  -- régimen actual + régimen neutro
  -- [NUEVO] Excluir patrones muy viejos con quality score bajo
  AND (cp.pattern_quality_score > 0.3 OR cp.created_at > NOW() - INTERVAL '14 days')
ORDER BY composite_score DESC
LIMIT 15;
```

Analizar los resultados con lógica mejorada:

```python
def analyze_similar_patterns(patterns):
    if len(patterns) < 5:
        return {"signal": "INSUFFICIENT_DATA", "confidence": 0.0}
    
    # Solo considerar patrones con similarity > 0.70
    strong_patterns = [p for p in patterns if p['raw_similarity'] > 0.70]
    
    if len(strong_patterns) < 3:
        return {"signal": "WEAK_MATCH", "confidence": 0.0}
    
    # Calcular win rate ponderado por composite_score
    total_weight = sum(p['composite_score'] for p in strong_patterns)
    weighted_up = sum(p['composite_score'] for p in strong_patterns if p['outcome_direction'] == 'up')
    weighted_down = sum(p['composite_score'] for p in strong_patterns if p['outcome_direction'] == 'down')
    
    up_probability = weighted_up / total_weight
    down_probability = weighted_down / total_weight
    
    # [NUEVO] Calcular ratio de riesgo/recompensa promedio
    avg_pips_up = np.mean([p['outcome_pips'] for p in strong_patterns if p['outcome_direction'] == 'up'] or [0])
    avg_pips_down = np.mean([abs(p['outcome_pips']) for p in strong_patterns if p['outcome_direction'] == 'down'] or [0])
    avg_adverse = np.mean([p['outcome_max_adverse'] for p in strong_patterns] or [0])
    
    # Señal solo si hay dominancia clara (>62%)
    if up_probability > 0.62:
        return {
            "signal": "UP",
            "confidence": min(up_probability, 0.95),
            "win_rate": up_probability,
            "avg_pips": avg_pips_up,
            "avg_adverse": avg_adverse,
            "sample_size": len(strong_patterns)
        }
    elif down_probability > 0.62:
        return {
            "signal": "DOWN",
            "confidence": min(down_probability, 0.95),
            "win_rate": down_probability,
            "avg_pips": avg_pips_down,
            "avg_adverse": avg_adverse,
            "sample_size": len(strong_patterns)
        }
    else:
        return {"signal": "NEUTRAL", "confidence": 0.0}
```

[MEJORADO] Cambios para rentabilidad:
- Composite score combina similitud × decaimiento temporal × quality score. Patrones viejos y de baja calidad pesan menos.
- Filtro de régimen: solo busca patrones formados en regímenes similares al actual. Un patrón de "trending_up" no debe matchear con el contexto actual si estamos en "ranging_tight".
- Threshold de dominancia subido de 70% a 62%. El 70% original era demasiado conservador y perdería muchas oportunidades con edge real. 62% con sample size >= 5 es estadísticamente significativo.
- Se calcula avg_adverse (máximo movimiento en contra) para informar la decisión de sizing.
- Se usa win rate PONDERADO, no simple conteo. Patrones recientes y de alta calidad pesan más.

## 4.4 Paso 4: Análisis Estadístico Avanzado [MEJORADO]

### 4.4.1 Análisis de Distribución de Precios
- Calcular la distribución de retornos en ventanas de 50, 100, 200 ticks
- Detectar skewness y kurtosis
- Mean reversion: z-score del precio actual vs EMA200
- [NUEVO] Test de Hurst exponent para medir mean-reversion vs momentum en la ventana actual:
  ```
  H < 0.5 → mean-reverting (favorece estrategias de reversión)
  H = 0.5 → random walk (NO operar, no hay edge)
  H > 0.5 → trending (favorece estrategias de momentum)
  ```
  Si H está entre 0.45 y 0.55, el mercado se comporta como random walk y el bot debe REDUCIR frecuencia de trades.

### 4.4.2 Análisis de Volatilidad con GARCH [MEJORADO]
```python
# Modelo GARCH(1,1) para predecir volatilidad futura
from arch import arch_model

def forecast_volatility(returns, horizon=5):
    """
    GARCH(1,1) forecast de volatilidad
    Returns: volatilidad esperada para los próximos N períodos
    """
    model = arch_model(returns * 100, vol='Garch', p=1, q=1, mean='Zero')
    fitted = model.fit(disp='off', show_warning=False)
    forecast = fitted.forecast(horizon=horizon)
    
    return {
        "current_vol": fitted.conditional_volatility[-1],
        "forecast_vol": forecast.variance.values[-1],
        "vol_trend": "expanding" if forecast.variance.values[-1][-1] > forecast.variance.values[-1][0] else "contracting",
        "vol_ratio": forecast.variance.values[-1][-1] / fitted.conditional_volatility[-1]  # >1 = expanding
    }
```

[MEJORADO] GARCH reemplaza el análisis de volatilidad estático del original. GARCH predice si la volatilidad va a AUMENTAR o DISMINUIR, lo cual es crítico: operar en volatilidad en contracción tiene menor riesgo que en expansión.

### 4.4.3 Análisis de Spikes con Proceso de Poisson [MEJORADO]

```python
import scipy.stats as stats

class SpikeProbabilityModel:
    """
    Modelo de Poisson modificado para predecir probabilidad de spike en Crash/Boom.
    
    FUNDAMENTO: Los spikes en Crash 1000 ocurren en promedio cada ~1000 ticks.
    La distribución de intervalos entre spikes se aproxima a una distribución exponencial
    (caso continuo del proceso de Poisson). Sin embargo, la hazard rate NO es constante:
    aumenta conforme pasan más ticks sin spike (distribución Weibull es mejor fit).
    """
    
    def __init__(self, symbol):
        self.symbol = symbol
        self.historical_intervals = []
        
    def fit(self, spike_intervals):
        """Ajustar distribución Weibull a los intervalos históricos entre spikes"""
        self.historical_intervals = spike_intervals
        
        # Fit Weibull distribution (más flexible que exponencial)
        self.shape, self.loc, self.scale = stats.weibull_min.fit(spike_intervals, floc=0)
        
        # También calcular estadísticas simples
        self.mean_interval = np.mean(spike_intervals)
        self.std_interval = np.std(spike_intervals)
        self.median_interval = np.median(spike_intervals)
        
    def hazard_rate(self, ticks_since_last):
        """
        Hazard rate: probabilidad instantánea de spike dado que no ha ocurrido aún.
        h(t) = f(t) / S(t) donde f=pdf y S=survival function
        
        Para Weibull con shape > 1: hazard rate AUMENTA con el tiempo
        (exactamente lo que esperamos: más ticks sin spike → más probable)
        """
        pdf = stats.weibull_min.pdf(ticks_since_last, self.shape, loc=0, scale=self.scale)
        sf = stats.weibull_min.sf(ticks_since_last, self.shape, loc=0, scale=self.scale)
        
        if sf > 0:
            return pdf / sf
        return 1.0  # Si survival function es 0, spike es inminente
    
    def probability_in_next_n_ticks(self, ticks_since_last, n=100):
        """
        P(spike en próximos n ticks | ya pasaron t ticks sin spike)
        = 1 - S(t+n) / S(t)
        """
        sf_current = stats.weibull_min.sf(ticks_since_last, self.shape, loc=0, scale=self.scale)
        sf_future = stats.weibull_min.sf(ticks_since_last + n, self.shape, loc=0, scale=self.scale)
        
        if sf_current > 0:
            return 1 - (sf_future / sf_current)
        return 1.0
    
    def get_zone(self, ticks_since_last):
        """Clasificar la zona de probabilidad de spike"""
        percentile = 1 - stats.weibull_min.sf(ticks_since_last, self.shape, loc=0, scale=self.scale)
        
        if percentile < 0.3:
            return "safe"           # Probabilidad baja de spike
        elif percentile < 0.6:
            return "normal"         # Probabilidad normal
        elif percentile < 0.8:
            return "elevated"       # Atención, probabilidad elevada
        elif percentile < 0.95:
            return "hot"            # Zona caliente, alta probabilidad
        else:
            return "critical"       # Spike estadísticamente inminente
```

[MEJORADO] El original usaba un análisis vago de "ticks desde último spike". La versión mejorada implementa un modelo Weibull completo con hazard rate creciente. Esto es CRÍTICO para la rentabilidad porque:
1. El hazard rate de Weibull AUMENTA con el tiempo (a diferencia de Poisson puro que es constante)
2. Permite calcular probabilidad exacta de spike en los próximos N ticks
3. Clasificación en zonas permite al bot ajustar comportamiento (en zona "hot" puede operar en dirección opuesta al spike esperado)

### 4.4.4 [NUEVO] Modelo de Ornstein-Uhlenbeck para Mean Reversion en Volatility Indices

```python
class MeanReversionModel:
    """
    Modelo Ornstein-Uhlenbeck para índices de Volatilidad.
    
    FUNDAMENTO: Los índices V75/V100 son generados para mantener una volatilidad objetivo.
    Cuando el precio se desvía significativamente de su media móvil, hay fuerza de reversión.
    El proceso O-U modela exactamente esto: dX = theta * (mu - X) * dt + sigma * dW
    
    theta = velocidad de reversión (mayor = revierte más rápido)
    mu = nivel de equilibrio
    sigma = volatilidad del proceso
    """
    
    def __init__(self):
        self.theta = None
        self.mu = None
        self.sigma = None
        
    def fit(self, prices, dt=1.0):
        """Estimar parámetros O-U por Maximum Likelihood"""
        n = len(prices)
        x = np.array(prices)
        
        # Regresión lineal: x[t+1] = a + b * x[t] + error
        x_lag = x[:-1]
        x_lead = x[1:]
        
        b = np.cov(x_lag, x_lead)[0][1] / np.var(x_lag)
        a = np.mean(x_lead) - b * np.mean(x_lag)
        residuals = x_lead - (a + b * x_lag)
        
        # Convertir a parámetros O-U
        self.theta = -np.log(b) / dt  # velocidad de reversión
        self.mu = a / (1 - b)          # media de largo plazo
        self.sigma = np.std(residuals) * np.sqrt(-2 * np.log(b) / (dt * (1 - b**2)))
        
        return {
            "theta": self.theta,
            "mu": self.mu, 
            "sigma": self.sigma,
            "half_life": np.log(2) / self.theta  # tiempo medio de reversión
        }
    
    def expected_return(self, current_price, horizon=5):
        """Retorno esperado por mean reversion en horizonte dado"""
        # E[X(t+h)] = mu + (x - mu) * exp(-theta * h)
        expected = self.mu + (current_price - self.mu) * np.exp(-self.theta * horizon)
        expected_return = (expected - current_price) / current_price
        return expected_return
    
    def signal(self, current_price):
        """Generar señal de trading basada en desviación de la media"""
        if self.mu is None:
            return {"signal": "WAIT", "strength": 0}
        
        deviation = (current_price - self.mu) / self.sigma
        half_life = np.log(2) / self.theta
        
        if deviation > 2.0:
            return {"signal": "SELL", "strength": min(abs(deviation) / 3, 1.0), "half_life": half_life}
        elif deviation < -2.0:
            return {"signal": "BUY", "strength": min(abs(deviation) / 3, 1.0), "half_life": half_life}
        elif deviation > 1.5:
            return {"signal": "WEAK_SELL", "strength": 0.3, "half_life": half_life}
        elif deviation < -1.5:
            return {"signal": "WEAK_BUY", "strength": 0.3, "half_life": half_life}
        else:
            return {"signal": "NEUTRAL", "strength": 0, "half_life": half_life}
```

[NUEVO] Esto no existía en el original. Es la estrategia de mean reversion más apropiada para Volatility Indices porque:
1. Los V75/V100 están DISEÑADOS para tener volatilidad objetivo, lo cual crea mean reversion natural
2. O-U es el modelo matemático estándar para mean reversion
3. Half-life dice cuánto tarda en revertir → informa la duración del contrato
4. Señal basada en desviaciones estándar del equilibrio → umbral objetivo y medible

### 4.4.5 [NUEVO] Detección de Régimen de Mercado con Hidden Markov Model

```python
from hmmlearn import hmm

class RegimeDetector:
    """
    HMM de 4 estados para detectar el régimen actual del mercado.
    
    Estados:
    0: trending_up — momento alcista sostenido
    1: trending_down — momento bajista sostenido
    2: ranging_tight — rango estrecho, baja volatilidad
    3: volatile_expansion — alta volatilidad sin dirección clara
    
    POR QUÉ ES CRÍTICO: El régimen determina QUÉ ESTRATEGIA usar:
    - trending → momentum/breakout
    - ranging → mean reversion
    - volatile → reducir posiciones o no operar
    """
    
    def __init__(self, n_states=4):
        self.model = hmm.GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=100,
            random_state=42
        )
        self.regime_names = {
            0: "trending_up",
            1: "trending_down", 
            2: "ranging_tight",
            3: "volatile_expansion"
        }
        self.is_fitted = False
        
    def fit(self, returns, volatility):
        """
        Entrenar HMM con features de retornos y volatilidad.
        Llamar con al menos 500 observaciones.
        """
        features = np.column_stack([returns, volatility])
        self.model.fit(features)
        self.is_fitted = True
        
        # Asignar nombres basado en medias de cada estado
        means = self.model.means_
        self._assign_regime_names(means)
        
    def predict_regime(self, returns, volatility):
        """Predecir régimen actual"""
        if not self.is_fitted:
            return "unknown", 0.0
            
        features = np.column_stack([returns[-50:], volatility[-50:]])
        states = self.model.predict(features)
        probabilities = self.model.predict_proba(features)
        
        current_state = states[-1]
        current_confidence = probabilities[-1][current_state]
        
        return self.regime_names.get(current_state, "unknown"), current_confidence
    
    def _assign_regime_names(self, means):
        """Asignar nombres de régimen basado en medias estimadas"""
        # Estado con mayor retorno medio positivo → trending_up
        # Estado con mayor retorno medio negativo → trending_down
        # Estado con menor volatilidad → ranging_tight
        # Estado con mayor volatilidad → volatile_expansion
        ret_means = means[:, 0]
        vol_means = means[:, 1]
        
        assignments = {}
        assignments[np.argmax(ret_means)] = "trending_up"
        assignments[np.argmin(ret_means)] = "trending_down"
        remaining = [i for i in range(4) if i not in assignments]
        if len(remaining) >= 2:
            assignments[remaining[np.argmin([vol_means[r] for r in remaining])]] = "ranging_tight"
            assignments[remaining[np.argmax([vol_means[r] for r in remaining])]] = "volatile_expansion"
        
        self.regime_names = assignments
```

[NUEVO] El HMM es CRÍTICO para la rentabilidad porque:
1. Evita operar momentum en mercado ranging (causa #1 de pérdidas en bots)
2. Evita operar mean reversion en mercado trending (causa #2)
3. Reduce posiciones en volatilidad extrema (protección de capital)
4. Informa tanto a pgvector (filtro de régimen) como a Groq (contexto)

### 4.4.6 Análisis de Estructura de Mercado (SMC Adaptado a Sintéticos)

Mantener SMC pero con una nota importante:

> **NOTA DE IMPLEMENTACIÓN:** Los conceptos de SMC (Order Blocks, FVG, BOS, CHoCH, liquidez) fueron diseñados para mercados reales con flujo institucional. En sintéticos NO hay instituciones. Sin embargo, el generador de Deriv está DISEÑADO para producir patrones que simulan comportamiento de mercado real, lo cual incluye estos patrones. SMC funciona en sintéticos no porque haya flujo institucional, sino porque el generador los crea intencionalmente.

Detectar:
- Higher Highs / Higher Lows y Lower Highs / Lower Lows
- Break of Structure (BOS): ruptura del último swing high/low
- Change of Character (CHoCH): primer señal de cambio de tendencia
- Order Blocks: última vela opuesta antes de un movimiento impulsivo
- Fair Value Gaps (FVG): gaps entre velas donde no hubo negociación
- Zonas de liquidez: acumulación de highs/lows iguales

[MEJORADO] Se mantiene SMC pero se contextualiza correctamente. El equipo de desarrollo debe entender que SMC funciona en sintéticos por diseño del generador, no por flujo institucional. Esto afecta cómo se interpretan las señales.

---

## 4.5 Paso 5: Decisión de Groq AI [MEJORADO — SECCIÓN CRÍTICA]

### 4.5.1 Configuración de Groq

```python
# Modelo: llama-3.3-70b-versatile (plan premium de Groq)
# Temperature: 0.05 (más bajo que el 0.1 original para máxima consistencia)
# Max tokens: 1500 (aumentado para permitir chain-of-thought + JSON)
# Timeout: 8 segundos máximo (aumentado para respuestas más completas)
# Retry: 2 intentos con backoff de 1s entre ellos
```

[MEJORADO] Temperature bajada a 0.05. En trading no queremos NADA de creatividad. Queremos que la misma situación de mercado genere la misma decisión consistentemente.

### 4.5.2 System Prompt para Groq [MEJORADO — REESCRITURA COMPLETA]

```
Eres un sistema experto de análisis cuantitativo especializado en índices sintéticos de Deriv.com. Tu función es evaluar datos de mercado y decidir si existe una oportunidad de trading con edge estadístico positivo, o si es mejor esperar.

PRINCIPIO FUNDAMENTAL: Tu trabajo NO es predecir el futuro. Tu trabajo es identificar situaciones donde la probabilidad está a nuestro favor basándose en datos históricos y modelos estadísticos. Si la evidencia no es clara, SIEMPRE dices WAIT. Decir WAIT no es un error — es preservar capital para mejores oportunidades.

== NATURALEZA DE LOS INSTRUMENTOS ==

Los índices sintéticos de Deriv son generados algorítmicamente. NO son mercados reales. Esto tiene implicaciones:
- No hay flujo institucional, noticias, ni eventos macro. Solo matemáticas.
- Volatility Indices (R_25 a R_100): mantienen volatilidad objetivo fija. La desviación de la media TIENDE a revertir. Mean reversion es la estrategia primaria.
- Crash Indices (CRASH500, CRASH1000): generan spikes bajistas con frecuencia estadística conocida. La probabilidad de spike AUMENTA conforme pasan más ticks sin uno (distribución Weibull, no Poisson puro).
- Boom Indices (BOOM500, BOOM1000): idéntico a Crash pero con spikes alcistas.

== PROCESO DE RAZONAMIENTO (SEGUIR SIEMPRE EN ESTE ORDEN) ==

Paso 1 — RÉGIMEN: ¿En qué régimen está el mercado? (trending_up, trending_down, ranging_tight, volatile_expansion). Si volatile_expansion con confianza > 0.7, responde WAIT automáticamente.

Paso 2 — ESTRATEGIA APROPIADA: Basado en el régimen, ¿qué tipo de señal buscas?
- trending → solo señales en dirección de la tendencia
- ranging → solo señales de mean reversion (z-score extremo)
- volatile → NO OPERAR

Paso 3 — EVALUACIÓN DE SEÑALES: Revisa cada fuente de datos:
a) ¿Qué dice el modelo estadístico? (O-U mean reversion, GARCH, Hurst exponent)
b) ¿Qué dicen los patrones similares de pgvector? (win rate, sample size, similarity)
c) ¿Qué dice la estructura de mercado? (tendencia, OB, FVG, BOS)
d) ¿Qué dicen los indicadores? (RSI, EMA alignment, Bollinger position)
e) Para Crash/Boom: ¿qué dice el modelo de spikes? (zona, hazard rate, probabilidad)

Paso 4 — CONFLUENCIAS: Cuenta cuántas fuentes de datos INDEPENDIENTES están alineadas en la misma dirección. Necesitas MÍNIMO 3 confluencias para considerar un trade.

Paso 5 — ABOGADO DEL DIABLO: ANTES de decidir, busca activamente razones para NO entrar:
- ¿Hay alguna señal contradictoria que estés ignorando?
- ¿El sample size de pgvector es suficiente (≥5)?
- ¿El Hurst exponent indica random walk (0.45-0.55)?
- ¿La volatilidad GARCH está en expansión?
- ¿El z-score está en zona neutral (-1.5 a +1.5)?
- ¿Hay trades correlacionados ya abiertos?
Si encuentras 2+ razones sólidas para no entrar, responde WAIT independientemente de las confluencias.

Paso 6 — CALIBRACIÓN DE CONFIANZA: Tu confianza debe reflejar la realidad:
- 0.70-0.75: Setup aceptable, confluencias mínimas, algún riesgo. Stake mínimo.
- 0.76-0.82: Setup bueno, múltiples confluencias, riesgo controlado. Stake normal.
- 0.83-0.89: Setup fuerte, todo alineado, bajo riesgo. Stake aumentado.
- 0.90-0.95: Setup excepcional, raramente ocurre. Solo cuando TODO está a favor.
- > 0.95: NUNCA. No existe setup con > 95% de probabilidad en trading. Si estás aquí, estás alucinando.

Paso 7 — DECISIÓN FINAL: Solo si pasó todos los pasos anteriores, genera la recomendación.

== REGLAS ANTI-ALUCINACIÓN ==
1. NO inventes confluencias. Si solo ves 1 señal clara, di WAIT.
2. NO interpretes datos ambiguos como señales. RSI en 45 no es "cercano a sobreventa".
3. NO ignores señales contradictoria para justificar un trade.
4. Si los datos de pgvector muestran < 5 patrones similares, su señal NO cuenta como confluencia.
5. Si el Hurst exponent está entre 0.45-0.55, cualquier señal direccional pierde una confluencia.

== REGLAS DE RIESGO (NUNCA ROMPER) ==
1. Confianza < 0.70 → SIEMPRE responde WAIT
2. Stake: nunca más del porcentaje calculado por Kelly (se te proporcionará)
3. 3+ pérdidas consecutivas → WAIT obligatorio
4. No operar contra el régimen (no mean reversion en trending, no momentum en ranging)
5. Si GARCH predice expansión de volatilidad > 1.5x → reducir stake a la mitad o WAIT

== FORMATO DE RESPUESTA ==

IMPORTANTE: Responde SOLO con JSON válido. Sin markdown, sin backticks, sin texto antes o después.

{
  "reasoning_chain": {
    "step1_regime": "descripción del régimen detectado y confianza",
    "step2_strategy": "estrategia apropiada para este régimen",
    "step3_signals": {
      "statistical_model": "qué dice el modelo estadístico",
      "pgvector_patterns": "qué dicen los patrones similares",
      "market_structure": "qué dice SMC",
      "indicators": "qué dicen los indicadores técnicos",
      "spike_model": "qué dice el modelo de spikes (si aplica)"
    },
    "step4_confluences": ["lista de confluencias encontradas"],
    "step5_counter_arguments": ["lista de razones para NO entrar"],
    "step6_calibration": "justificación del nivel de confianza"
  },
  "decision": "BUY" | "SELL" | "WAIT",
  "confidence": 0.00 a 0.95,
  "contract_type": "CALL" | "PUT" | "HIGHER" | "LOWER" | null,
  "duration_minutes": 1 a 15 o null,
  "stake_percentage": 0.3 a 2.0,
  "risk_level": "low" | "medium" | "high",
  "market_phase": "trending_up" | "trending_down" | "ranging" | "volatile" | "pre_spike",
  "invalidation": "condición que invalidaría este trade",
  "suggested_barrier": número o null (para contratos Higher/Lower)
}
```

[MEJORADO] Cambios críticos en el prompt de Groq para rentabilidad:
1. **Chain of Thought forzado**: 7 pasos obligatorios antes de decidir. Reduce decisiones impulsivas.
2. **Abogado del diablo (Paso 5)**: Groq debe buscar activamente razones para NO entrar. Esto es el cambio más impactante — los LLMs tienden a confirmation bias, buscar razones para confirmar lo que ya "decidieron". Forzarlos a buscar contra-argumentos reduce trades malos.
3. **Calibración de confianza explícita**: Rango máximo 0.95, con descripción clara de qué significa cada nivel. Elimina overconfidence del LLM.
4. **Reglas anti-alucinación**: 5 reglas específicas que evitan que Groq invente señales.
5. **Reasoning chain en el output**: Permite auditar cada decisión y detectar patrones de error.
6. **Temperature 0.05**: Máxima consistencia.
7. **Contexto de instrumentos**: Groq ahora entiende que son algorítmicos, no mercados reales.

### 4.5.3 User Prompt Template [MEJORADO]

```
ANÁLISIS DE MERCADO — {symbol} — {timestamp}

== ESTADO DEL BOT ==
Balance: ${balance} | P&L hoy: ${daily_pnl} ({daily_pnl_pct}%)
Trades hoy: {total_trades_today} (W:{wins} L:{losses}) | Win rate: {win_rate_today}%
Pérdidas consecutivas: {consecutive_losses}
Trades abiertos: {open_trades} | Trades correlacionados abiertos: {correlated_trades}
Meta-confianza en Groq (últimas 20 decisiones): {groq_meta_confidence}%

== RÉGIMEN DE MERCADO ==
Régimen detectado (HMM): {regime} (confianza: {regime_confidence})
Duración del régimen actual: {regime_duration} velas
Hurst exponent (últimas 200 velas): {hurst_exponent}
Interpretación Hurst: {hurst_interpretation}

== MODELO ESTADÍSTICO ==
{if_volatility_index}
  O-U Mean Reversion:
    Media de equilibrio (mu): {ou_mu}
    Precio actual: {current_price}
    Desviación: {ou_deviation} sigmas
    Señal O-U: {ou_signal} (strength: {ou_strength})
    Half-life de reversión: {ou_half_life} velas
  GARCH Volatility:
    Volatilidad actual: {garch_current_vol}
    Forecast (5 períodos): {garch_forecast_vol}
    Tendencia de volatilidad: {vol_trend}
    Ratio forecast/actual: {vol_ratio}
{endif}

{if_crash_boom}
  Modelo de Spikes (Weibull):
    Ticks desde último spike: {ticks_since_spike}
    Media histórica: {mean_interval} (σ: {std_interval})
    Hazard rate actual: {hazard_rate}
    Probabilidad de spike en próximos 100 ticks: {spike_prob_100}%
    Probabilidad de spike en próximos 500 ticks: {spike_prob_500}%
    Zona: {spike_zone}
{endif}

== DATOS DE VELAS (últimas 30 velas de {timeframe}) ==
{candles_data_formatted}

== INDICADORES TÉCNICOS ==
EMA: 9={ema_9} | 21={ema_21} | 50={ema_50} | 200={ema_200}
RSI 14: {rsi_14}
ATR 14: {atr_14}
Bollinger: U={bb_upper} | M={bb_middle} | L={bb_lower}
MACD: L={macd_line} | S={macd_signal} | H={macd_hist}
Z-score (precio vs EMA200): {zscore}
EMA Alignment: {ema_alignment}
Price Position (0-1): {price_position}

== ESTRUCTURA DE MERCADO (SMC) ==
Tendencia: {trend_direction}
Último BOS: {last_bos} @ {bos_price}
Último CHoCH: {last_choch} @ {choch_price}
Order Blocks activos: {active_order_blocks}
FVGs activos: {active_fvgs}
Liquidez más cercana: {nearest_liquidity} ({liquidity_direction})

== PATRONES SIMILARES (pgvector, filtrados por régimen) ==
Patrones encontrados: {n_similar_patterns} (similitud > 0.70: {n_strong_patterns})
Win rate ponderado: {weighted_win_rate}%
Dirección dominante: {dominant_direction} (probabilidad: {direction_prob}%)
Avg pips resultado: {avg_outcome_pips}
Avg max adverse (drawdown): {avg_adverse}
Sample quality: {sample_quality}

== KELLY CRITERION ==
Edge estimado (basado en pgvector + estadístico): {kelly_edge}
Win probability: {kelly_win_prob}
Win/Loss ratio: {kelly_ratio}
Kelly fracción óptima: {kelly_fraction}%
Stake sugerido por Kelly (con factor 0.25): ${kelly_stake}

Sigue tu proceso de razonamiento de 7 pasos y responde en JSON.
```

[MEJORADO] Cambios:
- Se agrega régimen de mercado, Hurst exponent, modelos O-U y GARCH, modelo de spikes Weibull con hazard rate
- Se agrega Kelly Criterion precalculado para que Groq no tenga que calcular sizing
- Se agrega meta-confianza (accuracy reciente de Groq) para auto-calibración
- Se agrega conteo de trades correlacionados abiertos
- Datos de pgvector ahora incluyen win rate PONDERADO y avg adverse

### 4.5.4 [NUEVO] Few-Shot Examples en el System Prompt

Agregar al final del system prompt estos 3 ejemplos:

```
== EJEMPLO 1: TRADE CORRECTO (BUY en V75 por mean reversion) ==
Contexto: R_75, régimen=ranging_tight, z-score=-2.3, O-U señal=BUY strength 0.8, 
pgvector 8/10 patrones similares fueron UP (win_rate 80%), RSI=28, precio en banda inferior Bollinger.
Respuesta correcta:
{
  "reasoning_chain": {
    "step1_regime": "ranging_tight con confianza 0.82 — apropiado para mean reversion",
    "step2_strategy": "Mean reversion — buscar señales de reversión alcista",
    "step3_signals": {
      "statistical_model": "O-U muestra desviación -2.3 sigmas, señal BUY fuerte. GARCH muestra vol estable.",
      "pgvector_patterns": "8/10 patrones similares resultaron UP, win rate ponderado 80%, sample sólido",
      "market_structure": "Precio en zona de demanda, FVG alcista detectado 15 velas atrás",
      "indicators": "RSI 28 (sobreventa), precio tocando Bollinger inferior, EMA9 empezando a girar",
      "spike_model": "N/A"
    },
    "step4_confluences": ["O-U mean reversion -2.3σ", "pgvector 80% UP", "RSI sobreventa", "Bollinger inferior", "FVG alcista"],
    "step5_counter_arguments": ["EMA alignment aún bajista — pero esto es normal antes de reversión en ranging"],
    "step6_calibration": "5 confluencias con 1 contra-argumento menor. Confianza 0.83 apropiada para setup fuerte."
  },
  "decision": "BUY",
  "confidence": 0.83,
  "contract_type": "CALL",
  "duration_minutes": 5,
  "stake_percentage": 1.2,
  "risk_level": "medium",
  "market_phase": "ranging",
  "invalidation": "Si z-score cae por debajo de -3.0 o régimen cambia a trending_down",
  "suggested_barrier": null
}

== EJEMPLO 2: WAIT CORRECTO (datos insuficientes) ==
Contexto: CRASH1000, régimen=trending_down, ticks_since_spike=450, pgvector solo 3 patrones similares, 
RSI=42, zona de spike=normal.
Respuesta correcta:
{
  "reasoning_chain": {
    "step1_regime": "trending_down con confianza 0.71 — operar solo en dirección bajista o esperar spike",
    "step2_strategy": "Crash — esperar zona caliente de spike para operar Rise (contra-spike)",
    "step3_signals": {
      "statistical_model": "Solo 450 ticks desde último spike, zona normal. Sin edge de spike.",
      "pgvector_patterns": "INSUFICIENTE — solo 3 patrones similares, no cumple mínimo de 5",
      "market_structure": "Tendencia bajista clara pero sin señal de reversión",
      "indicators": "RSI neutral en 42, sin señal clara",
      "spike_model": "Zona normal, hazard rate bajo, probabilidad spike próximos 100 ticks: 8%"
    },
    "step4_confluences": ["trending_down sugiere PUT"],
    "step5_counter_arguments": ["Solo 1 confluencia (necesito 3)", "pgvector insuficiente", "zona de spike normal sin edge", "RSI neutral sin confirmar"],
    "step6_calibration": "Solo 1 confluencia clara y 4 contra-argumentos. WAIT es la decisión correcta."
  },
  "decision": "WAIT",
  "confidence": 0.0,
  "contract_type": null,
  "duration_minutes": null,
  "stake_percentage": 0.0,
  "risk_level": "high",
  "market_phase": "trending_down",
  "invalidation": null,
  "suggested_barrier": null
}

== EJEMPLO 3: TRADE CORRECTO (Crash/Boom en zona hot) ==
Contexto: CRASH1000, ticks_since_spike=1350 (media=1000), zona=hot, hazard_rate alto,
probabilidad spike próximos 100 ticks: 38%, régimen=trending_down, pgvector 7/10 patrones en zona hot resultaron en spike.
Respuesta correcta:
{
  "reasoning_chain": {
    "step1_regime": "trending_down — consistente con esperar spike bajista",
    "step2_strategy": "Spike strategy — probabilidad elevada de spike bajista. Operar PUT corto.",
    "step3_signals": {
      "statistical_model": "Weibull: 1350 ticks sin spike (media 1000, +1.2σ). Hazard rate alto. P(spike <100 ticks)=38%.",
      "pgvector_patterns": "7/10 patrones en zona hot similares terminaron en spike, win rate 70%",
      "market_structure": "Aceleración bajista reciente consistente con pre-spike",
      "indicators": "ATR expandiéndose, consistente con volatilidad pre-spike",
      "spike_model": "Zona HOT. Estadísticamente, spike debería ocurrir pronto."
    },
    "step4_confluences": ["Weibull zona hot", "38% prob en 100 ticks", "pgvector 70% spike", "ATR expandiéndose"],
    "step5_counter_arguments": ["Spikes son impredecibles en timing exacto — podría tomar 500 ticks más"],
    "step6_calibration": "4 confluencias, 1 contra-argumento válido pero el edge estadístico es claro. Confianza 0.78."
  },
  "decision": "SELL",
  "confidence": 0.78,
  "contract_type": "PUT",
  "duration_minutes": 3,
  "stake_percentage": 0.8,
  "risk_level": "medium",
  "market_phase": "pre_spike",
  "invalidation": "Si spike ocurre antes de la entrada (oportunidad perdida, no entrar)",
  "suggested_barrier": null
}
```

[NUEVO] Few-shot examples son CRÍTICOS para la calidad de Groq porque:
1. Muestran exactamente el formato esperado
2. Demuestran cómo usar el abogado del diablo correctamente
3. Muestran calibración de confianza realista
4. Demuestran que WAIT es una respuesta válida y frecuente

### 4.5.5 Validación de Respuesta de Groq [MEJORADO]

Después de recibir la respuesta de Groq:

1. Parsear JSON. Si falla → registrar error, NO operar, retry 1 vez
2. Validar `confidence` >= 0.70. Si no → registrar como WAIT
3. Validar `confidence` <= 0.95. Si > 0.95 → **REDUCIR a 0.85 automáticamente** (overconfidence del LLM)
4. Validar que `stake_percentage` no exceda Kelly fraction × 1.5
5. Validar coherencia: si `decision` es "BUY"/"SELL" pero `contract_type` es null → descartar
6. Validar que `counter_arguments` no esté vacío. Si Groq no encontró ningún contra-argumento → sospechoso, reducir confianza en 0.10
7. Verificar concordancia con capas 1 y 2. Si Groq contradice AMBAS capas anteriores → reducir confianza en 0.15
8. Verificar límite de pérdida diaria
9. Verificar máximo de trades simultáneos
10. [NUEVO] Verificar correlación: si hay trades abiertos en instrumentos correlacionados, reducir stake
11. Si todo pasa → ejecutar el trade en Deriv API
12. Registrar TODO en `groq_decisions_log` y `trades`, incluyendo señales de cada capa

[MEJORADO] Validaciones 3, 6, y 7 son nuevas y críticas:
- Cap de 0.95 previene overconfidence
- Verificar que existan contra-argumentos asegura que Groq hizo el paso 5
- Penalización por contradecir ambas capas reduce trades donde Groq está "alucinando"

### 4.5.6 [NUEVO] Fallback: Operación sin Groq

Si Groq API está caído o tarda más de 8 segundos:

```python
def mechanical_fallback(layer1_signal, layer2_signal):
    """
    Decisión puramente mecánica cuando Groq no está disponible.
    Solo opera si AMBAS capas están de acuerdo con confianza alta.
    Stake reducido al 50% del normal como medida de precaución.
    """
    if layer1_signal['confidence'] > 0.75 and layer2_signal['confidence'] > 0.70:
        if layer1_signal['direction'] == layer2_signal['direction']:
            return {
                "decision": layer1_signal['direction'],
                "confidence": min(layer1_signal['confidence'], layer2_signal['confidence']) * 0.85,
                "stake_multiplier": 0.5,  # mitad del stake normal
                "source": "mechanical_fallback"
            }
    return {"decision": "WAIT", "confidence": 0, "source": "mechanical_fallback"}
```

[NUEVO] El original no tenía plan B para cuando Groq falla. Este fallback permite operar con las capas mecánicas pero con stake reducido. Esto evita perder oportunidades buenas cuando Groq tiene downtime.

---

# 5. MOTOR DE EJECUCIÓN DE TRADES [MEJORADO]

## 5.1 Flujo de Ejecución

```
Señal de Capa 1 (análisis mecánico/estadístico)
    ↓
Señal de Capa 2 (pgvector pattern matching)
    ↓
Señal de Capa 3 (Groq AI — o fallback mecánico)
    ↓
[NUEVO] Concordance Check: ¿cuántas capas están de acuerdo?
    ├── 3/3 de acuerdo → "full_agreement" (mejor stake)
    ├── 2/3 de acuerdo con Groq → "groq_confirmed" (stake normal)
    ├── 2/3 de acuerdo sin Groq → "mechanical_consensus" (stake reducido)
    └── Sin consenso → WAIT
    ↓
[NUEVO] Kelly Criterion: calcular stake óptimo
    ↓
Validación de Risk Management
    ├── ¿Balance suficiente?
    ├── ¿Límite diario no alcanzado?
    ├── ¿Trades abiertos < máximo?
    ├── ¿No en cooldown?
    ├── [NUEVO] ¿Correlación aceptable con trades abiertos?
    └── [NUEVO] ¿Régimen actual permite trading?
    ↓
Enviar orden a Deriv WebSocket API
    ↓
Confirmar ejecución → registrar en DB con decision_path y señales por capa
    ↓
Monitorear trade hasta cierre
    ↓
Registrar resultado → actualizar estadísticas → feedback loop
```

## 5.2 Risk Management [MEJORADO]

### 5.2.1 [NUEVO] Position Sizing con Fractional Kelly

```python
def calculate_kelly_stake(win_probability, win_loss_ratio, balance, kelly_fraction=0.25):
    """
    Kelly Criterion con fracción conservadora.
    
    f* = (p * b - q) / b
    donde p = prob de ganar, q = prob de perder, b = ratio win/loss
    
    Usamos Kelly fraccional (25% del Kelly óptimo) porque:
    - Kelly completo es demasiado agresivo y asume estimaciones perfectas
    - Kelly/4 reduce drawdown significativamente con sacrificio moderado de retorno
    """
    q = 1 - win_probability
    kelly_optimal = (win_probability * win_loss_ratio - q) / win_loss_ratio
    
    # Clamp entre 0 y 2% del balance
    kelly_adjusted = max(0, min(kelly_optimal * kelly_fraction, 0.02))
    
    stake = balance * kelly_adjusted
    
    return {
        "kelly_optimal": kelly_optimal,
        "kelly_fraction_used": kelly_fraction,
        "kelly_adjusted": kelly_adjusted,
        "stake": stake,
        "stake_pct": kelly_adjusted * 100
    }
```

[NUEVO] Kelly Criterion reemplaza el 2% fijo. Beneficios para rentabilidad:
- Stake proporcional al edge real. Setup con 80% win rate y 2:1 ratio merece más stake que uno con 57% y 1:1.
- Fracción 0.25 es conservadora, reduce drawdowns sin sacrificar demasiado retorno.
- El 2% máximo se mantiene como cap absoluto.

### 5.2.2 Reglas de Risk Management

| Regla | Valor | Descripción |
|-------|-------|-------------|
| Max stake por trade | min(Kelly×0.25, 2%) del balance | [MEJORADO] Dinámico con cap |
| Max pérdida diaria | 8% del balance inicial del día | [MEJORADO] Reducido de 10% a 8% |
| Max trades simultáneos | 3 (max 2 correlacionados) | [MEJORADO] + límite de correlación |
| Max trades por día | 40 | [MEJORADO] Reducido de 50 a 40 |
| Cooldown por pérdidas | 3 consecutivas = 15 min pausa | Sin cambio |
| Cooldown por pérdidas graves | 4 consecutivas = 1 hora pausa | [MEJORADO] Reducido de 5 a 4 |
| Max drawdown total | 25% del capital inicial | [MEJORADO] Reducido de 30% a 25% |
| [NUEVO] Régimen volatile | Reducir stake 50% o WAIT | Protección en alta volatilidad |
| [NUEVO] Groq meta-confidence < 50% | Reducir stake 30% | Si Groq está fallando, confiar menos |

[MEJORADO] Los cambios reducen el riesgo de ruina:
- Pérdida diaria de 10% → 8%: reduce drawdown acumulado semanal
- Drawdown total de 30% → 25%: mayor protección del capital
- Cooldown grave de 5 → 4 consecutivas: se activa antes
- Límite de correlación: evita 3 trades en instrumentos similares

### 5.2.3 [NUEVO] Gestión de Correlación

```python
CORRELATION_GROUPS = {
    "volatility_high": ["R_75", "R_100"],     # Alta correlación entre sí
    "volatility_low": ["R_25", "R_50"],       # Alta correlación entre sí
    "crash": ["CRASH500", "CRASH1000"],        # Alta correlación entre sí
    "boom": ["BOOM500", "BOOM1000"],           # Alta correlación entre sí
}

def check_correlation(new_trade_symbol, open_trades):
    """Verificar que no tengamos demasiados trades correlacionados"""
    new_group = None
    for group, symbols in CORRELATION_GROUPS.items():
        if new_trade_symbol in symbols:
            new_group = group
            break
    
    if new_group is None:
        return True  # Sin grupo, OK
    
    correlated_count = sum(1 for t in open_trades 
                          if t['symbol'] in CORRELATION_GROUPS.get(new_group, []))
    
    return correlated_count < 2  # Máximo 2 trades en el mismo grupo
```

### 5.2.4 [NUEVO] Protocolo de Drawdown Recovery

```python
def get_drawdown_adjustment(current_drawdown_pct):
    """
    Ajuste progresivo de stake según nivel de drawdown.
    A mayor drawdown, más conservador.
    """
    if current_drawdown_pct < 5:
        return 1.0    # Sin ajuste
    elif current_drawdown_pct < 10:
        return 0.75   # Reducir stake 25%
    elif current_drawdown_pct < 15:
        return 0.50   # Reducir stake 50%
    elif current_drawdown_pct < 20:
        return 0.30   # Reducir stake 70%
    elif current_drawdown_pct < 25:
        return 0.15   # Stake mínimo
    else:
        return 0.0    # STOP — no operar
```

[NUEVO] Drawdown recovery progresivo evita que un drawdown moderado se convierta en catastrófico. El original solo tenía un kill switch a 30%. Ahora el bot reduce progresivamente el riesgo, lo que permite recuperarse más fácilmente.

## 5.3 Feedback Loop (Aprendizaje Continuo) [MEJORADO]

Cuando un trade se cierra:

1. Actualizar `trades` con resultado final
2. Actualizar `candle_patterns` con outcomes
3. Actualizar `groq_decisions_log` con `was_correct`
4. [NUEVO] Registrar qué habría hecho cada capa independientemente (para A/B testing)
5. Actualizar pattern quality scores:
   - Ganador: `quality_score = quality_score * 0.9 + 0.1` (EMA hacia 1)
   - Perdedor: `quality_score = quality_score * 0.9 + 0.0` (EMA hacia 0)
6. [NUEVO] Actualizar meta-confianza de Groq:
   ```python
   # Calcular accuracy de Groq en las últimas 20 decisiones
   recent_20 = get_last_n_groq_decisions(20)
   groq_accuracy = sum(1 for d in recent_20 if d.was_correct) / len(recent_20)
   update_bot_state('groq_meta_confidence', groq_accuracy)
   
   # Si accuracy < 50%, reducir influencia de Groq
   if groq_accuracy < 0.50:
       log_alert("Groq accuracy below 50%. Reducing Groq influence.")
   ```
7. [NUEVO] Actualizar estadísticas por régimen en `regime_history`
8. [NUEVO] Evaluar si Groq aportó valor vs el mecánico solo:
   ```python
   # Si Groq contradijo al mecánico, ¿acertó?
   if trade.groq_overrode_mechanical:
       update_groq_override_stats(trade.groq_override_was_correct)
   ```
9. Recalcular estadísticas generales del bot

[MEJORADO] El feedback loop ahora:
- Usa EMA en vez de incremento/decremento simple para quality scores (más estable)
- Trackea meta-confianza de Groq para auto-regulación
- Registra performance por régimen para aprendizaje de estrategias
- Mide si Groq aporta valor real cuando contradice al sistema mecánico

### 5.3.1 [NUEVO] Proceso Batch Nocturno de Optimización

Ejecutar cada 24 horas (a las 00:00 UTC):

```python
async def nightly_optimization():
    """Proceso batch de optimización nocturna"""
    
    # 1. Recalcular todos los quality_scores con decaimiento temporal
    await recalculate_quality_scores()
    
    # 2. Re-entrenar HMM de régimen con datos actualizados
    for symbol in ACTIVE_SYMBOLS:
        await retrain_regime_detector(symbol)
    
    # 3. Re-entrenar modelo O-U con datos recientes
    for symbol in VOLATILITY_SYMBOLS:
        await retrain_ou_model(symbol)
    
    # 4. Re-ajustar distribución Weibull para Crash/Boom
    for symbol in CRASH_BOOM_SYMBOLS:
        await refit_weibull_model(symbol)
    
    # 5. Evaluar A/B test si está activo
    await evaluate_ab_test()
    
    # 6. Generar reporte de salud del sistema
    health_report = await generate_system_health_report()
    
    # 7. Enviar resumen por Telegram
    await send_daily_summary(health_report)
    
    # 8. Detectar degradación del modelo
    if health_report['groq_accuracy_7d'] < 0.50:
        await send_alert("⚠️ Groq accuracy < 50% en últimos 7 días. Considerar ajuste de prompt.")
    
    if health_report['overall_win_rate_7d'] < 0.50:
        await send_alert("🔴 Win rate < 50% en últimos 7 días. Considerar pausar bot.")
```

---

# 6. DASHBOARD WEB — PANEL DE CONTROL EN TIEMPO REAL

## 6.1 Especificaciones Generales

- **Framework:** Next.js 14+ con App Router
- **UI:** Tailwind CSS + shadcn/ui para componentes
- **Gráficos de mercado:** TradingView Lightweight Charts (open source, embeddable)
- **Gráficos de estadísticas:** Recharts
- **Comunicación en tiempo real:** Socket.IO
- **Autenticación:** JWT con login por email/password (solo 1 usuario admin)
- **Responsive:** Funcional en desktop y tablet, optimizado para desktop
- **Tema:** Dark mode por defecto (tema trading profesional)

## 6.2 Páginas del Dashboard

### 6.2.1 Dashboard Principal (Home)

**Fila superior — Métricas clave (5 cards):** [MEJORADO +1 card]
- Balance actual (con % cambio vs inicio del día)
- P&L del día (con indicador verde/rojo)
- Win rate del día (%)
- Trades activos (con lista dropdown)
- [NUEVO] Groq Meta-Confidence (% accuracy últimas 20 decisiones — gauge circular)

**Fila central izquierda — Gráfico de precios en tiempo real:**
- TradingView Lightweight Chart con velas
- Selector de instrumento y timeframe
- Overlays de indicadores: EMA 9/21/50/200, Bollinger Bands
- Marcadores visuales:
  - Triángulos verdes/rojos para trades ganados/perdidos
  - Rectángulos azules para Order Blocks
  - Rectángulos amarillos para FVGs
  - Líneas punteadas para niveles de liquidez
  - [NUEVO] Banda de confianza O-U: zona sombreada mostrando ±2σ del equilibrio
  - [NUEVO] Marcadores de spikes (Crash/Boom): líneas verticales rojas/verdes

**Fila central derecha — Panel de IA:** [MEJORADO]
- Última decisión de Groq con reasoning chain expandible
  - BUY = card verde, SELL = card roja, WAIT = card gris
  - Barra de confianza (0-95%)
  - [NUEVO] Sección "Abogado del diablo" — contra-argumentos encontrados
  - [NUEVO] Concordancia de capas: indicador visual 1/3, 2/3, 3/3
- Historial de últimas 10 decisiones con resultado

**Fila inferior — Feed de actividad + Régimen:**
- Log en tiempo real de eventos
- [NUEVO] Indicador visual del régimen actual por instrumento (badges de colores)

### 6.2.2 Página de Trades (sin cambios mayores)

Igual que el original, con adiciones:
- [NUEVO] Columna "Decision Path" (full_agreement, groq_confirmed, etc.)
- [NUEVO] Columna "Layers Agreement" (1/3, 2/3, 3/3)
- [NUEVO] Filtro por régimen de mercado al momento del trade

### 6.2.3 Página de Análisis de Mercado [MEJORADO]

**Análisis multi-instrumento:**
- Grid con mini-gráficos de todos los instrumentos
- [NUEVO] Badge de régimen actual por instrumento
- [NUEVO] Hurst exponent indicator por instrumento

**Panel de patrones (pgvector):**
- Igual que original
- [NUEVO] Gráfico de edad promedio de patrones usados (detectar si los patrones se están volviendo obsoletos)

**Panel de Crash/Boom:** [MEJORADO]
- Contador visual de ticks desde último spike
- [NUEVO] Hazard rate gauge (velocímetro)
- [NUEVO] Gráfico de distribución Weibull ajustada vs datos reales
- [NUEVO] Historial de precisión del modelo de spikes

**[NUEVO] Panel de Regímenes:**
- Timeline de cambios de régimen por instrumento
- Win rate del bot por régimen (¿en qué régimen gana más?)
- Duración promedio de cada régimen

### 6.2.4 Página de Rendimiento / Analytics [MEJORADO]

**Equity Curve:** (sin cambio)

**Estadísticas detalladas:** (sin cambio)

**[NUEVO] Análisis por Capas (A/B Testing):**
- Gráfico comparativo: rendimiento del sistema completo (3 capas) vs solo mecánico (capas 1+2) vs solo capa 1
- Win rate de cada capa independientemente
- Valor agregado de Groq: win rate CON Groq vs SIN Groq
- Valor agregado de pgvector: win rate CON pgvector vs SIN pgvector
- Significance test: ¿la diferencia es estadísticamente significativa? (p-value)

**[NUEVO] Panel de Leading Indicators:**
- Tendencia del Hurst exponent (si cae hacia 0.5, el edge se está erosionando)
- Tendencia del win rate de pgvector (si baja, los patrones pueden estar obsoletos)
- Tendencia del Groq accuracy (si baja, el prompt puede necesitar ajuste)
- Ratio de decisiones WAIT vs TRADE (si sube mucho, el bot no encuentra oportunidades)
- Volatilidad de resultados (si sube, el edge es menos estable)

**Alertas Tempranas Automáticas:**
- Si win rate de 7 días cae > 10% vs promedio → alerta amarilla
- Si Groq accuracy cae bajo 55% → alerta naranja
- Si Hurst exponent promedio entre 0.45-0.55 por 48+ horas → alerta "mercado random, considerar pausar"
- Si profit factor cae bajo 1.1 en 7 días → alerta roja

### 6.2.5 Página de Configuración (igual que original con adiciones)

**Adiciones:**
- [NUEVO] Kelly fraction multiplier (slider 0.10 - 0.50)
- [NUEVO] Toggle A/B testing ON/OFF
- [NUEVO] Selector de modo A/B test: "full vs no-groq" o "full vs mechanical-only"
- [NUEVO] Drawdown recovery: toggle ON/OFF y configurar niveles

---

# 7. SISTEMA DE NOTIFICACIONES — TELEGRAM

## 7.1 Tipos de Notificación

### Trade Abierto [MEJORADO]
```
🟢 TRADE ABIERTO
📊 R_75 — CALL (Rise)
💰 Stake: $5.00 (Kelly 1.2% del balance)
📈 Precio entrada: 450,231.50
⏱ Duración: 5 minutos
🤖 Groq: 83% confianza
🔗 Capas: ✅Mecánico ✅pgvector ✅Groq (3/3)
📋 Confluencias: O-U -2.1σ + pgvector 78% UP + RSI 28 + Bollinger Lower
⚖️ Contra-arg: EMA alignment mixto
🌡 Régimen: ranging_tight
```

### Trade Cerrado — Ganador (sin cambio mayor)
```
✅ TRADE GANADO
📊 R_75 — CALL (Rise)
💰 Payout: $9.50 | Profit: +$4.50
📈 450,231.50 → 450,298.20
📊 Win rate hoy: 65% (13/20)
💵 Balance: $523.50 (+$12.30 hoy)
```

### Trade Cerrado — Perdedor (sin cambio mayor)
```
❌ TRADE PERDIDO
📊 R_75 — CALL (Rise)
💰 Pérdida: -$5.00
📊 Win rate hoy: 60% (12/20)
💵 Balance: $518.50 (+$7.30 hoy)
⚠️ Consecutivas: 2/4
```

### [NUEVO] Alerta de Degradación del Modelo
```
⚠️ ALERTA: DEGRADACIÓN DETECTADA
📉 Groq accuracy (7d): 48% (umbral: 55%)
📊 Win rate (7d): 52% (umbral: 55%)
📐 Hurst promedio: 0.49 (zona random walk)
💡 Sugerencia: Considerar pausar bot y revisar prompt de Groq
🔧 Acción automática: Stake reducido 30%
```

### Resumen Diario [MEJORADO]
```
📊 RESUMEN DIARIO — 07 Feb 2026

💵 Balance: $535.20 | Drawdown: 3.2%
📈 P&L hoy: +$35.20 (+7.04%)
🎯 Trades: 22 total | W:14 L:8 | Win rate: 63.6%
🏆 Mejor: +$12.50 (R_75 CALL) | Peor: -$5.00 (CRASH1000 PUT)

🤖 GROQ REPORT
Accuracy: 68% | Meta-confianza: 72%
Override mecánico: 4 veces (3 correctas)
Aportó: +4.2% win rate vs mecánico solo

🔄 PGVECTOR REPORT
Patrones usados: 18 | Win rate: 72%
vs sin pgvector: 55% | Aporte: +17%

🌡 REGÍMENES
R_75: ranging_tight (8h) → trending_up (4h)
CRASH1000: trending_down | Spikes hoy: 3

📐 HEALTH
Hurst promedio: 0.56 (trending — bueno)
Profit factor: 1.82 | Sharpe: 2.1
```

---

# 8. DEPLOYMENT Y DEVOPS

## 8.1 Docker Compose

```yaml
services:
  bot-backend:
    build: ./backend
    restart: always
    depends_on: [postgres, redis]
    environment:
      - DERIV_API_TOKEN=${DERIV_API_TOKEN}
      - DERIV_APP_ID=${DERIV_APP_ID}
      - GROQ_API_KEY=${GROQ_API_KEY}
      - DATABASE_URL=postgresql://...
      - REDIS_URL=redis://redis:6379
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
    # [NUEVO] Health check
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    
  dashboard:
    build: ./dashboard
    restart: always
    ports:
      - "3000:3000"
    
  postgres:
    image: timescale/timescaledb:latest-pg16
    restart: always
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: deriv_bot
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    # [NUEVO] Configuración de performance
    command: >
      postgres 
      -c shared_buffers=2GB 
      -c effective_cache_size=4GB 
      -c work_mem=256MB
      -c maintenance_work_mem=512MB
      -c max_parallel_workers_per_gather=4
    
  redis:
    image: redis:7-alpine
    restart: always
    volumes:
      - redis_data:/data
    
  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d
      - ./certbot/conf:/etc/letsencrypt
    
  prometheus:
    image: prom/prometheus
    restart: always
    volumes:
      - ./prometheus:/etc/prometheus
    
  grafana:
    image: grafana/grafana
    restart: always
    ports:
      - "3001:3000"
    
  # [NUEVO] Watchdog — monitorea que el bot esté vivo
  watchdog:
    build: ./watchdog
    restart: always
    depends_on: [bot-backend]
    environment:
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - BOT_HEALTH_URL=http://bot-backend:8000/health

volumes:
  postgres_data:
  redis_data:
```

## 8.2 Variables de Entorno (.env)

```env
# Deriv
DERIV_API_TOKEN=xxxxx
DERIV_APP_ID=xxxxx
DERIV_ACCOUNT_TYPE=demo

# Groq
GROQ_API_KEY=gsk_xxxxx
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_TEMPERATURE=0.05
GROQ_MAX_TOKENS=1500
GROQ_TIMEOUT_SECONDS=8

# PostgreSQL
DB_USER=deriv_bot
DB_PASSWORD=xxxxx
DB_NAME=deriv_bot

# Redis
REDIS_URL=redis://redis:6379

# Telegram
TELEGRAM_BOT_TOKEN=xxxxx
TELEGRAM_CHAT_ID=xxxxx

# Dashboard
DASHBOARD_ADMIN_EMAIL=admin@jhonk.online
DASHBOARD_ADMIN_PASSWORD=xxxxx
JWT_SECRET=xxxxx

# SSL
DOMAIN=bot.jhonk.online

# [NUEVO] Risk Management
KELLY_FRACTION=0.25
MAX_DAILY_LOSS_PCT=8.0
MAX_DRAWDOWN_PCT=25.0
MAX_CONCURRENT_TRADES=3
MAX_CORRELATED_TRADES=2

# [NUEVO] Feature Flags
ENABLE_AB_TESTING=false
ENABLE_GROQ_FALLBACK=true
ENABLE_DRAWDOWN_RECOVERY=true
```

## 8.3 Requisitos del VPS

| Recurso | Mínimo | Recomendado |
|---------|--------|-------------|
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Almacenamiento | 100 GB SSD | 250 GB NVMe |
| Ancho de banda | 1 Gbps | 1 Gbps |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |

---

# 9. REQUERIMIENTOS DE SEGURIDAD

1. Todas las API keys encriptadas en .env, nunca en código
2. Dashboard con JWT y rate limiting (max 100 req/min)
3. HTTPS obligatorio con Let's Encrypt
4. Firewall: solo puertos 80, 443, SSH
5. Deriv API token con permisos mínimos (trade + read)
6. Backups automáticos diarios de PostgreSQL (retención 30 días)
7. Logs rotados, almacenados 90 días
8. Monitoreo de salud con alertas por Telegram
9. [NUEVO] Watchdog container que reinicia el bot si detecta inactividad
10. [NUEVO] Kill switch remoto vía Telegram: enviar "/stop" para detener el bot inmediatamente

---

# 10. EDGE CASES Y PROTECCIÓN [NUEVO]

| Escenario | Respuesta del Sistema |
|-----------|----------------------|
| Groq API caído | Fallback mecánico (capas 1+2), stake reducido 50%. Alerta por Telegram. |
| Groq responde JSON inválido | Retry 1 vez. Si falla de nuevo, fallback mecánico. Log del error. |
| Groq confianza > 0.95 | Auto-reducir a 0.85. Flagear como posible alucinación. |
| Deriv WebSocket cae | Reconexión con backoff exponencial. Si 5+ reconexiones en 10 min → pause bot. |
| Trade abierto y WS cae | NO abrir nuevos trades. Esperar reconexión. El trade existente se resuelve en Deriv. |
| Deriv cambia comportamiento de sintéticos | Si Hurst/GARCH/Weibull detectan distribución diferente por 48h → alerta de regime change. Pausar y recalibrar modelos. |
| Bug genera trades en loop | Max 40 trades/día hardcodeado. Max 1 trade cada 30 segundos. Circuit breaker si > 5 trades en 5 min. |
| Balance llega a $0 | Stop completo inmediato. Alerta CRÍTICA. Requiere intervención manual y recapitalización. |
| pgvector retorna similitud < 0.50 | Marcar como "no_match". No cuenta como confluencia. Log warning. |
| Redis cae | El bot puede operar sin Redis (pierde cache, funciona más lento). Alerta por Telegram. |
| PostgreSQL cae | Stop completo. Sin BD no se puede registrar nada. Alerta CRÍTICA. |

---

# 11. FASES DE DESARROLLO [MEJORADO]

## Fase 1 — Infraestructura Base (Semana 1-2)
- Setup Docker Compose con todos los servicios
- Conexión WebSocket a Deriv API
- Schema completo de PostgreSQL + pgvector + TimescaleDB
- Recolección de ticks y construcción de velas multi-timeframe
- Detector de spikes para Crash/Boom
- Tests de conexión, persistencia, y reconexión

## Fase 2 — Modelos Estadísticos (Semana 3-4) [MEJORADO]
- Cálculo de indicadores técnicos y features avanzados
- Implementación de HMM para detección de regímenes
- Implementación de modelo Ornstein-Uhlenbeck para mean reversion
- Implementación de GARCH para forecast de volatilidad
- Implementación de modelo Weibull para spikes de Crash/Boom
- Hurst exponent calculator
- Detección de patrones SMC (OB, FVG, BOS, CHoCH)

## Fase 3 — pgvector y Groq (Semana 5-6) [MEJORADO]
- Vectorización de patrones (360 dimensiones, z-score normalization)
- Búsqueda de similitud con decaimiento temporal y filtro de régimen
- Integración con Groq API (system prompt completo + few-shot examples)
- Validación de respuestas con todas las reglas anti-alucinación
- Fallback mecánico cuando Groq no disponible
- Kelly Criterion position sizing

## Fase 4 — Motor de Ejecución (Semana 7)
- Ejecución de trades vía Deriv WebSocket
- Risk management completo (correlación, drawdown recovery, Kelly)
- Feedback loop con A/B testing framework
- Proceso batch nocturno de optimización
- Notificaciones Telegram completas

## Fase 5 — Dashboard (Semana 8-10)
- Dashboard principal con gráficos en tiempo real
- Panel de IA con reasoning chain y concordancia de capas
- Página de trades con decision path y layers agreement
- Página de análisis con régimen, Crash/Boom, O-U
- Página de rendimiento con A/B testing y leading indicators
- Página de configuración con Kelly, A/B, drawdown recovery
- Autenticación y seguridad

## Fase 6 — Testing y Recolección de Datos (Semana 11-13) [MEJORADO]
- Recolección de datos mínimo 2 semanas antes de operar
- Ajuste de modelos con datos reales (HMM, O-U, Weibull)
- Testing extensivo en cuenta demo
- A/B testing: sistema completo vs mecánico solo
- Optimización de prompt de Groq basado en resultados
- Ajuste de parámetros de Kelly y risk management
- Documentación completa

## Fase 7 — Go Live (Semana 14)
- Deployment en VPS de producción
- Migración de demo a real con capital mínimo ($50-100)
- Monitoreo intensivo primeras 2 semanas
- Ajustes finales basados en datos reales

---

# 12. MÉTRICAS DE ÉXITO [MEJORADO]

El bot se considerará exitoso si después de 30 días en cuenta real cumple:

| Métrica | Objetivo Mínimo | Objetivo Óptimo |
|---------|-----------------|-----------------|
| Win rate | > 58% | > 65% |
| Profit factor | > 1.4 | > 2.0 |
| Max drawdown | < 15% | < 10% |
| Uptime del sistema | > 99% | > 99.9% |
| Groq accuracy | > 60% | > 70% |
| Groq valor agregado vs mecánico | > +3% win rate | > +8% win rate |
| pgvector valor agregado | > +5% win rate | > +12% win rate |
| Retorno mensual | > 5% | > 15% |
| Trades por día | 8-25 | 12-20 |
| Sharpe ratio | > 1.5 | > 2.5 |
| Recovery factor | > 2.0 | > 4.0 |

[MEJORADO] Se agregan métricas de valor agregado por capa (Groq y pgvector), Sharpe ratio, y recovery factor. Los objetivos de drawdown son más estrictos (15% vs 20% original). Win rate objetivo subido de 55% a 58%.

---

# 13. NOTAS TÉCNICAS ADICIONALES

## 13.1 Sobre los Índices Sintéticos de Deriv
Los índices sintéticos son generados por un algoritmo criptográficamente seguro. Tienen propiedades estadísticas estables y conocidas:
- Volatility indices mantienen su volatilidad objetivo → explotable con mean reversion (O-U)
- Crash/Boom tienen distribución Weibull de intervalos entre spikes → hazard rate creciente
- Los patrones técnicos se generan intencionalmente para simular mercados → SMC funciona por diseño
- [NUEVO] IMPORTANTE: Si Deriv actualiza su generador, los modelos estadísticos necesitan recalibrarse. El sistema de detección de régimen y los health checks nocturnos detectarán esto.

## 13.2 Sobre Groq como Capa de Decisión
Groq es un filtro inteligente, no un oráculo:
- Sintetiza información de múltiples fuentes
- El chain-of-thought y abogado del diablo reducen decisions impulsivas
- La meta-confianza permite auto-regulación
- [NUEVO] Si después de 30 días Groq no aporta > 3% win rate vs mecánico solo, considerar simplificar el sistema a solo capas 1+2

## 13.3 Sobre pgvector y Búsqueda de Patrones
- El decaimiento temporal evita que patrones obsoletos contaminen decisiones
- El filtro de régimen asegura que se comparen situaciones realmente similares
- [NUEVO] Los vectores de 360 dimensiones con z-score normalization capturan más información que los 140 originales con min-max
- Se recomienda mínimo 2-4 semanas de recolección antes de confiar en la búsqueda de similitud

## 13.4 [NUEVO] Sobre el Framework de A/B Testing
El A/B testing no es opcional — es lo que permite evolucionar el sistema con evidencia:
- Cada trade registra qué habría decidido cada capa
- Después de 100+ trades se puede calcular significancia estadística
- Si una capa no aporta valor, se puede desactivar sin perder el resto
- Esto permite iteración continua basada en datos, no en intuición

---

# FIN DEL DOCUMENTO V2.0

Este prompt optimizado implementa mejoras en 8 áreas clave respecto al V1.0:
1. Estrategia: Modelos estadísticos especializados (O-U, GARCH, Weibull, HMM) adaptados a la naturaleza algorítmica de los sintéticos
2. Groq: Chain-of-thought, abogado del diablo, anti-alucinación, few-shot examples, calibración de confianza
3. Risk Management: Kelly Criterion, correlación, drawdown recovery progresivo
4. pgvector: Decaimiento temporal, filtro de régimen, vectores de 360 dimensiones con z-score
5. Feedback Loop: Meta-confianza, A/B testing, proceso nocturno, health checks
6. Estrategias Crash/Boom: Modelo Weibull con hazard rate creciente
7. Mean Reversion: Modelo Ornstein-Uhlenbeck para Volatility indices
8. Edge Cases: Manejo detallado de 12 escenarios de fallo

Cualquier decisión no cubierta queda a criterio de Antigravity, priorizando: estabilidad > seguridad del capital > rentabilidad > features del dashboard.
