# Phase 6: Follow-up & Notifications - Research

**Researched:** 2026-03-28
**Domain:** Business hours detection, vendor WhatsApp notifications, n8n delayed follow-up scheduling
**Confidence:** HIGH (all findings based on direct codebase analysis + verified Python stdlib behavior)

---

## Summary

Phase 6 adds three distinct capabilities on top of the existing codebase: (1) business hours detection so the bot auto-responds after hours and queues the lead for next-day follow-up, (2) vendor WhatsApp notification when a lead is registered or handoff happens, and (3) automated follow-up 24-48 hours later for clients who saw properties but never booked.

The codebase already has all the primitives needed. `agent/session.py` stores which properties each client saw (`_cache` dict with phone → properties). `agent/takeover.py` has `set_estado()` and `construir_mensaje_vendedor()`. `agent/tools.py` has `registrar_lead_ghl()` which is the natural injection point for vendor notification. `main.py` already has an n8n HTTP pattern (`N8N_EMAIL_WEBHOOK`). The plan must add: a `business_hours.py` module, a new `FollowUpSchedule` SQLAlchemy table, inject vendor notification into `registrar_lead_ghl()`, and an n8n workflow for delayed follow-up firing.

The single most important architectural decision for this phase: **follow-up scheduling should be tracked in SQLite/DB (not session cache), because the 24-48h delay spans server restarts**. The session cache (`session.py`) is in-memory and resets on restart — it cannot survive the wait window. The pattern from Phase 5 (ConversationState in DB) is the model to follow.

**Primary recommendation:** Three plans — 06-01 for business hours module + after-hours bot response, 06-02 for vendor notification injection at lead registration and handoff points, 06-03 for follow-up table + n8n scheduling + follow-up execution endpoint.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `zoneinfo` (stdlib) | Python 3.9+ | Argentina/Cordoba timezone-aware datetime | Built-in, no extra dependency on Docker/Railway where tzdata is available via OS |
| `tzdata` | 2025.3 (already in pip) | IANA timezone DB for zoneinfo on Windows/minimal Docker | Required on Windows dev + slim Docker images; already installed |
| `sqlalchemy` | already installed | `FollowUpSchedule` table for 24-48h follow-up state | Same engine/session as Mensaje and ConversationState |
| `httpx` | already installed | HTTP POST to n8n webhook to trigger follow-up dispatch | Same client used in `_notificar_error_crm()` and `main.py` n8n calls |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio` | stdlib | Background task for after-hours lead batch check (if needed) | Only if polling approach chosen; n8n Schedule Trigger avoids this |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `zoneinfo` (stdlib) | `pytz` | pytz is not in requirements.txt; zoneinfo is stdlib + tzdata already present |
| n8n Schedule Trigger polling DB | asyncio background task in Python | n8n is already used as scheduler (Phase 2, `admin/refresh-properties`); consistent pattern; no extra load on FastAPI |
| New `FollowUpSchedule` DB table | Redis/external queue | Overkill; SQLite already handles ConversationState persistence; same pattern |
| Vendor notification via n8n | Direct WhatsApp via proveedor | Direct WhatsApp is already working in `solicitar_humano()` and `construir_mensaje_vendedor()`; use the same pattern, no new dependency |

**Installation:** Add `tzdata` to requirements.txt (already present in environment, just not declared).

---

## Architecture Patterns

### Recommended Project Structure

New files:
```
agent/
├── business_hours.py    ← New: timezone-aware business hours detection for Bertero
```

New DB table (in memory.py):
```
FollowUpSchedule          ← New: pending follow-ups with status + scheduled_at
```

New admin endpoint (in main.py):
```
POST /admin/process-followups  ← Called by n8n Schedule Trigger to process due follow-ups
```

Modified files:
```
agent/tools.py            ← registrar_lead_ghl() injects vendor WhatsApp notification
agent/memory.py           ← New FollowUpSchedule model
agent/main.py             ← After-hours gate before Claude call + new /admin/process-followups
.env.example              ← New vars: BUSINESS_TIMEZONE, N8N_FOLLOWUP_WEBHOOK
requirements.txt          ← Add tzdata
```

### Pattern 1: Business Hours Detection (06-01)

**What:** Check Argentina/Cordoba time before calling Claude. If outside business hours, send auto-response with schedule info and register lead for next-day follow-up. Bot does NOT call Claude API.

**When to use:** Every inbound client message before brain.py is called.

**Key logic:**
```python
# agent/business_hours.py
# Source: Python stdlib docs + verified against America/Argentina/Cordoba

from zoneinfo import ZoneInfo
from datetime import datetime

