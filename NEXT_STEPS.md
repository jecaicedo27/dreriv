# 🚀 PRÓXIMOS PASOS — BOT DERIV V2

**Fecha**: 7 de febrero de 2026  
**Proyecto aprobado**: ✅ Path MVP recomendado (8-10 semanas, $8-12k)

---

## ✅ COMPLETADO

- [x] Revisión técnica completa de la especificación
- [x] Análisis de arquitectura y modelos estadísticos
- [x] Timeline y costos estimados
- [x] Skills custom creados y listos para configurar

---

## 🎯 PASO 1: Configurar Skills (HOY)

### Opción A: Automática
```bash
cd /var/www/jhonk/dreriv
./setup-skills.sh
```

### Opción B: Manual
```bash
cd /var/www/jhonk/dreriv
mkdir -p .agent/skills
cp -r skills/mnt/user-data/outputs/antigravity-skills/* .agent/skills/
```

### Verificación
Después de copiar los skills, pregúntale a Antigravity:
```
¿Qué skills tienes disponibles relacionados con Deriv, trading, o pgvector?
```

Deberías ver los 6 skills custom listados.

---

## 📋 PASO 2: Setup Inicial del Proyecto (Semana 1, Días 1-2)

### 2.1 Crear Cuentas y API Keys

**Deriv.com**:
1. Ir a https://deriv.com
2. Crear cuenta DEMO (no real todavía)
3. Ir a https://app.deriv.com/account/api-token
4. Crear API token con permisos: `read`, `trade`, `trading_information`
5. Guardar el token (empieza con letras y números)

**Deriv App ID**:
1. Ir a https://developers.deriv.com
2. Registrar tu aplicación
3. Obtener App ID (número de 5 dígitos)

**Groq API**:
1. Ir a https://console.groq.com
2. Crear cuenta (gratis con rate limits)
3. Generar API key
4. (Opcional) Upgrade a plan premium si necesitas más requests

**Telegram Bot**:
1. Hablar con @BotFather en Telegram
2. Crear nuevo bot: `/newbot`
3. Guardar el token
4. Obtener tu Chat ID: habla con @userinfobot

### 2.2 Crear Estructura del Proyecto

```bash
cd /var/www/jhonk/dreriv
mkdir -p deriv-bot-v2/{backend,dashboard,nginx,prometheus,watchdog}
cd deriv-bot-v2

# Crear .env
cat > .env << 'EOF'
# Deriv
DERIV_API_TOKEN=tu_token_aqui
DERIV_APP_ID=12345
DERIV_ACCOUNT_TYPE=demo

# Groq
GROQ_API_KEY=gsk_tu_key_aqui
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_TEMPERATURE=0.05
GROQ_MAX_TOKENS=1500
GROQ_TIMEOUT_SECONDS=8

# PostgreSQL
DB_USER=deriv_bot
DB_PASSWORD=genera_password_seguro
DB_NAME=deriv_bot

# Redis
REDIS_URL=redis://redis:6379

# Telegram
TELEGRAM_BOT_TOKEN=tu_bot_token
TELEGRAM_CHAT_ID=tu_chat_id

# Dashboard
DASHBOARD_ADMIN_EMAIL=admin@jhonk.online
DASHBOARD_ADMIN_PASSWORD=genera_password_seguro
JWT_SECRET=genera_secret_aleatorio

# Risk Management (MVP)
KELLY_FRACTION=0.25
MAX_DAILY_LOSS_PCT=8.0
MAX_DRAWDOWN_PCT=25.0
MAX_CONCURRENT_TRADES=3
MAX_CORRELATED_TRADES=2

# Feature Flags (MVP - Groq y pgvector desactivados inicialmente)
ENABLE_GROQ=false
ENABLE_PGVECTOR=false
ENABLE_AB_TESTING=true
ENABLE_DRAWDOWN_RECOVERY=true
EOF
```

---

## 🏗️ PASO 3: Desarrollo — Path MVP (8 semanas)

### Semanas 1-2: Infraestructura Base

**Prompt para Antigravity**:
```
Vamos a construir el bot de trading de Deriv.com según la 
especificación en prompt-bot-deriv-v2-optimizado.md.

Empezaremos con el PATH MVP (8 semanas), implementando SOLO la capa 1 
(modelos estadísticos) inicialmente.

Fase 1 - Infraestructura Base:
1. Crea docker-compose.yml con:
   - PostgreSQL 16 con pgvector y TimescaleDB
   - Redis
   - Backend FastAPI skeleton
   
2. Implementa el schema completo de base de datos según la especificación
   (usa el skill postgresql-schema-design)
   
3. Crea el cliente WebSocket de Deriv con reconexión automática
   (usa el skill deriv-websocket-trading)
   
Sigue las mejores prácticas de los skills y la especificación V2.
```

### Semanas 3-4: Modelos Estadísticos (Capa 1 SOLO)

**Para MVP, implementar solo**:
- Ornstein-Uhlenbeck (mean reversion para V75/V100)
- GARCH (forecast de volatilidad)
- Hurst exponent (detectar trending vs mean-revert)
- Indicadores básicos (EMA, RSI, ATR, Bollinger)

**Dejar para después del MVP**:
- HMM (régimen detection) → usar reglas simples inicialmente
- Weibull (spikes Crash/Boom) → enfocarse en Volatility indices primero
- SMC (Order Blocks, FVG) → nice to have, no crítico

