# 🚀 GUÍA DE SKILLS PARA ANTIGRAVITY — BOT DERIV V2

## RESUMEN

Esta guía explica cómo instalar y usar **dos tipos de skills** en Antigravity para maximizar la calidad del código del bot de trading:

1. **Skills de la comunidad** (700+ probados) — mejoran la programación general
2. **Skills custom** (6 creados por nosotros) — conocimiento específico del bot de Deriv

---

## PASO 1: Instalar Skills de la Comunidad

Estos son skills genéricos que mejoran CÓMO programa el agente (mejores patrones, seguridad, Docker, etc.)

### Opción A: Instalación completa (recomendada)
```bash
# En la terminal de Antigravity, dentro del proyecto del bot:
npx antigravity-awesome-skills
```
Esto clona 700+ skills en `.agent/skills/`

### Opción B: Instalación selectiva (solo los que necesitamos)
```bash
# Desde el repo rmyndharis que permite instalar individual:
npx @rmyndharis/antigravity-skills install fastapi-pro
npx @rmyndharis/antigravity-skills install python-pro
npx @rmyndharis/antigravity-skills install docker-expert
npx @rmyndharis/antigravity-skills install async-python-patterns
npx @rmyndharis/antigravity-skills install postgresql-schema-design
npx @rmyndharis/antigravity-skills install api-security-best-practices
npx @rmyndharis/antigravity-skills install nextjs-app-router-patterns
npx @rmyndharis/antigravity-skills install senior-architect
npx @rmyndharis/antigravity-skills install observability-engineer
npx @rmyndharis/antigravity-skills install typescript-pro
```

### Skills de comunidad que nos sirven:

| Skill | Para qué nos sirve |
|-------|-------------------|
| **fastapi-pro** | Backend principal del bot — async APIs, WebSockets, Pydantic V2 |
| **python-pro** | Mejores patrones Python, type hints, manejo de errores |
| **async-python-patterns** | Asyncio correcto para WebSocket streaming + tareas concurrentes |
| **docker-expert** | Docker Compose multi-container, health checks, optimización |
| **postgresql-schema-design** | Diseño de schema, índices, constraints, performance |
| **api-security-best-practices** | JWT auth, rate limiting, validación de input |
| **nextjs-app-router-patterns** | Dashboard Next.js 14 con App Router |
| **typescript-pro** | TypeScript sólido para el frontend |
| **senior-architect** | Decisiones de arquitectura, escalabilidad, patrones |
| **observability-engineer** | Logging, métricas, monitoreo del bot |
| **frontend-design** | UI/UX profesional para el dashboard |
| **auth-implementation-patterns** | Login seguro para el dashboard |

---

## PASO 2: Instalar Skills Custom (Bot de Deriv)

Estos skills contienen conocimiento **específico** que los skills genéricos NO tienen:
- Cómo conectarse al WebSocket de Deriv
- Cómo usar Groq para decisiones de trading con anti-alucinación
- Cómo hacer vectorización de velas con pgvector
- Modelos estadísticos (GARCH, O-U, Weibull, HMM)
- Risk management con Kelly Criterion
- Dashboard de trading en tiempo real

### Instalación:
```bash
# Copiar los skills custom al proyecto
cp -r antigravity-skills/* .agent/skills/

# O si quieres que estén disponibles en TODOS tus proyectos:
cp -r antigravity-skills/* ~/.gemini/antigravity/skills/
```

### Nuestros 6 Skills Custom:

| Skill | Contenido |
|-------|-----------|
| **deriv-websocket-trading** | API Deriv WS v3, autenticación, suscripciones, ejecución de trades, tipos de contrato, manejo de errores, reconexión automática |
| **groq-trading-decisions** | Integración Groq, prompt engineering para trading, chain-of-thought, abogado del diablo, validación de respuestas JSON, meta-confianza, fallback |
| **pgvector-pattern-matching** | Vectorización 360D con z-score, HNSW tuning, temporal decay, filtro de régimen, feedback loop de quality scores |
| **statistical-trading-models** | GARCH(1,1), Ornstein-Uhlenbeck, Weibull para Crash/Boom, HMM de régimen, Hurst exponent — con código completo y parámetros |
| **trading-risk-management** | Kelly Criterion fraccional, límites hardcoded, drawdown progresivo, correlación de instrumentos, circuit breakers, A/B testing |
| **realtime-trading-dashboard** | TradingView Lightweight Charts, Socket.IO streaming, Next.js 14, shadcn/ui, dark theme, componentes de trading |

---

## PASO 3: Verificar que los Skills están cargados

En Antigravity, abre la terminal del agente y pregunta:
```
¿Qué skills tienes disponibles relacionados con Deriv, trading, o pgvector?
```

El agente debería listar nuestros 6 skills custom.

---

## PASO 4: Cómo usar los Skills en el desarrollo

