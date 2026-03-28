---
phase: 04-business-flows
plan: 02
subsystem: api
tags: [tool-use, conversation-reset, session-cache, prompts]

# Dependency graph
requires:
  - phase: 04-01
    provides: Tasación/Venta/Alquiler captación flows wired end-to-end
provides:
  - reiniciar_conversacion tool function that clears DB history + session property cache
  - TOOLS_DEFINITION updated to 6 entries with full-reset vs soft-restart distinction
  - brain.py dispatcher wired for reiniciar_conversacion
  - prompts.yaml restart section with trigger phrase list and NO-reiniciar guidance
affects: [any future phase touching conversation state, session cache, or tool dispatcher]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Inline import from agent.memory (limpiar_historial) inside tool function to avoid circular deps — matches existing pattern in registrar_lead_ghl"
    - "Session cache cleared via direct dict delete on _cache[telefono] key — same module reference imported in tool"

key-files:
  created: []
  modified:
    - agent/tools.py
    - agent/brain.py
    - config/prompts.yaml

key-decisions:
  - "reiniciar_conversacion clears BOTH DB history and session property cache — prevents stale visita lists appearing after restart"
  - "TOOLS_DEFINITION description explicitly lists trigger phrases AND non-trigger phrases to minimize false positives"
  - "Restart flow section placed BEFORE Horario section in prompts.yaml — ordering maintains thematic grouping of flow instructions"

patterns-established:
  - "Dual-cache clearing pattern: any tool that resets conversation state must clear both agent.memory (DB) and agent.session (_cache)"

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 4 Plan 2: Flow Restart Tool Summary

**reiniciar_conversacion tool wired end-to-end: clears DB history + session cache, with prompts.yaml distinguishing full-reset from soft-restart phrases**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-28T19:16:13Z
- **Completed:** 2026-03-28T19:20:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- New `reiniciar_conversacion(telefono)` async function in tools.py that clears both SQLite conversation history and in-memory session property cache
- TOOLS_DEFINITION now has 6 entries; reiniciar_conversacion entry includes explicit list of trigger phrases and non-trigger phrases
- brain.py `_ejecutar_herramienta` dispatches `reiniciar_conversacion` calls via new elif branch
- prompts.yaml restart section guides Claude on when to call the tool (full-reset) vs when NOT to (soft re-qualification like "quiero buscar otra cosa")

## Task Commits

Each task was committed atomically:

1. **Task 1: Add reiniciar_conversacion tool function and TOOLS_DEFINITION entry** - `fe91c94` (feat)
2. **Task 2: Wire reiniciar_conversacion in brain.py dispatcher and add restart flow to prompts.yaml** - `801c6dc` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `agent/tools.py` - Added reiniciar_conversacion function and 6th TOOLS_DEFINITION entry
- `agent/brain.py` - Added reiniciar_conversacion to imports and elif branch in _ejecutar_herramienta
- `config/prompts.yaml` - Added "Reinicio de conversación" section before "## Horario"

## Decisions Made
- reiniciar_conversacion clears BOTH DB history and session property cache — prevents stale visita lists appearing after restart
- TOOLS_DEFINITION description explicitly lists trigger phrases AND non-trigger phrases to minimize false positives
- Restart flow section placed BEFORE Horario section in prompts.yaml — ordering maintains thematic grouping of flow instructions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 04 (Business Flows) is now complete — both plans done
- Phase 05 can begin: all business flows (search, captación, restart) are wired end-to-end
- No blockers

## Self-Check: PASSED

- agent/tools.py — FOUND
- agent/brain.py — FOUND
- config/prompts.yaml — FOUND
- .planning/phases/04-business-flows/04-02-SUMMARY.md — FOUND
- Commit fe91c94 — FOUND
- Commit 801c6dc — FOUND

---
*Phase: 04-business-flows*
*Completed: 2026-03-28*