TZ_BERTERO = ZoneInfo("America/Argentina/Cordoba")

# Bertero hours: Mon-Fri 9-18, Sat 10-14, Sun closed
HORARIOS = {
    0: (9, 18),   # Lunes
    1: (9, 18),   # Martes
    2: (9, 18),   # Miércoles
    3: (9, 18),   # Jueves
    4: (9, 18),   # Viernes
    5: (10, 14),  # Sábado
    6: None,      # Domingo — cerrado
}

def esta_en_horario() -> bool:
    """True if current Cordoba time is within Bertero business hours."""
    now = datetime.now(TZ_BERTERO)
    rango = HORARIOS.get(now.weekday())
    if rango is None:
        return False
    hora_apertura, hora_cierre = rango
    return hora_apertura <= now.hour < hora_cierre

def proximo_horario_texto() -> str:
    """Returns human-readable next opening time for after-hours message."""
    now = datetime.now(TZ_BERTERO)
    # ... walk forward to find next open day/time
```

**Important:** `America/Argentina/Cordoba` is UTC-3 with NO DST. Argentina stopped observing DST in 2000. This is fixed offset year-round — confirmed via IANA tzdata.

**Gate position in main.py:** Insert AFTER vendor command routing and rate limiting, BEFORE `obtener_estado()` call. The gate fires before Claude is ever invoked. State check order:
1. Vendor command routing (unchanged)
2. Rate limiting (unchanged)
3. **Business hours gate** (NEW — after-hours response + register follow-up)
4. Human takeover gate (unchanged)
5. Claude call (unchanged)

**After-hours message format:**
```
Gracias por escribirnos! 🏠

Nuestro horario de atención es:
• Lunes a Viernes: 9:00 a 18:00 hs
• Sábados: 10:00 a 14:00 hs

Te contactaremos el próximo día hábil. Si querés ver propiedades disponibles, podés hacerlo en cualquier momento en: www.inmobiliariabertero.com.ar
```

### Pattern 2: Vendor Notification on Lead Registration (06-02)

**What:** When `registrar_lead_ghl()` is called, immediately send a WhatsApp summary to VENDEDOR_WHATSAPP with lead details. Same pattern as `solicitar_humano()`.

**Injection point:** End of `registrar_lead_ghl()` in `tools.py`, after GHL contact/opportunity creation succeeds.

**Key data available at injection point:** `telefono`, `nombre`, `email`, `operacion`, `tipo_propiedad`, `zona`, `propiedad_id`, `propiedad_link`, `propiedad_direccion`, `resumen` — all already parameters of `registrar_lead_ghl()`.

**Also:** `solicitar_humano()` already notifies vendor at handoff. The requirement FU-02 says "each time a lead is registered OR handoff happens". The handoff notification already exists (construir_mensaje_vendedor). Only the lead registration notification is missing.

**Message format for lead registration:**
```
*NUEVO LEAD — [nombre]*

📱 Teléfono: [tel]
📧 Email: [email]
🏠 Busca: [operacion] de [tipo] en [zona]
💰 Presupuesto: [resumen extracto]

[Si hay propiedad:]
📍 Propiedad: [direccion]
🔗 [link]

---
Lead registrado en CRM.
```

**Vendor notification helper:** Extract common notification helper to `agent/takeover.py` or keep in `tools.py`. Given both `solicitar_humano` and `registrar_lead_ghl` need it, a shared `_enviar_notificacion_vendedor(mensaje: str)` helper in `tools.py` avoids circular imports (tools already imports providers).

### Pattern 3: Follow-up Scheduling via n8n (06-03)

**What:** When `buscar_propiedades()` runs (client saw properties), record a `FollowUpSchedule` entry with status=`pending` and `scheduled_at = now + 24h`. If the client books, mark as `cancelled`. n8n Schedule Trigger fires every hour, calls `/admin/process-followups`, which finds `pending` entries with `scheduled_at <= now`, sends the WhatsApp follow-up, and marks as `sent`.

**New DB model:**
```python
# In agent/memory.py

class FollowUpSchedule(Base):
    __tablename__ = "follow_up_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | sent | cancelled
    propiedades_json: Mapped[str] = mapped_column(Text, default="")
    # JSON-serialized list of prop dicts shown to client
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    # UTC timestamp when to send the follow-up
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

**Status lifecycle:**
- `pending` → set when buscar_propiedades() runs for a phone
- `cancelled` → set when registrar_lead_ghl() or solicitar_humano() runs for same phone
- `sent` → set after /admin/process-followups sends the message

