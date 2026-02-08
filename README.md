# 🤖 Bot de Autotrading - Deriv V2

Bot de trading algorítmico para índices sintéticos de Deriv.com con arquitectura de 3 capas:
- **Capa 1**: Modelos estadísticos (O-U, GARCH, Hurst)
- **Capa 2**: Pattern matching con pgvector
- **Capa 3**: Decisión AI con Groq

## 📚 Documentación

- **[NEXT_STEPS.md](NEXT_STEPS.md)** - Guía paso a paso para comenzar
- **[Skills Guide](skills/GUIA_INSTALACION.md)** - Configuración de skills
- **[Especificación Técnica](prompt-bot-deriv-v2-optimizado.md)** - Spec completa (2,156 líneas)

## 🚀 Quick Start

### 1. Configurar Skills (ya hecho ✅)
```bash
./setup-skills.sh
```

### 2. Configurar Variables de Entorno
```bash
cp .env.example .env
# Editar .env con tus API keys (ya configurado ✅)
```

**Pendientes**:
- `DERIV_APP_ID` → Obtener de https://developers.deriv.com
- `TELEGRAM_BOT_TOKEN` → Hablar con @BotFather
- `TELEGRAM_CHAT_ID` → Hablar con @userinfobot

### 3. Iniciar Desarrollo

Ver **[NEXT_STEPS.md](NEXT_STEPS.md)** para el plan completo de desarrollo.

## 🎯 Path MVP (Recomendado)

**Timeline**: 8 semanas  
**Costo**: $8-12k

1. Semanas 1-2: Infraestructura Base
2. Semanas 3-4: Modelos Estadísticos (Capa 1)
3. Semana 5: Motor de Ejecución
4. Semana 6: Dashboard Básico
5. Semanas 7-8: Testing + Go Live

## 📊 Stack Tecnológico

- **Backend**: Python 3.12 + FastAPI
- **Database**: PostgreSQL 16 + pgvector + TimescaleDB
- **Cache**: Redis
- **AI**: Groq API (llama-3.3-70b-versatile)
- **Frontend**: Next.js 14 + TradingView Charts
- **Deployment**: Docker Compose

## ⚙️ Configuración Actual

✅ Skills configurados (6 custom skills)  
✅ API keys configuradas (Groq + Deriv)  
⏳ Deriv App ID pendiente  
⏳ Telegram Bot pendiente  

## 🔒 Seguridad

- ✅ `.env` en `.gitignore` - no commitear secrets
- ✅ Claves API configuradas
- ✅ Passwords generados de forma segura

## 📞 Próximos Pasos

1. Obtener Deriv App ID
2. Crear Telegram Bot
3. Seguir guía en [NEXT_STEPS.md](NEXT_STEPS.md)

---

**Versión**: 2.0  
**Fecha**: Febrero 2026  
**Cliente**: Popping Boba International — Jhonk
