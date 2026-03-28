---
phase: 03-audio-smart-media
plan: 02
subsystem: ai-prompt-engineering
tags: [prompts.yaml, claude-vision, image-processing, property-search, bertero-sign-detection]

# Dependency graph
requires:
  - phase: 02-supabase-data-foundation
    provides: buscar_propiedades tool and property catalog in Supabase

provides:
  - System prompt with proactive image-to-search behavior (no extra round-trip)
  - Bertero sign detection with immediate visit booking offer
  - Non-property image safety gate (no false searches on selfies/docs)
  - Zone-based fallback when no exact Bertero sign match found

affects: [future prompt updates, agent/brain.py image flow, testing image scenarios]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Proactive tool-call from visual context: system prompt instructs LLM to call buscar_propiedades immediately on image receipt without asking user first"
    - "Safety gate before visual tool call: assess if image is real estate related before triggering search"
    - "Two-level Bertero detection: exact match → offer visit; no match → similar zone properties + offer visit"

key-files:
  created: []
  modified:
    - config/prompts.yaml

key-decisions:
  - "System prompt engineering only — no new code or tools needed; Claude Vision already receives the image in generar_respuesta(), the fix was purely behavioral instructions"
  - "Non-property image safety gate added explicitly to avoid false buscar_propiedades calls on selfies, documents or screenshots"
  - "Bertero sign no-match fallback shows similar-zone properties rather than dead end, keeping the conversation productive"

patterns-established:
  - "Pattern: Image safety assessment before tool call — always check if image is property-related before launching search"
  - "Pattern: Immediate action from visual context — do not ask user for data Claude can extract from the image itself"

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 3 Plan 02: Smart Image Search Summary

**System prompt rewritten to make Claude proactively call `buscar_propiedades` on image receipt, with Bertero sign detection, visit-booking offer, and safety gate against non-property images**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-28T14:10:00Z
- **Completed:** 2026-03-28T14:14:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Replaced passive "Fotos de propiedades" section with assertive "Procesamiento de imagenes (CRITICO)" section that instructs Claude to analyze and search immediately
- Added "Deteccion de carteles Bertero (CRITICO)" section: exact match shows property + `enviar_botones` visit offer; no exact match shows similar-zone properties + offer visit; other-agency signs handled gracefully
- Added explicit safety gate: if image is NOT real estate related (selfie, document, screenshot), do not search — acknowledge and ask what they need

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite image processing section in system prompt for proactive search** - `33cb8db` (feat)

**Plan metadata:** `[pending final commit]` (docs: complete plan)

## Files Created/Modified

- `config/prompts.yaml` - Replaced "## Fotos de propiedades" (8 lines, passive) with "## Procesamiento de imagenes" + "## Deteccion de carteles Bertero" (40 lines, assertive with safety rules and fallbacks)

## Decisions Made

- System prompt engineering only — no new code, tools, or API calls needed. Claude Vision already receives the image via the existing `generar_respuesta()` path. The behavioral change required only updated instructions.
- Kept Argentine Spanish (vos) tone consistent with rest of prompt.
- Included MIME-type safety language ("selfie, documento, captura de pantalla") directly in the prompt to match the exact non-property scenarios from the research pitfall list.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 3 complete: both plans done (03-01 Audio Transcription, 03-02 Smart Image Search)
- Phase 4 can begin: system is now capable of processing voice notes, images, and standard text
- No blockers

---
*Phase: 03-audio-smart-media*
*Completed: 2026-03-28*
