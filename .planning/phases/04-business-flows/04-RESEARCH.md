# Phase 4: Business Flows - Research

**Researched:** 2026-03-28
**Domain:** Conversational flow design, system prompt engineering, GHL lead registration
**Confidence:** HIGH (all findings based on direct codebase analysis — no external API unknowns)

---

## Summary

Phase 4 adds three new outbound business flows to the bot (tasación, vender, poner en alquiler) plus a universal flow-restart mechanism. Unlike Phases 1-3 which required new Python infrastructure, Phase 4 is **almost entirely a system prompt + tool schema problem**. The existing `registrar_lead_ghl` function in `agent/tools.py` already handles contact creation and opportunity registration in GHL — it just needs to be called with the right parameters. The tools layer (`brain.py` tool loop) is fully operational. The only Python change is `memory.py` — adding a `limpiar_historial()` call to support clean flow restart.

The three new flows (BF-01, BF-02, BF-03) share the same structure: Claude asks sequential guided questions, collects property data from the client, then calls `registrar_lead_ghl` with a descriptive `resumen` that identifies this as a captación (tasación), lead vendedor, or lead alquiler. The `resumen` field is what the GHL team will use to triage and route — it must be explicit.

The flow restart (BF-04) has two layers: (1) when the client says "empezar de nuevo" or similar, Claude must call `limpiar_historial` — but `limpiar_historial` is currently not exposed as a Claude tool. A new lightweight tool `reiniciar_conversacion(telefono)` must be added to `TOOLS_DEFINITION` in `tools.py` and exposed to Claude via `brain.py`. Without this tool, Claude can only verbally acknowledge the restart but the conversation memory persists, causing context bleed.

**Primary recommendation:** Add one new tool (`reiniciar_conversacion`), extend `prompts.yaml` system prompt with three flow blocks, and update `TOOLS_DEFINITION` in `tools.py`. No new Python packages, no schema changes, no n8n work.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `anthropic` | already installed | Claude tool_use loop drives the conversation flows | Already orchestrates all multi-turn flows in `brain.py` |
| `sqlalchemy` | already installed | `limpiar_historial()` for DB cleanup on restart | Already in `memory.py`; just need to expose it as a tool |
| `httpx` | already installed | GHL API calls inside `registrar_lead_ghl` | Already handles all GHL HTTP in `tools.py` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `yaml` (stdlib) | Python 3.11 | Read `config/prompts.yaml` with new flow blocks | Already used in `brain.py` for system prompt loading |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| System prompt flow instructions | Finite-state machine in Python | Code FSM is more predictable but adds ~200 lines of state management; for 3 simple flows, prompt engineering is sufficient and matches the existing bot's approach |
| Exposing `limpiar_historial` as a tool | Clearing history in `main.py` before calling brain | Tool approach keeps Claude in control of when to clear; `main.py` approach would require regex to detect restart intent before calling Claude, which is fragile |

**Installation:** No new dependencies required.

---

## Architecture Patterns

### Recommended Project Structure

No new files required. Changes are additive to existing files:

```
config/
└── prompts.yaml          ← Add 3 new flow blocks + flow-restart section

agent/
├── tools.py              ← Add reiniciar_conversacion() + TOOLS_DEFINITION entry
└── brain.py              ← Add reiniciar_conversacion to _ejecutar_herramienta()
```

### Pattern 1: Guided Multi-Step Flow via System Prompt

**What:** A flow block in `prompts.yaml` instructs Claude to ask specific questions one at a time, accumulate answers across turns, then call a tool when all data is collected.

**When to use:** When a business process requires 3-5 sequential data points from the client (address, type, size, age for tasación).

**How it works with the existing stack:**
- Claude receives user message + full conversation history (last 16 messages)
- System prompt contains the flow definition (step sequence, what to ask, what tool to call at the end)
- Claude tracks its progress through the flow using the conversation history — no separate state object needed
- When complete, Claude calls `registrar_lead_ghl` with accumulated data in `resumen`

**Key insight from existing code:** `main.py` already injects `[CONTEXTO INTERNO]` metadata into every message, including `lista_id` and `boton_id` when the client interacts with interactive elements. This same mechanism makes Claude aware of which flow it's in.

**Example structure for prompts.yaml flow block:**

