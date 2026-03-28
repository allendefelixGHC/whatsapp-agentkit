---
phase: 01-technical-hardening
plan: 01
subsystem: core-message-processing
tags: [deduplication, phone-normalization, memory, reliability]
dependency_graph:
  requires: []
  provides: [agent/utils.py, agent/dedup.py]
  affects: [agent/main.py, agent/memory.py, agent/ghl.py]
tech_stack:
  added: [cachetools>=5.3.0]
  patterns: [TTLCache in-memory dedup, centralized normalization utility]
key_files:
  created: [agent/utils.py, agent/dedup.py]
  modified: [agent/main.py, agent/memory.py, agent/ghl.py, requirements.txt]
decisions:
  - "Canonical phone form is digits-only 13-char string (549XXXXXXXXXX) for DB keys; GHL-specific +54X format derived on demand"
  - "obtener_link_booking() left with its own URL-param cleanup — it builds query strings, not identity keys"
metrics:
  duration: "3 minutes"
  completed: "2026-03-28T12:16:xx"
  tasks_completed: 2
  files_modified: 6
---

# Phase 1 Plan 1: Message Dedup, Phone Normalization, History Expansion

**One-liner:** TTLCache dedup preventing double-responses on webhook retries, centralized `normalizar_telefono()` eliminating duplicate contact creation across phone format variants, and 6→16 message history for richer Claude context.

---

## What Was Built

### agent/utils.py (new)
Single source of truth for Argentina phone normalization. Handles all input variants (`@s.whatsapp.net`, `@c.us`, `+54`, `054`, local 10-digit) and returns canonical 13-digit `549XXXXXXXXXX` form used as the DB key.

### agent/dedup.py (new)
In-memory `TTLCache(maxsize=10_000, ttl=300)` that registers `mensaje_id` on first sight and returns `True` on subsequent calls within the 5-minute window. Empty IDs are never deduplicated (logged as warning).

### agent/memory.py (modified)
Changed `obtener_historial()` default `limite` from 6 to 16. Also corrected the stale docstring that incorrectly stated "default: 20".

### agent/main.py (modified)
- Added imports: `from agent.dedup import es_duplicado`, `from agent.utils import normalizar_telefono`
- In `webhook_handler`: dedup check runs before typing indicator and Claude API call
- Memory operations (`obtener_historial`, `guardar_mensaje`) use `telefono_normalizado` (canonical key); Whapi sends still use original `msg.telefono` (with `@s.whatsapp.net`)
- In `ghl_webhook_handler`: replaced 5-line inline phone normalization block with single `normalizar_telefono(phone) + "@s.whatsapp.net"`

### agent/ghl.py (modified)
- Added `from agent.utils import normalizar_telefono`
- `crear_o_actualizar_contacto()`: replaced inline stripping + regex with `normalizar_telefono()` call; GHL-specific `549→54` conversion retained as post-normalization step
- `buscar_contacto_por_telefono()`: normalizes phone before GHL API query

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create phone normalization utility and dedup cache | 6eff017 | agent/utils.py, agent/dedup.py, requirements.txt |
| 2 | Integrate dedup and normalization into main.py and ghl.py, expand history | 44561e1 | agent/main.py, agent/memory.py, agent/ghl.py |

---

## Verification Results

All success criteria met:

- [x] `cachetools>=5.3.0` in requirements.txt and installed
- [x] `agent/utils.py` with `normalizar_telefono()` handling all AR phone formats (5 assertions pass)
- [x] `agent/dedup.py` with `es_duplicado()` using `TTLCache(maxsize=10000, ttl=300)`
- [x] `agent/memory.py` has `limite=16` as default
- [x] `agent/main.py` calls `es_duplicado()` before processing and `normalizar_telefono()` for memory ops
- [x] `agent/ghl.py` uses `normalizar_telefono()` instead of inline logic
- [x] Server starts without import errors (tested with uvicorn on port 8111)

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing functionality] GHL phone normalization retained explicit 549→54 conversion**

- **Found during:** Task 2
- **Issue:** The plan instruction said `return "+" + normalizar_telefono(telefono)` for GHL format, but `normalizar_telefono()` returns `5493...` (with mobile `9`) while GHL needs `+543...` (without `9`). Blindly following the instruction would break GHL contact creation.
- **Fix:** After `normalizar_telefono()` call, the `549→54` stripping is kept as a GHL-specific post-processing step — clearly commented. The centralization goal is achieved (no duplicate stripping-of-`@s.whatsapp.net` logic), and correctness is preserved.
- **Files modified:** agent/ghl.py

**2. [Rule 1 - Bug] Stale docstring in memory.py**

- **Found during:** Task 2
- **Issue:** `obtener_historial()` docstring said "default: 20" when actual default was 6.
- **Fix:** Corrected docstring to "default: 16" when changing the actual default.
- **Files modified:** agent/memory.py

---

## Decisions Made

1. **Canonical phone form is `549XXXXXXXXXX` (digits only) for all DB/memory keys.** GHL-specific format (`+543...`) is derived on demand in `ghl.py` after normalization. This means one canonical form everywhere for lookups, with format conversion only at the GHL API boundary.

2. **`obtener_link_booking()` inline phone cleanup not replaced.** That function builds URL query string params — it's a presentation concern, not an identity/storage key. Replacing it with `normalizar_telefono()` would change the booking link format (would add `549` prefix where `+54` is expected). Left as-is per scope.

3. **`cachetools` TTLCache chosen over DB-backed dedup.** Webhook retries happen within seconds. In-memory TTL of 5 minutes covers all retry windows without DB writes. Acceptable trade-off: dedup state resets on server restart (documented in research as known limitation for Phase 1).

---

## Self-Check: PASSED

All created files exist on disk. Both task commits verified in git log:
- `6eff017` feat(01-01): add phone normalization utility and message dedup cache
- `44561e1` feat(01-01): integrate dedup and phone normalization, expand history to 16
