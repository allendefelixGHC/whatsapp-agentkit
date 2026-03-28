---
phase: 04-business-flows
plan: 01
subsystem: ai-prompt
tags: [prompts.yaml, registrar_lead_ghl, system-prompt, captacion, tasacion]

# Dependency graph
requires:
  - phase: 03-audio-smart-media
    provides: Completed system prompt foundation; registrar_lead_ghl fully operational with operacion param
provides:
  - Three guided conversation flows in prompts.yaml for tasación, venta captación, and alquiler captación
  - Claude now knows what to do when op_tasacion, op_vender, or op_poner_alquiler are selected from the qualification list
affects: [04-02, human-takeover, ghl-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Guided multi-step flow via system prompt: Claude tracks flow state via conversation history (last 16 msgs) — no Python state machine needed"
    - "Minimum viable registration: collect dirección + tipo as gate, treat m²/antigüedad as optional in resumen"
    - "Nombre default: check history first, fall back to 'Cliente WhatsApp' — never ask for name in captación flows"

key-files:
  created: []
  modified:
    - config/prompts.yaml

key-decisions:
  - "Register after dirección + tipo minimum (not all 4 fields) to reduce drop-off — m² and antigüedad are optional in resumen"
  - "nombre defaults to 'Cliente WhatsApp' in captación flows — NEVER ask for name (phone from context is sufficient for follow-up)"
  - "email NOT required in tasación/venta/alquiler flows — avoids drop-off from property owners"
  - "captacion_venta and captacion_alquiler use distinct operacion values to enable GHL triage"

patterns-established:
  - "Flow block in prompts.yaml: trigger IDs → sequential questions (UNA a la vez) → registrar_lead_ghl call → confirmation message"

# Metrics
duration: 2min
completed: 2026-03-28
---

# Phase 4 Plan 01: Business Flows — Tasación, Venta, Alquiler Summary

**Three guided captación flows added to system prompt: Claude now routes op_tasacion/op_vender/op_poner_alquiler to registrar_lead_ghl with operacion-differentiated resúmenes (tasacion, captacion_venta, captacion_alquiler)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-28T15:32:24Z
- **Completed:** 2026-03-28T15:34:24Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Added `## Flujo "Tasación"` block: dirección + tipo minimum, m²/antigüedad optional, calls `registrar_lead_ghl(operacion="tasacion")`
- Added `## Flujo "Vender mi propiedad"` block: same data pattern, calls `registrar_lead_ghl(operacion="captacion_venta")`
- Added `## Flujo "Poner en alquiler"` block: same pattern, calls `registrar_lead_ghl(operacion="captacion_alquiler")`
- All three flows correctly positioned after `## Agendar visita` and before `## Horario`
- YAML parses cleanly (`python -c "import yaml; yaml.safe_load(...)"` confirmed)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add tasación, venta, and alquiler flow blocks to system prompt** - `8600560` (feat)

**Plan metadata:** (next commit)

## Files Created/Modified
- `config/prompts.yaml` - Added 56 lines: three new guided flow blocks for property owner captación

## Decisions Made
- Register after collecting dirección + tipo minimum — m² and antigüedad added to resumen only if provided, reducing client drop-off from unknown figures
- nombre defaults to "Cliente WhatsApp" in all three flows; check history first but never ask — phone number is sufficient for advisor follow-up
- Email explicitly marked "NO requerir" in all three flow blocks to prevent Claude from asking for it
- Distinct operacion values (tasacion vs captacion_venta vs captacion_alquiler) enable GHL team to triage captación leads by type

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required. The three flows use the existing `registrar_lead_ghl` tool which is already wired to GHL.

## Next Phase Readiness
- Phase 4 Plan 01 complete — three captación flows operational
- Plan 02 (flow restart via `reiniciar_conversacion` tool) is ready to execute
- No blockers

## Self-Check: PASSED

- `config/prompts.yaml` exists and contains all three flow blocks (verified via grep)
- `8600560` commit exists (verified via task commit output)
- YAML parses without error (verified via python yaml.safe_load)

---
*Phase: 04-business-flows*
*Completed: 2026-03-28*