```yaml
## Flujo "Tasación" (op_tasacion / "quiero tasar" / "tasar mi propiedad")
Cuando el cliente elige tasación o pide tasar su propiedad:
1. Explicar brevemente: "Hacemos tasaciones de mercado para que sepas cuánto vale tu propiedad."
2. Pedir DIRECCIÓN de la propiedad
3. Pedir TIPO (casa, departamento, terreno, local, galpón, oficina)
4. Pedir SUPERFICIE (m² cubiertos)
5. Pedir ANTIGÜEDAD (años aproximados)
6. Llamar a registrar_lead_ghl con:
   - resumen: "TASACIÓN: [tipo] en [dirección] — [m²] m², [antigüedad] años"
   - operacion: "tasacion"
7. Confirmar: "¡Listo! Ya registré tu solicitud de tasación. Un asesor de Bertero te va a contactar para coordinar la visita y preparar la tasación. ¿Hay algo más en lo que pueda ayudarte?"
```

### Pattern 2: Flow Restart Tool

**What:** A Claude tool `reiniciar_conversacion(telefono)` that calls `limpiar_historial()` from `memory.py`.

**When to use:** When client says "empezar de nuevo", "quiero buscar otra cosa", "cambiar mi búsqueda", or similar intent.

**Implementation:**

```python
# In agent/tools.py

async def reiniciar_conversacion(telefono: str) -> str:
    """
    Borra el historial de conversación para que el cliente empiece desde cero.
    Se llama cuando el cliente dice 'empezar de nuevo', 'quiero buscar otra cosa', etc.
    """
    from agent.memory import limpiar_historial
    await limpiar_historial(telefono)
    logger.info(f"Historial limpiado para {telefono}")
    return "Historial limpiado. El cliente puede empezar de nuevo."
```

```python
# TOOLS_DEFINITION entry to add in agent/tools.py:
{
    "name": "reiniciar_conversacion",
    "description": "Borra el historial de conversación completo para reiniciar el flujo de calificación desde cero. Llamar cuando el cliente diga 'empezar de nuevo', 'quiero buscar otra cosa', 'cambiar mi búsqueda', 'me equivoqué', o cualquier intención de reinicio.",
    "input_schema": {
        "type": "object",
        "properties": {
            "telefono": {
                "type": "string",
                "description": "Teléfono del cliente (viene del contexto interno del mensaje)"
            }
        },
        "required": ["telefono"]
    }
}
```

```python
# In agent/brain.py, _ejecutar_herramienta():
elif nombre == "reiniciar_conversacion":
    return await reiniciar_conversacion(**parametros)
```

**Critical note:** After `limpiar_historial` runs, the *current* response will be based on an empty history BUT the current message is still in context. Claude must immediately launch the qualification list (step 1 of the flow) as if it were a new client. The system prompt must say: "After calling reiniciar_conversacion, send the welcome list immediately — DO NOT ask again what the client wants, just send the qualification list."

### Pattern 3: Distinguishing Tasación/Venta/Alquiler from List IDs

**What:** The existing qualification list (step 1) already has `op_tasacion`, `op_vender`, `op_poner_alquiler` as list IDs. The new flow blocks in `prompts.yaml` react to those IDs.

**Current list IDs in prompts.yaml (step 1):**
- `op_comprar` → existing buyer flow
- `op_alquilar` → existing renter flow
- `op_vender` → **NEW: Phase 4 vendor flow**
- `op_poner_alquiler` → **NEW: Phase 4 rental landlord flow**
- `op_tasacion` → **NEW: Phase 4 tasación flow**
- `op_info` → general info

**Implication:** The list IDs are already defined in the system prompt and will appear in `[El cliente seleccionó de una lista interactiva. ID seleccionado: op_tasacion]` in the context injected by `main.py`. Claude just needs flow instructions for those IDs.

### Anti-Patterns to Avoid

- **Asking for email during tasación/venta/alquiler:** For these flows, email should be optional (not required) since the client is giving us the property — not booking a visit. Force-requiring email causes drop-off. Only nombre + teléfono (already known from context) is strictly needed to call `registrar_lead_ghl`.
- **Hardcoding tasación step count in code:** Keep the step logic in prompts.yaml, not in Python. Changing a step from 4 to 5 should not require a code deploy.
- **Separate GHL pipelines per flow type:** All three new flows (tasación, venda, alquiler landlord) should go into the SAME GHL pipeline as existing leads, differentiated by the `resumen` field and `operacion` parameter. `registrar_lead_ghl` already accepts `operacion` parameter.
- **Clearing session cache on restart:** `limpiar_historial` only clears `agent/memory.py` (SQLite). The `agent/session.py` property cache (for visit lists) should also be cleared via `limpiar_cache_expirado()` or explicit delete — otherwise stale property lists persist for `obtener_propiedades_para_visita`. Add a `limpiar_propiedades(telefono)` to session.py if not already present.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Collecting multi-turn form data | Stateful FSM in Python with `conversation_state` table | System prompt flow block + Claude memory (last 16 msgs) | Existing pattern already works for qualification; same approach works for tasación/venta flows |
| GHL lead registration | New HTTP client for tasación leads | Existing `registrar_lead_ghl()` with `operacion="tasacion"` | Already handles contact upsert, opportunity creation, booking link, error fallback |
| Detecting restart intent | Intent classifier | System prompt instruction + `reiniciar_conversacion` tool | Claude already handles fuzzy intent detection; no need for separate classifier |
| Resetting session state | New DB table | `limpiar_historial()` (memory.py) + clearing session.py cache | Both already exist, just need wiring |