**Prompt para Antigravity**:
```
Fase 2 - Modelos Estadísticos MVP:

Implementa estos 3 modelos usando el skill statistical-trading-models:

1. Ornstein-Uhlenbeck para mean reversion (V75/V100)
   - Fit con últimas 200 velas
   - Señal cuando desviación > 2σ del equilibrio
   
2. GARCH(1,1) para volatilidad
   - Forecast 5 períodos adelante
   - Detectar expansión/contracción
   
3. Hurst exponent
   - Ventana de 200 velas
   - Si H < 0.45 → mean-revert (favorable)
   - Si 0.45 < H < 0.55 → random walk (reducir trades)
   - Si H > 0.55 → trending (favorable)

Sigue el código de referencia del skill para implementación correcta.
```

### Semana 5: Motor de Ejecución

```
Fase 3 - Ejecución MVP:

1. Implementa decisión mecánica simple (sin Groq):
   - IF O-U desviación > 2σ AND Hurst < 0.5 AND GARCH estable 
     → Señal de reversión
   
2. Implementa Kelly Criterion sizing (usa skill trading-risk-management)

3. Ejecuta trades vía Deriv WebSocket (usa skill deriv-websocket-trading)

4. Risk management:
   - Límite diario 8%
   - Drawdown recovery progresivo
   - Max 3 trades simultáneos
   - Circuit breaker
```

### Semana 6: Dashboard Básico

```
Fase 4 - Dashboard MVP:

Crea dashboard Next.js minimalista con:
1. Métricas principales (balance, P&L, win rate)
2. TradingView chart básico (usa skill realtime-trading-dashboard)
3. Tabla de trades activos e históricos
4. Página de configuración básica

No implementar todavía:
- Panel de Groq (no hay Groq en MVP)
- Análisis de régimen avanzado
- A/B testing UI (se registra en backend, no necesita UI aún)
```

### Semanas 7-8: Testing

**Semana 7**: Recolección de datos (modo observación, no opera)
**Semana 8**: Paper trading en DEMO + ajustes

---

## 📊 PASO 4: Evaluación del MVP (Fin de Semana 8)

Después de 1 semana de paper trading en DEMO, evaluar:

**Si win rate > 60%**:
- ✅ El edge de los modelos estadísticos es REAL
- → Proceder a agregar Capa 2 (pgvector) en 2 semanas más
- → Después agregar Capa 3 (Groq) en 2 semanas más

**Si win rate 55-60%**:
- ⚠️ Edge marginal
- → Ajustar parámetros de los modelos
- → Probar 1 semana más
- → Si no mejora, replantear estrategia

**Si win rate < 55%**:
- 🔴 No hay edge suficiente
- → Analizar qué modelo está fallando
- → Considerar estrategia diferente

---

## 🎯 CRITERIOS DE ÉXITO MVP (30 días)

| Métrica | MVP Objetivo |
|---------|--------------|
| Win rate | > 58% |
| Profit factor | > 1.4 |
| Max drawdown | < 15% |
| Uptime | > 99% |
| Trades/día | 8-20 |

Si cumples estos objetivos, el MVP es exitoso y puedes escalar a Full System.

---

## 💡 RECURSOS

### Documentación
- [Especificación completa](file:///var/www/jhonk/dreriv/prompt-bot-deriv-v2-optimizado.md)
- [Análisis técnico](file:///root/.gemini/antigravity/brain/64907adc-2984-48db-8d40-55bc69f04785/technical_analysis.md)
- [Executive summary](file:///root/.gemini/antigravity/brain/64907adc-2984-48db-8d40-55bc69f04785/executive_summary.md)
- [Guía de skills](file:///var/www/jhonk/dreriv/skills/GUIA_INSTALACION.md)

### APIs y Servicios
- Deriv API Docs: https://developers.deriv.com
- Deriv WebSocket Playground: https://api.deriv.com/api-explorer
- Groq API Docs: https://console.groq.com/docs
- pgvector Docs: https://github.com/pgvector/pgvector

### Skills Disponibles
Los 6 skills custom están en `.agent/skills/`:
1. `deriv-websocket-trading` — Conexión a Deriv
2. `statistical-trading-models` — GARCH, O-U, Weibull, HMM
3. `trading-risk-management` — Kelly, drawdown, limits
4. `groq-trading-decisions` — Prompting avanzado (cuando agregues Groq)
5. `pgvector-pattern-matching` — Vectores 360D (cuando agregues pgvector)
6. `realtime-trading-dashboard` — TradingView charts

---

## ❓ PREGUNTAS FRECUENTES

**P: ¿Por qué MVP sin Groq/pgvector?**
R: Para validar que el edge está en los modelos estadísticos ANTES de agregar complejidad. Si los modelos no funcionan, Groq y pgvector no los salvarán.

**P: ¿Cuándo agregar Groq?**
R: Después de que el MVP demuestre win rate > 60% por 30 días. Entonces Groq puede mejorar aún más.

**P: ¿Cuándo usar dinero real?**
R: Después de 100+ trades en DEMO con win rate > 60%. Empezar con $200-300.

**P: ¿Qué pasa si el MVP no funciona?**
R: Analizar qué componente falla, ajustar parámetros, o considerar estrategia diferente. Mejor descubrirlo en 8 semanas que en 14.

---

## ✅ CHECKLIST INMEDIATO

- [ ] Ejecutar `./setup-skills.sh` para configurar skills
- [ ] Crear cuentas: Deriv DEMO, Groq, Telegram Bot
- [ ] Guardar API keys en archivo seguro (no commitear)
- [ ] Crear estructura del proyecto con .env
- [ ] Comenzar Fase 1 con Antigravity

---

**¿Listo para empezar?** 🚀

Ejecuta el script de skills y luego comienza con el primer prompt de Antigravity para la Fase 1.
