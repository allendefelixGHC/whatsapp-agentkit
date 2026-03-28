---
phase: 05-human-takeover
plan: 02
subsystem: human-takeover
tags: [tools, brain, prompts, takeover, vendor-notification]
dependency_graph:
  requires: ["05-01"]
  provides: ["HT-02", "HT-03"]
  affects: ["agent/tools.py", "agent/brain.py", "config/prompts.yaml"]
tech_stack:
  added: []
  patterns:
    - "Idempotency guard via obtener_estado before set_estado"
    - "VENDEDOR_WHATSAPP env var opt-in (silent no-op if unset)"
    - "solicitar_humano wired in brain.py dispatcher same pattern as reiniciar_conversacion"
    - "System prompt takeover section placed after restart section, before Horario (thematic grouping)"
key_files:
  created: []
  modified:
    - agent/tools.py
    - agent/brain.py
    - config/prompts.yaml
decisions:
  - "[Phase 05-02]: solicitar_humano idempotent — if estado==humano already, returns early without re-notifying vendor (HT-02 pitfall guard)"
  - "[Phase 05-02]: VENDEDOR_WHATSAPP opt-in — warning if unset, not error; tool still changes state even if WhatsApp notification is skipped"
  - "[Phase 05-02]: TOOLS_DEFINITION description lists explicit trigger phrases AND non-trigger guidance, same pattern as reiniciar_conversacion"
metrics:
  duration: "3 minutes"
  completed: "2026-03-28T16:05:00Z"
  tasks_completed: 2
  files_modified: 3
---

# Phase 05 Plan 02: solicitar_humano Tool — Human Takeover Flow Summary

**One-liner:** `solicitar_humano` tool pauses the bot and sends a vendor WhatsApp notification with full context summary when a client explicitly requests a human.

## What Was Built

### Task 1: solicitar_humano tool function + TOOLS_DEFINITION entry (agent/tools.py)

Added `async def solicitar_humano(telefono, resumen)` after `reiniciar_conversacion`. The function:

1. Checks idempotency: if `obtener_estado(telefono) == "humano"`, returns early without re-notifying the vendor.
2. Calls `set_estado(telefono, "humano")` to pause the bot for this conversation.
3. Reads `VENDEDOR_WHATSAPP` env var. If set, builds the notification message via `construir_mensaje_vendedor` and sends it via the configured WhatsApp provider.
4. Logs a warning (not an error) if `VENDEDOR_WHATSAPP` is not configured.

Added TOOLS_DEFINITION entry with:
- Explicit trigger phrases: "quiero hablar con alguien", "me pasas con una persona", "hablar con un asesor", etc.
- Explicit non-trigger guidance: do NOT call when client only has questions/doubts Claude can answer.
- Both `telefono` and `resumen` as required parameters, with clear descriptions.

### Task 2: brain.py dispatcher + prompts.yaml takeover block

**agent/brain.py:**
- Added `solicitar_humano` to the import from `agent.tools`
- Added `elif nombre == "solicitar_humano": return await solicitar_humano(**parametros)` after the `reiniciar_conversacion` branch in `_ejecutar_herramienta`

**config/prompts.yaml:**
- Added `## Takeover — cuando el cliente pide hablar con un humano (HT-02)` section
- Placed after `## Reinicio de conversacion` and before `## Horario` (thematic grouping)
- Includes: trigger phrase examples, step-by-step instructions (call solicitar_humano + respond to client), IMPORTANTE warning about not continuing after takeover, and non-trigger guard

## Verification Results

All success criteria passed:
- `python -c "from agent.tools import solicitar_humano; print('tool OK')"` — PASS
- `python -c "from agent.brain import _ejecutar_herramienta; print('brain OK')"` — PASS
- `grep "solicitar_humano" agent/brain.py` — finds import (line 29) + dispatcher (lines 198-199)
- `grep "solicitar_humano" agent/tools.py` — finds function (line 744) + TOOLS_DEFINITION (line 920)
- `grep "solicitar_humano" config/prompts.yaml` — finds takeover section (lines 164, 170, 173)

## Commits

| Task | Commit | Files |
|------|--------|-------|
| Task 1: solicitar_humano tool + TOOLS_DEFINITION | 410bc8c | agent/tools.py |
| Task 2: brain dispatcher + prompts takeover block | a60dc53 | agent/brain.py, config/prompts.yaml |

## Deviations from Plan

None — plan executed exactly as written.

## Must-Haves Status

- HT-02: When client asks to speak with a person, bot pauses and notifies vendor — DONE (solicitar_humano sets estado=humano + sends WhatsApp)
- HT-03: Vendor receives WhatsApp with full context: name, what they want, properties seen, budget — DONE (resumen parameter + construir_mensaje_vendedor)
- solicitar_humano idempotent — no duplicate notification if already in humano state — DONE (idempotency guard at function start)