**Key insight:** All the machinery exists. This phase is about configuring the existing machinery, not building new infrastructure.

---

## Common Pitfalls

### Pitfall 1: Teléfono Not in Tool Call Parameters

**What goes wrong:** Claude calls `reiniciar_conversacion()` without passing `telefono`, causing a Python TypeError.

**Why it happens:** The phone number lives in the `[CONTEXTO INTERNO]` section of the message injected by `main.py`, not as a visible conversation message. Claude sometimes fails to extract it when generating tool calls.

**How to avoid:** In the tool description, explicitly state: "El teléfono del cliente siempre está disponible en el contexto interno del mensaje que dice '[CONTEXTO INTERNO - NO MOSTRAR AL CLIENTE: teléfono del cliente es XXXXXXXX]'. Extraer ese número y pasarlo aquí."

**Warning signs:** If `reiniciar_conversacion` is called with empty string telefono, add validation that logs a warning and uses a fallback.

### Pitfall 2: Flow Context Bleed After Restart

**What goes wrong:** Client says "empezar de nuevo" mid-flow. `limpiar_historial` clears DB history. But `guardar_mensaje` in `main.py` saves the current exchange *after* the brain call — so the restart message itself becomes the new first message in history.

**Why it happens:** The sequence in `main.py` is: `obtener_historial` → `generar_respuesta` → `guardar_mensaje`. The restart message is saved after the response, so the next turn has one message in history: the restart request + Claude's "starting fresh" reply.

**How to avoid:** This is actually fine — the next turn will have a tiny history that starts fresh. No code change needed. Just document it and ensure the system prompt handles "I see only 1 message in history after a restart, treat as new client" correctly.

### Pitfall 3: registrar_lead_ghl Called Without Email for Tasación