**Upsert semantics:** If client searches properties multiple times, upsert (telefono unique-ish): reset `scheduled_at = now + 24h` and `propiedades_json` to latest. Use `SELECT + UPDATE or INSERT` pattern (same as ConversationState in takeover.py — no UniqueConstraint needed, just query by telefono where status=pending).

**The n8n workflow (06-03):**
- Trigger: Schedule Trigger, every hour (consistent with Phase 2 refresh pattern)
- Node: HTTP Request POST to `https://[bot-url]/admin/process-followups` with `X-Admin-Token` header
- That's it — the Python endpoint does all the work

**Follow-up message format:**
```
Hola! 👋 Por acá Lucía de Bertero Inmobiliaria.

Hace unos días te mostramos algunas propiedades. ¿Pudiste verlas? ¿Te interesó alguna?

Si querés agendar una visita o tenés alguna consulta, estamos disponibles. 😊
```

**Cancellation points** (where to call `cancelar_followup(telefono)`):
1. `registrar_lead_ghl()` — lead booked a visit
2. `solicitar_humano()` — handoff to real agent
3. Optional: `reiniciar_conversacion()` — client started fresh (may have new interest)

### Anti-Patterns to Avoid

- **Checking business hours in Claude's system prompt:** Claude cannot know current time reliably. Business hours must be detected in Python before Claude is called.
- **Using `datetime.utcnow()` without timezone for business hours check:** Always use `datetime.now(TZ_BERTERO)` for the gate. `utcnow()` is UTC — Argentina is UTC-3, the difference matters.
- **Using session cache for follow-up state:** `session.py` `_cache` is in-memory. A 24-48h follow-up will always cross a server restart on Railway. Must use DB table.
- **Registering a follow-up on every single message:** Only register when `buscar_propiedades()` runs (client actually saw results). Not on greeting, not on lead registration.
- **Sending follow-up if client already booked or is in human takeover:** Check `FollowUpSchedule.status == 'pending'` and also check `ConversationState` before sending — if estado == 'humano', skip.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Scheduled delayed execution | Custom cron in Python | n8n Schedule Trigger → POST `/admin/process-followups` | n8n already runs for property refresh (Phase 2); consistent pattern; no extra process |
| Timezone conversion | UTC math manually | `zoneinfo.ZoneInfo("America/Argentina/Cordoba")` | DST edge cases, IANA correctness, built-in stdlib |
| WhatsApp vendor notification | New HTTP client | `proveedor.enviar_mensaje()` already exists | Same Whapi client used in solicitar_humano; no new code needed |

**Key insight:** n8n is already the scheduler for this project (Phase 2). Every "run something periodically" job goes through n8n → Python admin endpoint. Never add a new asyncio background loop when n8n can call a dedicated endpoint instead.

---

## Common Pitfalls

### Pitfall 1: Argentina Timezone on Minimal Docker Containers
**What goes wrong:** `zoneinfo.ZoneInfo("America/Argentina/Cordoba")` raises `ZoneInfoNotFoundError` on Alpine-based Docker images (no `/usr/share/zoneinfo`).
**Why it happens:** `zoneinfo` stdlib looks for IANA data in the OS first, then falls back to the `tzdata` pip package. Alpine doesn't ship tzdata by default.
**How to avoid:** Add `tzdata` to `requirements.txt`. The pip package provides the IANA database as a fallback. Current `Dockerfile` uses `python:3.11-slim` (Debian-based) which has OS tzdata, but explicit `tzdata` in requirements ensures it works everywhere.
**Warning signs:** `ZoneInfoNotFoundError: No time zone found with key America/Argentina/Cordoba` in logs at startup.

### Pitfall 2: Follow-up Fires After Lead Already Booked
**What goes wrong:** Client searches properties (follow-up scheduled), then books a visit, then receives follow-up 24h later asking if they're interested.
**Why it happens:** Follow-up table is not cancelled when lead is registered.
**How to avoid:** In `registrar_lead_ghl()`, call `cancelar_followup(telefono)` after successful GHL registration. Same in `solicitar_humano()`.
**Warning signs:** Vendor or client complaints about receiving follow-up after booking.

### Pitfall 3: After-hours Gate Must Not Fire for Vendor's Own Phone
**What goes wrong:** Vendor sends `#bot` command at 11pm, gets after-hours auto-response instead of command processing.
**Why it happens:** After-hours gate is placed in wrong position in main.py.
**How to avoid:** The gate MUST be placed AFTER the vendor command routing block. Vendor phone is routed and `continue`-d before business hours is ever checked. Current main.py order: vendor routing → rate limit → [INSERT after-hours here] → takeover gate → Claude.