### Estructura de carpetas del proyecto:
```
deriv-bot-v2/
├── .agent/
│   └── skills/              ← SKILLS VAN AQUÍ
│       ├── deriv-websocket-trading/
│       │   └── SKILL.md
│       ├── groq-trading-decisions/
│       │   └── SKILL.md
│       ├── pgvector-pattern-matching/
│       │   └── SKILL.md
│       ├── statistical-trading-models/
│       │   └── SKILL.md
│       ├── trading-risk-management/
│       │   └── SKILL.md
│       ├── realtime-trading-dashboard/
│       │   └── SKILL.md
│       ├── fastapi-pro/          ← (comunidad)
│       ├── docker-expert/        ← (comunidad)
│       ├── python-pro/           ← (comunidad)
│       └── ...
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── deriv_client.py
│   │   ├── groq_engine.py
│   │   ├── models/
│   │   │   ├── garch.py
│   │   │   ├── ornstein_uhlenbeck.py
│   │   │   ├── weibull_spike.py
│   │   │   ├── hmm_regime.py
│   │   │   └── hurst.py
│   │   ├── pgvector/
│   │   ├── risk_manager.py
│   │   └── ...
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/
│   ├── app/
│   ├── components/
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
└── prompt-bot-deriv-v2-optimizado.md   ← La especificación completa
```

### Ejemplo de prompts para el agente:

**Fase 1 — Infraestructura:**
```
Crea la infraestructura base del bot de trading según la especificación 
en prompt-bot-deriv-v2-optimizado.md. 

Usa los skills de deriv-websocket-trading para el cliente WebSocket,
docker-expert para los contenedores, y postgresql-schema-design para
la base de datos con pgvector.

Empieza con:
1. docker-compose.yml con PostgreSQL (pgvector + timescaledb) y backend FastAPI
2. Schema de base de datos completo
3. Cliente WebSocket de Deriv con reconexión automática
```

**Fase 2 — Modelos estadísticos:**
```
Implementa los 4 modelos estadísticos del skill statistical-trading-models:
1. GARCH para forecast de volatilidad
2. Ornstein-Uhlenbeck para mean reversion en V75/V100
3. Weibull para predicción de spikes en Crash/Boom
4. HMM para detección de régimen
5. Hurst exponent

Sigue el código de referencia del skill y las especificaciones del documento V2.
```

**Fase 3 — Groq + pgvector:**
```
Implementa el motor de decisiones usando los skills groq-trading-decisions 
y pgvector-pattern-matching:
1. Vectorización 360D de velas con z-score
2. HNSW index con los parámetros del skill (m=24, ef_construction=128)
3. Temporal decay y filtro de régimen en las queries
4. Prompt de Groq con chain-of-thought de 7 pasos
5. Validación de respuesta y meta-confianza
6. Fallback mecánico cuando Groq no está disponible
```

**Fase 4 — Risk Management:**
```
Implementa el sistema de risk management del skill trading-risk-management:
1. Kelly Criterion fraccional para sizing
2. Drawdown recovery progresivo
3. Límites de correlación entre instrumentos
4. Circuit breakers
5. Framework de A/B testing
```

**Fase 5 — Dashboard:**
```
Crea el dashboard de trading usando el skill realtime-trading-dashboard 
y nextjs-app-router-patterns:
1. TradingView Lightweight Charts con candles en tiempo real
2. Socket.IO streaming desde el backend
3. Cards de métricas (P&L, win rate, drawdown, Groq meta-confidence)
4. Panel de decisión de Groq expandible con reasoning chain
5. Tabla de trades activos e históricos
6. Página de analytics con equity curve y A/B testing results
```

---

## CÓMO FUNCIONA LA MAGIA

Cuando le pides algo al agente de Antigravity:

1. **El agente lee las descriptions** de todos los skills (solo metadata, liviano)
2. **Detecta cuáles son relevantes** a tu petición
3. **Carga el SKILL.md completo** de los skills relevantes a su contexto
4. **Usa ese conocimiento** para escribir código de mayor calidad

Por ejemplo, si dices "crea el cliente WebSocket de Deriv":
- El agente carga automáticamente `deriv-websocket-trading/SKILL.md`
- Lee que debe usar `wss://ws.derivws.com/websockets/v3?app_id={APP_ID}`
- Sabe que debe autenticar ANTES de suscribirse
- Implementa reconexión con exponential backoff
- Maneja los error codes específicos de Deriv
- Todo sin que tú tengas que explicarle nada de eso

Sin el skill, el agente habría tenido que "inventar" o buscar en internet cómo funciona la API de Deriv. Con el skill, **ya sabe exactamente cómo hacerlo**.

---

## RESUMEN DE BENEFICIO

| Sin Skills | Con Skills |
|-----------|-----------|
| Agente genera código genérico | Código específico para Deriv + trading |
| Puede inventar endpoints que no existen | Usa la API real de Deriv documentada |
| Prompt de Groq básico | Prompt con anti-alucinación y few-shot examples |
| pgvector sin optimizar | HNSW tuneado para 360 dimensiones |
| Risk management básico (% fijo) | Kelly Criterion + drawdown progresivo |
| Modelos estadísticos genéricos | GARCH/O-U/Weibull/HMM con parámetros probados |
| Dashboard genérico | TradingView + componentes de trading especializados |

---

## NOTAS IMPORTANTES

1. **Los skills NO reemplazan la especificación V2** — la spec dice QUÉ construir, los skills dicen CÓMO construirlo bien
2. **El documento V2 (prompt-bot-deriv-v2-optimizado.md)** debe estar en la raíz del proyecto para que el agente lo use como referencia
3. **Reinicia la sesión del agente** después de agregar skills nuevos
4. **No instales TODOS los 700+ skills** si usas la opción selectiva — muchos son irrelevantes (Shopify, mobile, etc.) y pueden confundir al agente
