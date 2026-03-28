---
phase: 05-human-takeover
plan: "01"
subsystem: conversation-state
tags: [human-takeover, sqlalchemy, state-machine, bot-gate]
dependency_graph:
  requires: [agent/memory.py, agent/main.py]
  provides: [ConversationState DB table, obtener_estado, set_estado, state gate in webhook]
  affects: [agent/main.py webhook handler, all future takeover plans]
tech_stack:
  added: []
  patterns: [SQLAlchemy upsert, async state gate in webhook loop, asyncio background timeout loop]
key_files:
  created: [agent/takeover.py]
  modified: [agent/memory.py, agent/main.py, .env.example]
decisions:
  - "ConversationState uses unique=True on telefono for safe upsert without conflicts"
  - "State gate uses continue — complete skip of Claude, typing indicator, history save (silence is correct per HT-04)"
  - "VENDEDOR_WHATSAPP warning logged at startup using os.getenv in lifespan() body (not module-level to respect dotenv load order)"
  - "takeover.py timeout_loop designed to be started via asyncio.create_task() in lifespan — wired in plan 05-03"
metrics:
  duration: "2 min 22 sec"
  completed: "2026-03-28"
  tasks: 2
  files_changed: 4
---

# Phase 5 Plan 01: Conversation State Foundation Summary

ConversationState SQLAlchemy model + CRUD module (takeover.py) + HT-04 state gate in webhook handler — bot goes fully silent when conversation is in "humano" mode.

## What Was Built

### ConversationState Model (agent/memory.py)
New SQLAlchemy model added after the existing `Mensaje` class. Uses the same `Base` so `inicializar_db()` auto-creates the `conversation_states` table on first run. Key design choices:
- `telefono` has `unique=True` + `index=True` — enables safe upsert and fast lookup
- `estado` default is `"bot"` — absence of a row == bot mode (no row needed until takeover occurs)
- `vendedor` stored for future per-vendor routing (Phase 6+)
- `updated_at` enables timeout queries (find all humano rows older than N hours)

### agent/takeover.py (new module)
Complete CRUD + notification + timeout logic:
- `obtener_estado(telefono)` — returns estado or "bot" if no row exists (safe default)
- `set_estado(telefono, estado, vendedor)` — upsert using select-then-update/insert pattern
- `construir_mensaje_vendedor(cliente_telefono, resumen)` — WhatsApp-formatted takeover notification with #bot command hint
- `check_and_apply_timeouts(timeout_hours)` — finds stale humano rows and returns them to bot
- `devolver_todas_al_bot()` — bulk return for #bot-all vendor command (wired in plan 05-03)
- `timeout_loop()` — asyncio infinite loop for hourly timeout checks (started in plan 05-03 lifespan)

### State Gate in main.py (HT-04)
Inserted after the rate limit check, before obtener_historial:
```python
estado_conv = await obtener_estado(telefono_normalizado)
if estado_conv == "humano":
    logger.info(f"Conversacion {telefono_normalizado} en modo HUMANO — bot en pausa")
    continue  # Saltar completamente
```
The `continue` skips: typing indicator, obtener_historial, generar_respuesta, guardar_mensaje, enviar_respuesta. Total silence — no bot response, no history saved.

### .env.example
Added `VENDEDOR_WHATSAPP` (full international format, digits-only) and `TAKEOVER_TIMEOUT_HOURS=4` with clear documentation.

## Verification Results

All plan verification checks passed:
1. `from agent.memory import ConversationState; from agent.takeover import obtener_estado, set_estado` — OK
2. `from agent.main import app` — OK (no import errors)
3. `grep "estado_conv" agent/main.py` — found at lines 171-174 (gate in webhook handler)
4. `grep "VENDEDOR_WHATSAPP" .env.example` — found (env var documented)

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | c3c0ad0 | feat(05-01): add ConversationState model + takeover.py CRUD + env vars |
| Task 2 | 2140273 | feat(05-01): add state gate in main.py webhook handler (HT-04) |

## Deviations from Plan

None — plan executed exactly as written.

## What's Next

Plan 05-02 will add the `solicitar_humano` Claude tool in tools.py + brain.py dispatcher, and the prompts.yaml takeover trigger instructions. Plan 05-03 wires the vendor command routing + timeout loop startup in lifespan().

## Self-Check: PASSED

- `agent/takeover.py` exists: FOUND
- `agent/memory.py` contains `ConversationState`: FOUND
- `agent/main.py` contains `estado_conv`: FOUND
- `.env.example` contains `VENDEDOR_WHATSAPP`: FOUND
- Commit c3c0ad0: FOUND
- Commit 2140273: FOUND