### Pitfall 4: Multiple Pending Follow-ups for Same Phone
**What goes wrong:** Client searches properties 3 times, creating 3 pending follow-up rows. All 3 fire 24h later with duplicate messages.
**Why it happens:** `buscar_propiedades()` creates a new follow-up row on every call without checking for existing pending ones.
**How to avoid:** Upsert pattern — check for existing `pending` row for that phone, update it instead of inserting. Keep only one active follow-up per phone.

### Pitfall 5: Follow-up Sends to Phone in "humano" State
**What goes wrong:** Human takeover is active (vendor is attending), but bot sends an automated follow-up WhatsApp to the same client.
**Why it happens:** `/admin/process-followups` processes all `pending` rows without checking conversation state.
**How to avoid:** In the endpoint's processing loop, check `obtener_estado(telefono)`. If `estado == "humano"`, skip (don't send, don't cancel — the vendor may close the lead).

### Pitfall 6: Business Hours Bypass Needed for Testing
**What goes wrong:** Testing during after-hours is blocked by the gate — can't verify the bot's normal flow.
**How to avoid:** Add `BUSINESS_HOURS_ENABLED=true` env var (default true). When false, gate is skipped entirely. This is already the pattern for other optional features (`WHAPI_WEBHOOK_SECRET`, `GHL_WEBHOOK_AUTH_STRICT`).

---

## Code Examples

Verified patterns from codebase and stdlib:

### Business Hours Check (stdlib verified)
```python
# Source: Python docs zoneinfo + verified locally (2026-03-28)
# America/Argentina/Cordoba = UTC-3, NO DST (Argentina stopped DST in 2000)

from zoneinfo import ZoneInfo
from datetime import datetime

TZ_BERTERO = ZoneInfo("America/Argentina/Cordoba")

HORARIOS = {
    0: (9, 18),   # Monday
    1: (9, 18),   # Tuesday
    2: (9, 18),   # Wednesday
    3: (9, 18),   # Thursday
    4: (9, 18),   # Friday
    5: (10, 14),  # Saturday
    6: None,      # Sunday — closed
}

def esta_en_horario() -> bool:
    now = datetime.now(TZ_BERTERO)
    rango = HORARIOS.get(now.weekday())
    if rango is None:
        return False
    return rango[0] <= now.hour < rango[1]
```

### After-hours Gate in main.py (pattern matches existing takeover gate)
```python
# Insert in webhook_handler AFTER rate limit check, BEFORE obtener_estado()
# Source: pattern derived from existing takeover gate at line 196 of main.py

if BUSINESS_HOURS_ENABLED and not esta_en_horario():
    # Register lead for next-day follow-up
    await programar_followup_after_hours(telefono_normalizado)
    # Send auto-response with schedule info
    await proveedor.enviar_mensaje(msg.telefono, AFTER_HOURS_MESSAGE)
    logger.info(f"After-hours: auto-response sent to {telefono_normalizado}")
    continue  # Do NOT call Claude
```

### FollowUpSchedule Upsert (pattern from ConversationState in takeover.py)
```python
# Source: pattern from takeover.py set_estado() function (lines 38-66)

async def programar_followup(telefono: str, propiedades: list[dict], delay_hours: int = 24) -> None:
    """Upsert: create or reset pending follow-up for this phone."""
    import json
    scheduled = datetime.utcnow() + timedelta(hours=delay_hours)
    props_json = json.dumps(propiedades[:5])  # Cap at 5 props

    async with async_session() as session:
        query = (
            select(FollowUpSchedule)
            .where(FollowUpSchedule.telefono == telefono)
            .where(FollowUpSchedule.status == "pending")
        )
        result = await session.execute(query)
        row = result.scalar_one_or_none()

        if row:
            row.scheduled_at = scheduled
            row.propiedades_json = props_json
            row.updated_at = datetime.utcnow()
        else:
            session.add(FollowUpSchedule(
                telefono=telefono,
                status="pending",
                propiedades_json=props_json,
                scheduled_at=scheduled,
            ))
        await session.commit()
```

### Vendor Notification Helper (extends existing pattern)
```python
# Source: derived from solicitar_humano() in tools.py (lines 744-779)
# Same proveedor.enviar_mensaje() pattern

async def _enviar_notificacion_vendedor(mensaje: str) -> None:
    """Sends a WhatsApp message to VENDEDOR_WHATSAPP. Graceful if unset."""
    from agent.providers import obtener_proveedor
    from agent.utils import normalizar_telefono

    vendedor_raw = os.getenv("VENDEDOR_WHATSAPP", "")
    if not vendedor_raw:
        logger.warning("VENDEDOR_WHATSAPP no configurado — notificacion vendedor omitida")
        return
    try:
        prv = obtener_proveedor()
        vendedor_wa = normalizar_telefono(vendedor_raw) + "@s.whatsapp.net"
        await prv.enviar_mensaje(vendedor_wa, mensaje)
    except Exception as e:
        logger.error(f"Error enviando notificacion vendedor: {e}")
```

