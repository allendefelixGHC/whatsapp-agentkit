---
phase: 06-follow-up-notifications
plan: "03"
subsystem: follow-up-scheduling
tags: [followup, automation, db-backed, n8n, whatsapp]
dependency_graph:
  requires: ["06-01", "06-02", "memory.FollowUpSchedule"]
  provides: ["FU-01 automated follow-up", "/admin/process-followups endpoint"]
  affects: ["agent/tools.py buscar_propiedades", "agent/tools.py registrar_lead_ghl", "agent/tools.py solicitar_humano", "agent/main.py"]
tech_stack:
  added: []
  patterns: ["upsert via SQLAlchemy async", "lazy import to avoid circular deps", "per-item try/except in batch processor"]
key_files:
  created:
    - agent/followup.py
  modified:
    - agent/tools.py
    - agent/main.py
decisions:
  - "[06-03]: Upsert pattern in programar_followup — same phone, multiple searches = one follow-up, rescheduled each time"
  - "[06-03]: cancelar_followup is idempotent — safe to call from registrar_lead_ghl and solicitar_humano without prior check"
  - "[06-03]: procesar_followups_pendientes uses per-item try/except — one WhatsApp failure does not block the batch"
  - "[06-03]: humano state checked at processing time (not scheduling time) — vendor may close takeover before follow-up fires"
  - "[06-03]: Separate session per commit in procesar_followups_pendientes — avoids session reuse across async boundary"
metrics:
  duration: "2 minutes"
  completed: "2026-03-28"
  tasks_completed: 2
  files_modified: 3
---

# Phase 6 Plan 3: Automated Follow-Up Scheduling Summary

DB-backed follow-up system that sends a WhatsApp re-engagement message ~24h after a client views properties but does not book; cancelled automatically on lead registration or human handoff; processed hourly via n8n calling `/admin/process-followups`.

## What Was Built

### agent/followup.py (new)

Three async functions implementing the full follow-up lifecycle:

**`programar_followup(telefono, propiedades)`** — Upsert pattern: if a `pending` record exists for this phone, reschedules it (updates `scheduled_at` and `propiedades_json`). If not, inserts a new record. Delay configurable via `FOLLOWUP_DELAY_HOURS` env var (default 24h). Stores up to 5 properties (direccion + link) as JSON context.

**`cancelar_followup(telefono)`** — Finds all `pending` records for the phone and sets them to `cancelled`. Idempotent — no-op if none found.

**`procesar_followups_pendientes()`** — Queries all `pending` rows with `scheduled_at <= now`. For each: checks conversation state (skips if `humano`), sends `FOLLOWUP_MESSAGE` via WhatsApp provider, marks as `sent`. Returns stats dict `{processed, sent, skipped_humano}`. Per-item try/except prevents one failure from blocking others.

### agent/tools.py (modified)

- `buscar_propiedades`: after saving to session cache, calls `programar_followup` with the current page of results. Only fires when `telefono and pagina_actual` are both truthy.
- `registrar_lead_ghl`: after vendor notification block, calls `cancelar_followup`. Wrapped in try/except for graceful degradation.
- `solicitar_humano`: after vendor WhatsApp notification, calls `cancelar_followup`. Same pattern.

### agent/main.py (modified)

Added `POST /admin/process-followups` endpoint after `/admin/refresh-properties`. Same admin auth pattern (`X-Admin-Token` header, only enforced when `ADMIN_TOKEN` is set). Calls `procesar_followups_pendientes()` and returns `{status: ok, stats: {...}}`.

## Must-Haves Verification

| Truth | Status |
|-------|--------|
| Client who searched but didn't book receives follow-up 24h later | Done — `buscar_propiedades` schedules, `procesar_followups_pendientes` sends |
| When `buscar_propiedades` runs, pending follow-up is scheduled (upsert) | Done — single pending per phone, rescheduled on repeat searches |
| When `registrar_lead_ghl` or `solicitar_humano` runs, pending follow-up is cancelled | Done — both functions call `cancelar_followup` |
| `POST /admin/process-followups` processes due follow-ups and sends WhatsApp | Done — endpoint added with admin auth |
| Follow-ups NOT sent to phones in 'humano' state | Done — state checked in `procesar_followups_pendientes` |
| Follow-up scheduling survives server restarts (DB-backed) | Done — stored in `FollowUpSchedule` table (SQLite/PostgreSQL) |

## Deviations from Plan

None — plan executed exactly as written.

## n8n Setup Note (Manual Step)

Create a new n8n workflow:
1. **Schedule Trigger**: every hour (same as property refresh)
2. **HTTP Request**: POST `{AGENTKIT_SERVER_URL}/admin/process-followups`
   - Header: `X-Admin-Token: {AGENTKIT_ADMIN_TOKEN}`
3. Same pattern as existing property refresh workflow

## Self-Check: PASSED

Files verified:
- `agent/followup.py` — exists, 3 async functions, imports OK
- `agent/tools.py` — `programar_followup` at line 299, `cancelar_followup` at lines 683 and 821
- `agent/main.py` — `/admin/process-followups` endpoint at line 143

Commits verified:
- `e4c8861` — feat(06-03): add agent/followup.py
- `fd57ac5` — feat(06-03): wire follow-up trigger/cancellation + /admin/process-followups