**What goes wrong:** `registrar_lead_ghl` function in `tools.py` does not require `email` (it's an optional parameter). But GHL contact creation works without email — it will use the phone number as the primary identifier. This is fine.

**Why it happens:** Tasación clients are property owners, not buyers — asking for email feels intrusive at this stage.

**How to avoid:** Confirm that `crear_o_actualizar_contacto` in `ghl.py` handles missing email gracefully. Reading the code: `email` is passed as-is to GHL API. GHL accepts contacts without email when phone is present. Confirmed safe.

### Pitfall 4: op_vender vs op_poner_alquiler Confusingly Similar

**What goes wrong:** "Vender mi propiedad" and "poner en alquiler" feel similar to clients and similar to Claude. Claude might mix the flows.

**Why it happens:** Both flows collect property data; the difference is the end goal (sale vs rental management).

**How to avoid:** Make the flow blocks in `prompts.yaml` very explicit about the `operacion` value to pass to `registrar_lead_ghl`: `operacion="captacion_venta"` vs `operacion="captacion_alquiler"`. Also include a one-line description in each flow block clarifying the distinction.

### Pitfall 5: Restart Triggers False Positives

**What goes wrong:** A client says "quiero buscar otra cosa" but means "search for a different property type" — not "wipe my history". Claude calls `reiniciar_conversacion` and the client's context is lost.

**Why it happens:** Restart detection relies on Claude's interpretation of intent.

**How to avoid:** In the system prompt restart section, list specific trigger phrases: "empezar de nuevo", "empezar desde cero", "olvidate de todo", "me equivoqué, quiero cambiar todo". For "buscar otra cosa" or "ver algo diferente" → do NOT call `reiniciar_conversacion`, instead restart the qualification list (step 1 of flow) WITHOUT clearing history. Only call the tool for explicit full-reset requests.

---

## Code Examples

### Tool Definition to Add in tools.py

```python
# Source: analysis of existing TOOLS_DEFINITION pattern in agent/tools.py

async def reiniciar_conversacion(telefono: str) -> str:
    """
    Borra el historial de conversación para reinicio limpio.
    """
    from agent.memory import limpiar_historial
    await limpiar_historial(telefono)
    # También limpiar el cache de propiedades de sesión
    from agent.session import _cache
    if telefono in _cache:
        del _cache[telefono]
    logger.info(f"Conversación reiniciada para {telefono}")
    return "Historial limpiado exitosamente. El cliente puede empezar desde cero."


# Add to TOOLS_DEFINITION list:
{
    "name": "reiniciar_conversacion",
    "description": (
        "Borra el historial de conversación completo para reiniciar el flujo de calificación "
        "desde cero. Llamar SOLO cuando el cliente pida explícitamente empezar de nuevo o "
        "cambiar todo (ej: 'empezar de nuevo', 'olvidate de todo', 'me equivoqué quiero cambiar'). "
        "NO llamar para 'quiero ver otra cosa' o 'buscar diferente'. "
        "El teléfono del cliente está en el contexto interno: "
        "'[CONTEXTO INTERNO - NO MOSTRAR AL CLIENTE: teléfono del cliente es XXXXXXXX]'. "
        "Extraer ese número y pasarlo aquí."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "telefono": {
                "type": "string",
                "description": "Teléfono del cliente del contexto interno (ej: 5493517575244@s.whatsapp.net)"
            }
        },
        "required": ["telefono"]
    }
}
```

### System Prompt Block for Tasación (prompts.yaml)

```yaml
## Flujo "Tasación" (se activa con: op_tasacion, "quiero tasar", "tasar mi propiedad", "saber cuánto vale", "valuar")
Cuando el cliente quiere tasar su propiedad:
1. Explicar brevemente: "¡Con gusto! Realizamos tasaciones de mercado para que sepas cuánto vale tu propiedad con precisión. Necesito algunos datos para que nuestros asesores puedan preparar la valuación."
2. Pedir DIRECCIÓN de la propiedad (calle y altura o barrio de referencia)
3. Pedir TIPO de propiedad (casa, departamento, terreno, local, galpón, oficina)
4. Pedir SUPERFICIE cubierta aproximada en m²
5. Pedir ANTIGÜEDAD aproximada en años (o "a estrenar")
6. Llamar a registrar_lead_ghl con:
   - telefono: del contexto
   - nombre: si ya lo tenés del historial, sino omitir (campo opcional)
   - operacion: "tasacion"
   - tipo_propiedad: el tipo recopilado
   - zona: extraído de la dirección
   - resumen: "TASACIÓN SOLICITADA: [tipo] en [dirección completa] — aprox [m²] m², [antigüedad] años"
7. Confirmar: "¡Listo! Ya tomé nota de tu solicitud de tasación 😊 Un asesor de Bertero se va a comunicar con vos para coordinar la visita y preparar la tasación formal. ¿Hay algo más en lo que pueda ayudarte?"
UNA pregunta a la vez. Si el cliente da varios datos en un mensaje, tomarlos todos y saltear los pasos ya respondidos.
```

### System Prompt Block for Venta (prompts.yaml)

```yaml
## Flujo "Vender mi propiedad" (se activa con: op_vender, "quiero vender", "poner en venta", "vender mi casa/depto")
Cuando el cliente quiere vender su propiedad:
1. Mostrar texto: "¡Genial! Bertero te acompaña en todo el proceso de venta: tasación, publicación, visitas y cierre de operación."
2. Pedir DIRECCIÓN de la propiedad
3. Pedir TIPO de propiedad
4. Pedir SUPERFICIE cubierta aproximada en m²
5. (Opcional) Preguntar si ya tiene precio en mente o si necesita tasación primero
6. Llamar a registrar_lead_ghl con:
   - operacion: "captacion_venta"
   - tipo_propiedad: el tipo recopilado
   - zona: de la dirección
   - resumen: "VENTA: cliente quiere poner en venta [tipo] en [dirección] — aprox [m²] m²[, precio estimado: X si lo dio]"
7. Confirmar: "¡Perfecto! Ya registré tu consulta de venta. Un asesor de Bertero te va a contactar para coordinar una visita a la propiedad y preparar la estrategia de venta. ¿Hay algo más?"
```

### System Prompt Block for Alquiler Landlord (prompts.yaml)

```yaml
## Flujo "Poner en alquiler" (se activa con: op_poner_alquiler, "poner en alquiler", "alquilar mi propiedad", "administrar mi propiedad")
Cuando el cliente quiere poner su propiedad en alquiler:
1. Mostrar texto: "¡Claro! Bertero ofrece el servicio de administración de alquileres: nos encargamos de encontrar inquilinos, cobrar alquileres y gestionar todo el contrato."
2. Pedir DIRECCIÓN de la propiedad
3. Pedir TIPO de propiedad
4. Pedir SUPERFICIE cubierta aproximada en m²
5. Llamar a registrar_lead_ghl con:
   - operacion: "captacion_alquiler"
   - tipo_propiedad: el tipo recopilado
   - zona: de la dirección
   - resumen: "ALQUILER: cliente quiere poner en alquiler [tipo] en [dirección] — aprox [m²] m²"
6. Confirmar: "¡Listo! Ya registré tu consulta 😊 Un asesor de Bertero te va a contactar para explicarte el servicio de administración y coordinar los próximos pasos. ¿Hay algo más?"
```

### System Prompt Block for Restart (prompts.yaml)

```yaml
## Reinicio de conversación (BF-04)
Cuando el cliente pide explícitamente empezar de nuevo (frases exactas o similares: "empezar de nuevo", "empezar desde cero", "olvidate de todo lo anterior", "me equivoqué, quiero cambiar todo"):
1. Llamar a reiniciar_conversacion con el teléfono del contexto
2. Responder: "¡Claro! Empezamos de nuevo 😊" y enviar la lista interactiva de opciones (paso 1 del flujo de calificación)

IMPORTANTE: Para "quiero buscar otra cosa", "ver algo diferente", "cambiar el tipo de propiedad" → NO llamar a reiniciar_conversacion. En su lugar, volver al paso correspondiente del flujo de calificación y preguntar qué cambio quiere hacer.
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| No flows for tasación/venta/alquiler | Explicit flow blocks in system prompt | BF-01, BF-02, BF-03 covered |
| No restart mechanism | `reiniciar_conversacion` tool | BF-04 covered |
| `limpiar_historial` only callable from tests | Exposed as Claude tool | Clean restart without restarting server |

**Deprecated/outdated:**
- Nothing deprecated — this phase only adds to existing patterns.

---

## Open Questions

1. **¿Nombre obligatorio en tasación/venta/alquiler?**
   - What we know: `registrar_lead_ghl(nombre, ...)` — nombre is a required parameter in the function signature
   - What's unclear: Whether GHL accepts empty nombre, and whether it's better UX to not ask for name in these captación flows
   - Recommendation: Make Claude check history for an existing name first (`obtener_historial` may already have it from a prior interaction). If not found, skip asking — pass `nombre="Cliente WhatsApp"` as default. Do NOT ask for name in these flows; the phone number is sufficient for the sales team to follow up.

2. **¿Nuevo pipeline stage para captación vs comprador?**
   - What we know: Current GHL pipeline has stages: `lead_nuevo`, `contactado_bot`, `visita_agendada`, etc. The `resumen` field differentiates lead types.
   - What's unclear: Whether Bertero wants separate pipeline stages for captación leads vs buyer leads.
   - Recommendation: Keep single pipeline, differentiate by `resumen` and `operacion` field. Phase 5 (Human Takeover) is the right time to introduce pipeline stage complexity if needed.

3. **¿Cuántos pasos mínimos para tasación antes de registrar?**
   - What we know: Business requirement says "dirección, tipo, m2, antigüedad"
   - What's unclear: Whether to require all 4 before calling `registrar_lead_ghl`, or register after 2 and ask remaining as optional
   - Recommendation: Register after collecting at minimum dirección + tipo. Treat m2 and antigüedad as optional fields in the resumen — "aprox X m²" if given, otherwise omit. This reduces drop-off from clients who don't know exact figures.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis — `agent/tools.py`, `agent/brain.py`, `agent/memory.py`, `agent/session.py`, `agent/ghl.py`, `agent/main.py`, `config/prompts.yaml`
- All claims about tool signatures, DB patterns, and GHL integration are verified against live source code

### Secondary (MEDIUM confidence)
- GHL API behavior (empty email, empty nombre) — inferred from existing error handling code in `tools.py` lines 604-618 and `ghl.py` contact creation logic

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, verified against existing imports
- Architecture: HIGH — patterns mirror Phase 3 (system prompt + one new tool), verified against existing code
- Pitfalls: HIGH — identified from direct code reading of `main.py` flow and `memory.py` operations

**Research date:** 2026-03-28
**Valid until:** Stable — only invalidated by changes to `registrar_lead_ghl` signature or `memory.py` API