### Cancelling Follow-up at Booking
```python
# Source: pattern from takeover.py set_estado(), inject into registrar_lead_ghl()

async def cancelar_followup(telefono: str) -> None:
    """Mark any pending follow-up for this phone as cancelled."""
    async with async_session() as session:
        query = (
            select(FollowUpSchedule)
            .where(FollowUpSchedule.telefono == telefono)
            .where(FollowUpSchedule.status == "pending")
        )
        result = await session.execute(query)
        rows = result.scalars().all()
        for row in rows:
            row.status = "cancelled"
            row.updated_at = datetime.utcnow()
        await session.commit()
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Business hours in system prompt ("tell Claude what time it is") | Python gate in webhook handler, before Claude | Claude cannot reliably know current time; Python is deterministic |
| Always-on bot (no hours awareness) | `esta_en_horario()` check before every inbound message | Bertero requirement FU-03; prevents bot from making promises it can't keep |
| Session cache for follow-up state | SQLite FollowUpSchedule table | Session cache lost on restart; DB survives Railway deploys |

---

## New Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `BUSINESS_HOURS_ENABLED` | `true` | Toggle for testing — when false, business hours gate is skipped |
| `BUSINESS_TIMEZONE` | `America/Argentina/Cordoba` | Timezone string for business hours detection (zoneinfo key) |
| `N8N_FOLLOWUP_WEBHOOK` | (empty) | URL n8n calls to trigger follow-up sending; not used, Python endpoint is called BY n8n |
| `FOLLOWUP_DELAY_HOURS` | `24` | Hours after property search before follow-up is sent |

Note: `N8N_FOLLOWUP_WEBHOOK` is not needed — n8n calls `/admin/process-followups` on a schedule (same pattern as `/admin/refresh-properties`). No outbound call from Python to n8n for follow-up.

---

## Open Questions

1. **After-hours: should the bot respond to returning clients differently?**
   - What we know: FU-03 says "bot responds automatically indicating schedule + registers lead for next-day follow-up"
   - What's unclear: Should a client who already has an active conversation (knows the bot) get a different message than a new client?
   - Recommendation: Same message for both — simpler, and the requirement doesn't distinguish. The message can be generic.

2. **Follow-up: should it only fire once or retry if no response?**
   - What we know: FU-01 says "24-48 hours after", suggesting a single touch
   - What's unclear: No second follow-up is specified
   - Recommendation: Single follow-up. Mark as `sent` and do not retry. Excessive follow-up damages brand trust.

3. **Vendor notification message: does FU-02 require a new message format or reuse handoff format?**
   - What we know: FU-02 explicitly lists: nombre, telefono, email, operacion, tipo, zona, presupuesto, propiedades con links
   - What's unclear: The handoff message (construir_mensaje_vendedor) already has some of this but not all
   - Recommendation: New `construir_mensaje_lead()` function alongside the existing `construir_mensaje_vendedor()` in takeover.py. Same file, different function, different purpose.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis — `agent/main.py`, `agent/takeover.py`, `agent/tools.py`, `agent/memory.py`, `agent/session.py` — all implementation patterns
- Python stdlib docs — `zoneinfo` module, `datetime.weekday()` — business hours detection
- Verified locally — `ZoneInfo("America/Argentina/Cordoba")` confirmed working with `tzdata==2025.3` pip package (2026-03-28)
- `.planning/phases/05-human-takeover/05-RESEARCH.md` — confirmed ConversationState DB pattern for persistent state

### Secondary (MEDIUM confidence)
- n8n Wait node docs — confirmed n8n workflows persist state across restarts for long waits; confirmed Schedule Trigger + HTTP Request pattern is standard
- IANA tzdata — Argentina/Cordoba confirmed UTC-3 fixed offset, no DST since 2000

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project, no new dependencies except tzdata declaration
- Architecture: HIGH — direct codebase analysis, all injection points identified precisely
- Pitfalls: HIGH — based on concrete code paths in existing files
- n8n follow-up pattern: HIGH — same as Phase 2 `/admin/refresh-properties` pattern, already working

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable domain; no fast-moving dependencies)
