---
phase: 05-human-takeover
plan: 03
subsystem: api
tags: [human-takeover, vendor-commands, whatsapp, asyncio, background-task, timeout]

# Dependency graph
requires:
  - phase: 05-01
    provides: ConversationState DB model, obtener_estado, set_estado
  - phase: 05-02
    provides: solicitar_humano tool, vendor notification on takeover request

provides:
  - procesar_comando_vendedor() — routes #bot/#bot-all/#estado WhatsApp commands
  - devolver_todas_al_bot() — bulk reset all humano conversations to bot
  - check_and_apply_timeouts() — timeout-based auto-return to bot mode
  - timeout_loop() — hourly background task via asyncio.create_task
  - VENDEDOR_PHONE_NORM — module-level normalized vendor phone constant
  - Vendor message interception in webhook handler (before rate limit)
  - Startup timeout check (Pitfall 3 prevention)

affects: [main-webhook-flow, human-takeover, vendor-ux]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Vendor message routing via phone number comparison before rate limit
    - Background asyncio task started in lifespan (not startup event)
    - Startup cleanup pattern for stale DB states on server restart

key-files:
  created: []
  modified:
    - agent/takeover.py
    - agent/main.py

key-decisions:
  - "procesar_comando_vendedor: only # prefix messages trigger command parsing — all other vendor messages silently dropped (vendor may chat on same number)"
  - "VENDEDOR_PHONE_NORM computed at module load — avoids per-request env lookup and normalizes once"
  - "Vendor routing uses continue unconditionally — vendor phone NEVER reaches client message pipeline or DB history"
  - "timeout_loop wraps check_and_apply_timeouts in try/except for loop resilience — errors logged but loop continues"
  - "Startup call to check_and_apply_timeouts() before asyncio.create_task(timeout_loop()) — catches stale humano states from pre-restart period"

patterns-established:
  - "Vendor command pattern: check phone norm == VENDEDOR_PHONE_NORM, then check startswith('#'), then continue unconditionally"
  - "Phone tolerant parsing: strip +, split('@')[0], then normalizar_telefono() — handles all Whapi phone formats"
  - "Background loop pattern: asyncio.create_task(loop()) in lifespan, try/except inside while True to prevent crash on transient errors"

# Metrics
duration: 5min
completed: 2026-03-28
---

# Phase 5 Plan 03: Human Takeover — Vendor Commands + Timeout Summary

**Vendor WhatsApp commands (#bot, #bot-all, #estado) and hourly timeout loop wired end-to-end so the vendor can return conversations to bot mode and stale humano states auto-expire**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-28T16:04:00Z
- **Completed:** 2026-03-28T16:09:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `procesar_comando_vendedor()` added to takeover.py — handles #bot, #bot-all, #estado with confirmation messages back to vendor
- Vendor phone detection in webhook handler: all messages from VENDEDOR_PHONE_NORM bypass rate limit and client pipeline entirely
- `asyncio.create_task(timeout_loop())` started in lifespan + startup check clears stale humano states from before server restart

## Task Commits

Each task was committed atomically:

1. **Task 1: Vendor command functions + timeout logic in takeover.py** - `81e39fe` (feat)
2. **Task 2: Vendor phone routing in main.py + timeout task in lifespan** - `638445d` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `agent/takeover.py` - Added `procesar_comando_vendedor()`, `normalizar_telefono` import, try/except in `timeout_loop`
- `agent/main.py` - Added `asyncio` import, takeover imports, `VENDEDOR_PHONE_NORM` constant, vendor routing block, lifespan timeout init

## Decisions Made
- Only `#`-prefixed messages from vendor number are processed as commands — all other messages silently dropped via unconditional `continue`. Prevents vendor's normal WhatsApp conversations from being routed to Claude or saved to DB.
- `VENDEDOR_PHONE_NORM` computed at module load time (not per-request) — single normalization, always consistent.
- Phone parsing in `procesar_comando_vendedor` is tolerant: strips `+`, splits on `@`, then `normalizar_telefono()` — covers all Whapi/WhatsApp phone format variants.
- Startup `check_and_apply_timeouts()` call before `timeout_loop` create_task prevents Pitfall 3 (stale humano states from pre-restart period not cleared until first hourly tick).

## Deviations from Plan

None — plan executed exactly as written. `procesar_comando_vendedor` was referenced in the takeover.py module docstring from plan 05-01 but not yet implemented; added here as planned in 05-03.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required. `TAKEOVER_TIMEOUT_HOURS` env var (default: 4) controls timeout window. `VENDEDOR_WHATSAPP` was already wired in plan 05-02.

## Next Phase Readiness
- Phase 05 Human Takeover complete: all 3 plans done
  - 05-01: ConversationState DB model + HT-04 state gate
  - 05-02: solicitar_humano tool + vendor notification
  - 05-03: vendor commands + timeout loop
- Ready for Phase 06

---
*Phase: 05-human-takeover*
*Completed: 2026-03-28*
