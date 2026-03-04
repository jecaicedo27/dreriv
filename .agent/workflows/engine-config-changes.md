---
description: Cómo hacer cambios a motores de trading — reglas de arquitectura para que los cambios se apliquen en un solo lugar
---

# Regla de Oro: El Motor Define Sus Valores

Cada motor define su configuración en **UN solo lugar**: `backend/app/analysis/engine_registry.py`.

Los orquestadores (bot.py, replay_bot.py, batallas) **leen** esos valores — NUNCA los definen ni sobrescriben.

## Arquitectura

```
engine_registry.py  → QUÉ es cada motor (hurst, slope, cooldown, duration, defensive)
TradingCore.py      → CÓMO se analiza (slope filter, hurst gate, engine.analyze())
KellyCriterion      → CUÁNTO se apuesta (fórmula Kelly desde el balance)

bot.py / replay_bot.py / batallas → ORQUESTAN (leen config, llaman TradingCore)
Frontend → SOLO envía: fecha, nombre del motor — NO envía filtros
```

## Dónde Cambiar Cada Cosa

| Quiero cambiar... | Archivo a modificar | NO tocar |
|---|---|---|
| Hurst, slope, cooldown, duration de un motor | `engine_registry.py` → `_ENGINES[nombre]` | bot.py, replay_bot.py, simulation_api.py |
| Filtros defensivos de un motor | `engine_registry.py` → `_ENGINES[nombre]["defensive"]` | bot.py, replay_bot.py |
| Lógica de análisis (señales CALL/PUT) | `backend/app/analysis/{motor}_engine.py` | Nada más |
| Fórmula de Kelly / stake | `replay_bot.py` L301-305 + `trade_executor.py` | Frontend |
| Filtro de slope (pendiente EMA) | `TradingCore.analyze()` en `trading_core.py` | bot.py (ya lo lee de TradingCore) |
| Agregar un nuevo motor | 1. Crear `{motor}_engine.py` 2. Registrar en `engine_registry.py` | Nada más |

## Checklist Antes de Hacer un Cambio

// turbo-all

1. Identificar QUÉ se va a cambiar (parámetro, lógica, filtro)
2. Buscar en la tabla de arriba DÓNDE vive ese código
3. Cambiar SOLO en ese archivo
4. Verificar que bot.py, replay_bot.py y batallas leen con `get_engine_config()`
5. NO duplicar lógica — si ya existe en TradingCore o engine_registry, importarla

## Flujo de Datos (cómo lee cada componente)

```
engine_registry.py
    ↓ get_engine_config(name)
    ├── bot.py          → L459: eng_cfg = get_engine_config(eng_name)
    ├── replay_bot.py   → __init__: engine_cfg = get_engine_config(self.engine_name)
    └── simulation_api  → L1536: engine_cfg = get_engine_config(engine_name)
```

## Ejemplo: "Cambia el cooldown de bullish_v5 a 10"

✅ Correcto:
```python
# engine_registry.py línea ~48
"cooldown_candles": 10,  # era 7
```
Listo. Aplica automáticamente en bot live, simulaciones y batallas.

❌ Incorrecto:
```python
# bot.py
self.cooldown = 10  # NO — esto solo cambia el live bot
# replay_bot.py
self.cooldown_candles = 10  # NO — esto solo cambia simulaciones
```
