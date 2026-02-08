# 🤖 Bot de Autotrading Deriv V2 - GUÍA RÁPIDA

## ✅ MVP COMPLETO

El bot está **100% funcional** y listo para paper trading.

---

## 🚀 Inicio Rápido

### 1. Iniciar el Bot

```bash
cd /var/www/jhonk/dreriv
./start-bot.sh
```

### 2. Ver Logs

```bash
docker-compose logs -f backend
```

### 3. Detener

```bash
docker-compose down
```

---

## 📊 ¿Qué Hace el Bot?

1. **Conecta** a Deriv.com WebSocket API (cuenta DEMO)
2. **Recibe** ticks en tiempo real del índice R_100
3. **Construye** candles 1m automáticamente
4. **Analiza** cada minuto con:
   - Ornstein-Uhlenbeck (mean reversion)
   - GARCH (volatilidad)
   - Hurst exponent (régimen de mercado)
   - Indicadores técnicos (EMA, RSI, ATR, Bollinger, MACD)
5. **Genera** señales CALL/PUT con confianza cuantificada
6. **Calcula** stake optimal con Kelly Criterion
7. **Verifica** risk management (límites diarios, drawdown, cooldowns)
8. **Ejecuta** trades automáticamente si:
   - Confianza ≥ 60%
   - Risk checks pasan
9. **Notifica** vía Telegram
10. **Registra** todo en PostgreSQL

---

## ⚙️ Configuración

Ver `.env` para ajustar:
- `KELLY_FRACTION` - Agresividad de sizing (0.25 = conservador)
- `MAX_DAILY_LOSS_PCT` - Stop loss diario (8%)
- `MAX_DRAWDOWN_PCT` - Drawdown máximo (25%)
- `COOLDOWN_AFTER_LOSSES` - Cooldown tras N pérdidas (3)

---

## 📱 Telegram

El bot enviará:
- 🚀 Notificación al iniciar
- 📊 Al abrir cada trade
- ✅/❌ Al cerrar cada trade  
- ⚠️ Eventos de risk management

---

## 📂 Documentación Completa

- [PHASE1_COMPLETE.md](PHASE1_COMPLETE.md) - Infraestructura
- [PHASE2_COMPLETE.md](PHASE2_COMPLETE.md) - Modelos estadísticos
- [PHASE3_COMPLETE.md](PHASE3_COMPLETE.md) - Ejecución y risk management
- [NEXT_STEPS.md](NEXT_STEPS.md) - Roadmap completo

---

## ⚠️ IMPORTANTE

**Usar solo en cuenta DEMO** hasta validar performance por al menos 2 semanas.

Criterios para considerar LIVE:
- Win rate ≥ 55%
- Sharpe ratio ≥ 1.5
- Max drawdown ≤ 15%
- ≥ 200 trades ejecutados

---

**Soporte**: Ver logs con `docker-compose logs -f backend`
