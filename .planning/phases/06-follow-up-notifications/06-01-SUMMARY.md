---
phase: 06-follow-up-notifications
plan: 01
subsystem: business-hours
tags: [business-hours, after-hours, follow-up, timezone, whatsapp-gate]
dependency_graph:
  requires: []
  provides: [agent/business_hours.py, FollowUpSchedule model]
  affects: [agent/main.py, agent/memory.py]
tech_stack:
  added: [tzdata>=2024.1]
  patterns: [timezone-aware gate, lazy import for future dependency, SQLAlchemy model lifecycle]
key_files:
  created:
    - agent/business_hours.py
  modified:
    - agent/memory.py
    - agent/main.py
    - requirements.txt
decisions:
  - "[06-01] america/argentina/cordoba timezone (UTC-3, no DST) used via zoneinfo — no pytz needed"
  - "[06-01] lazy import of programar_followup with ImportError catch — followup.py created in plan 06-03, gate works gracefully without it"
  - "[06-01] BUSINESS_HOURS_ENABLED=false bypasses gate entirely — designed for testing outside business hours"
  - "[06-01] after-hours gate fires AFTER vendor routing and rate limiting, BEFORE human takeover gate"
metrics:
  duration: 2 min
  completed: 2026-03-28
  tasks_completed: 2
  files_modified: 4
---

# Phase 06 Plan 01: Business Hours Gate Summary

Business hours detection and after-hours auto-response gate for Bertero Inmobiliaria, registering out-of-hours contacts for next-day follow-up.

## What Was Built

### Task 1 — business_hours.py + FollowUpSchedule model + tzdata (commit: 7373694)

Created `agent/business_hours.py` with timezone-aware business hours detection for Bertero Cordoba:
- `TZ_BERTERO = ZoneInfo("America/Argentina/Cordoba")` — UTC-3, no DST
- `HORARIOS` dict: Mon-Fri (9, 18), Sat (10, 14), Sun None (closed)
- `esta_en_horario() -> bool` — checks current local time against schedule
- `AFTER_HOURS_MESSAGE` — auto-response with real Bertero schedule and website link

Added `FollowUpSchedule` SQLAlchemy model to `agent/memory.py`:
- `__tablename__ = "follow_up_schedules"`
- Fields: id, telefono (indexed), status (pending/sent/cancelled), propiedades_json, scheduled_at, created_at, updated_at
- Created automatically by `inicializar_db()` via `Base.metadata.create_all`

Added `tzdata>=2024.1` to `requirements.txt` for Windows compatibility with `zoneinfo`.

### Task 2 — After-hours gate in main.py (commit: d0580bc)

Integrated after-hours gate into `webhook_handler`:
- Import: `from agent.business_hours import esta_en_horario, AFTER_HOURS_MESSAGE`
- Env var: `BUSINESS_HOURS_ENABLED` (default `true`, set to `false` to disable for testing)
- Gate condition: `if BUSINESS_HOURS_ENABLED and not esta_en_horario()`
- On trigger: lazy-imports `programar_followup` from `agent.followup` (plan 06-03), sends `AFTER_HOURS_MESSAGE`, skips Claude entirely

Gate ordering in `webhook_handler`:
1. Vendor routing (`continue` at ~line 184) — vendor never reaches gate
2. Rate limiting (`continue` at ~line 195) — rate-limited users handled first
3. **After-hours gate** (`continue` at ~line 217) — auto-respond + schedule follow-up
4. Human takeover gate (`obtener_estado` at ~line 219)

## Verification Results

All verification checks passed:

```
python -c "from agent.business_hours import esta_en_horario, AFTER_HOURS_MESSAGE; print('hours OK:', esta_en_horario()); print('msg OK:', len(AFTER_HOURS_MESSAGE) > 50)"
hours OK: False
msg OK: True

python -c "from agent.memory import FollowUpSchedule; print('model OK:', FollowUpSchedule.__tablename__)"
model OK: follow_up_schedules

grep tzdata requirements.txt
tzdata>=2024.1

python -c "from agent.main import app, BUSINESS_HOURS_ENABLED; print('gate loaded, enabled:', BUSINESS_HOURS_ENABLED)"
gate loaded, enabled: True
```

## Deviations from Plan

None — plan executed exactly as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 7373694 | feat(06-01): business hours module + FollowUpSchedule model + tzdata |
| 2 | d0580bc | feat(06-01): after-hours gate in webhook_handler with follow-up scheduling |

## Self-Check: PASSED

All files verified present:
- FOUND: agent/business_hours.py
- FOUND: agent/memory.py
- FOUND: agent/main.py

All commits verified:
- FOUND: 7373694
- FOUND: d0580bc
