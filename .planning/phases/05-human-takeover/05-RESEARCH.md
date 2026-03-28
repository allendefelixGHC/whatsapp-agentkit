# Phase 5: Human Takeover - Research

**Researched:** 2026-03-28
**Domain:** Conversation state management, real-time vendor notification via WhatsApp, timeout-based auto-return
**Confidence:** HIGH (all findings based on direct codebase analysis — no external API unknowns)

---

## Summary

Phase 5 adds a human takeover mechanism: when a client requests a human, the bot pauses, notifies the assigned vendor via WhatsApp with a context summary, and stops responding to that client. The vendor can return control to the bot via a command or after a configurable timeout.

The existing codebase already has all the primitives needed. The `Mensaje` SQLAlchemy model in `memory.py` needs one new table (`ConversationState`) with three states: `bot`, `humano`, `cerrado`. The `main.py` webhook handler already normalizes phone numbers and retrieves history before generating a response — the state check inserts at exactly that point as a gate. The `proveedor.enviar_mensaje()` method already knows how to send WhatsApp messages to any phone number — including the vendor's number. The `obtener_historial()` function already retrieves the context summary needed for the vendor notification.

The most architecturally interesting requirement is HT-05: the vendor returning control via a command. This requires the webhook to recognize messages from the **vendor's phone number** as administrative commands rather than client messages. The solution is: store `VENDEDOR_WHATSAPP` in `.env`, check if `msg.telefono` (normalized) matches that number in the webhook handler, and route to command processing. A configurable timeout (default 4 hours) auto-returns the bot when the vendor is inactive.

**Primary recommendation:** Add one new SQLAlchemy model (`ConversationState`), one new tool (`solicitar_humano`), one new module (`agent/takeover.py` for vendor command routing), extend `main.py` to check conversation state before calling Claude, and add `VENDEDOR_WHATSAPP` + `TAKEOVER_TIMEOUT_HOURS` to `.env`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sqlalchemy` | already installed | `ConversationState` table for bot/humano/cerrado flag | Already manages `Mensaje` table; same async session pattern |
| `anthropic` | already installed | Claude generates the context summary for vendor notification | Already running the tool_use loop in `brain.py` |
| `httpx` | already installed | Whapi call to send vendor notification WhatsApp | Already used in `providers/whapi.py` for all outbound messages |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio` | stdlib | `asyncio.create_task()` for timeout auto-return background job | Needed to schedule timeout check without blocking webhook response |
| `dotenv` | already installed | `VENDEDOR_WHATSAPP`, `TAKEOVER_TIMEOUT_HOURS` env vars | Already loaded in all modules |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New SQLAlchemy table (`ConversationState`) | In-memory dict | In-memory loses state on restart — not acceptable for production; DB table survives restart |
| In-memory dict | New SQLAlchemy table | Simpler but loses takeover state on server restart, creating phantom "human mode" sessions |
| asyncio background task for timeout | APScheduler | APScheduler adds a dependency; asyncio task is sufficient for this simple use case |
| Vendor commands in same `/webhook` endpoint | New `/vendor` endpoint | No new endpoint needed; vendor uses WhatsApp like a client — same webhook, identified by phone number |

**Installation:** No new dependencies required.

---

## Architecture Patterns

### Recommended Project Structure

New files:
```
agent/
├── takeover.py          ← New: state CRUD + vendor command routing + timeout logic
```

Modified files:
```
agent/
├── memory.py            ← Add ConversationState model + state functions
├── main.py              ← Add state check gate before generar_respuesta + vendor command routing
├── tools.py             ← Add solicitar_humano() function + TOOLS_DEFINITION entry
└── brain.py             ← Add solicitar_humano to _ejecutar_herramienta()

config/
└── prompts.yaml         ← Add human takeover trigger instructions

.env / .env.example      ← Add VENDEDOR_WHATSAPP, TAKEOVER_TIMEOUT_HOURS
```

### Pattern 1: Conversation State as a DB Table

**What:** A `ConversationState` SQLAlchemy model stores one row per phone number with a `estado` column (`bot` | `humano` | `cerrado`) and a `updated_at` timestamp.

**When to use:** Any time the webhook processes a message — check state first.

**Why DB (not in-memory dict):**
- Survives server restart (Railway restarts are common during deploys)
- Same async session pattern as `Mensaje` — no new infrastructure
- Queryable for timeout logic (find all `humano` rows where `updated_at < now - timeout`)

**Schema:**

```python
# Source: pattern mirrors Mensaje model in agent/memory.py

class ConversationState(Base):
    """Estado de la conversación: bot, humano, o cerrado."""
    __tablename__ = "conversation_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    estado: Mapped[str] = mapped_column(String(20), default="bot")  # "bot" | "humano" | "cerrado"
    vendedor: Mapped[str] = mapped_column(String(100), default="")  # nombre del vendedor asignado
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

**CRUD functions (go in `agent/takeover.py`):**

```python
async def obtener_estado(telefono: str) -> str:
    """Retorna 'bot', 'humano', o 'cerrado'. Default: 'bot' si no existe."""

async def set_estado(telefono: str, estado: str, vendedor: str = "") -> None:
    """Upsert el estado de la conversación."""

async def check_and_apply_timeouts() -> list[str]:
    """
    Busca conversaciones en estado 'humano' con updated_at más viejo que TAKEOVER_TIMEOUT_HOURS.
    Las devuelve al estado 'bot' y retorna la lista de teléfonos afectados.
    """
```

### Pattern 2: State Gate in main.py Webhook Handler

**What:** Before calling `generar_respuesta`, check the conversation state. If `humano`, skip Claude entirely and optionally send an acknowledgment message.

**Where exactly in main.py to insert:** After the rate limit check, before `obtener_historial`:

```python
# Source: analysis of webhook handler flow in agent/main.py lines 157-216

# NUEVO: verificar estado de takeover ANTES de llamar a Claude
from agent.takeover import obtener_estado
estado = await obtener_estado(telefono_normalizado)
if estado == "humano":
    # El bot está en pausa — NO generar respuesta ni guardar en historial
    logger.info(f"Conversación {telefono_normalizado} en modo HUMANO — ignorando mensaje")
    continue  # Saltar este mensaje completamente
```

**Critical decision:** Do NOT send any auto-reply when in `humano` state. The client expects to be talking to a human; an auto-reply from the bot breaks that expectation. Silence is correct.

### Pattern 3: solicitar_humano as a Claude Tool

**What:** Claude calls `solicitar_humano(telefono, resumen)` when it detects the client wants a human. This tool: (1) sets state to `humano` in DB, (2) sends WhatsApp notification to vendor.

**Why a tool, not a system prompt instruction:**
- Same pattern as `reiniciar_conversacion` — Claude tools are the established mechanism for side effects in this codebase
- Allows Claude to compute the `resumen` string with context before the state change
- The tool returns a string that Claude uses in its final response to the client

**Tool function:**

```python
# In agent/tools.py

async def solicitar_humano(telefono: str, resumen: str) -> str:
    """
    Pausa el bot y notifica al vendedor asignado por WhatsApp.
    Llamar cuando el cliente pide hablar con una persona.

    Args:
        telefono: Teléfono del cliente (del contexto interno)
        resumen: Resumen de la conversación — qué busca, presupuesto, propiedades vistas
    """
    from agent.takeover import set_estado, construir_mensaje_vendedor
    from agent.ghl import VENDEDOR_DEFAULT

    # 1. Cambiar estado a "humano"
    await set_estado(telefono, "humano")

    # 2. Enviar WhatsApp al vendedor
    vendedor_phone = os.getenv("VENDEDOR_WHATSAPP", "")
    if vendedor_phone:
        mensaje_vendedor = construir_mensaje_vendedor(telefono, resumen)
        vendedor_wa = normalizar_telefono(vendedor_phone) + "@s.whatsapp.net"
        await proveedor.enviar_mensaje(vendedor_wa, mensaje_vendedor)
        logger.info(f"Notificación de takeover enviada a {vendedor_phone}")
    else:
        logger.warning("VENDEDOR_WHATSAPP no configurado — notificación por WhatsApp omitida")

    return (
        "Estado cambiado a 'humano'. "
        "Notificación enviada al vendedor. "
        "Responder al cliente que ya se conectó con el equipo."
    )
```

**Tool definition to add to TOOLS_DEFINITION:**

```python
{
    "name": "solicitar_humano",
    "description": (
        "Pausa el bot y notifica al vendedor asignado por WhatsApp. "
        "Llamar cuando el cliente diga: 'quiero hablar con alguien', 'me pasás con una persona', "
        "'hablar con un asesor', 'necesito ayuda de alguien', o frases similares que impliquen "
        "querer hablar con un humano. "
        "El resumen debe incluir: nombre si se sabe, qué busca (tipo, zona, presupuesto), "
        "propiedades que vio, y cualquier detalle relevante de la conversación. "
        "El teléfono del cliente está en el contexto interno."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "telefono": {
                "type": "string",
                "description": "Teléfono del cliente del contexto interno"
            },
            "resumen": {
                "type": "string",
                "description": "Resumen completo: nombre, qué busca, zona, presupuesto, propiedades vistas"
            }
        },
        "required": ["telefono", "resumen"]
    }
}
```

### Pattern 4: Vendor Command Routing in main.py

**What:** When a message arrives from the vendor's WhatsApp number (identified by `VENDEDOR_WHATSAPP`), route it to command processing instead of Claude.

**Supported commands:**
- `#bot <phone>` — Return specific conversation to bot mode
- `#bot-all` — Return ALL conversations currently in human mode to bot
- `#estado <phone>` — Check state of a conversation (for debugging)

**Where in main.py:** After parsing the message but before the rate limit check — vendor commands bypass rate limiting.

```python
# Source: analysis of main.py webhook handler structure

VENDEDOR_PHONE_NORM = normalizar_telefono(os.getenv("VENDEDOR_WHATSAPP", ""))

# En el loop de mensajes, ANTES del rate limit:
if VENDEDOR_PHONE_NORM and normalizar_telefono(msg.telefono) == VENDEDOR_PHONE_NORM:
    await _procesar_comando_vendedor(msg.texto, msg.telefono)
    continue  # No procesar como mensaje de cliente
```

**`_procesar_comando_vendedor` function (in `agent/takeover.py`):**

```python
async def procesar_comando_vendedor(texto: str, vendedor_telefono: str) -> None:
    """
    Procesa comandos del vendedor para control del takeover.
    Envía confirmación al vendedor por WhatsApp.
    """
    from agent.takeover import set_estado, obtener_estado, listar_conversaciones_humano
    texto = texto.strip()

    if texto.lower().startswith("#bot "):
        # #bot <phone> — devolver conversación específica al bot
        phone = texto[5:].strip()
        phone_norm = normalizar_telefono(phone)
        await set_estado(phone_norm, "bot")
        await proveedor.enviar_mensaje(vendedor_telefono, f"Conversacion {phone} devuelta al bot.")

    elif texto.lower() == "#bot-all":
        # Devolver todas las conversaciones en modo humano
        devueltas = await devolver_todas_al_bot()
        await proveedor.enviar_mensaje(vendedor_telefono, f"{len(devueltas)} conversaciones devueltas al bot.")

    elif texto.lower().startswith("#estado "):
        # Consultar estado de una conversación
        phone = texto[8:].strip()
        phone_norm = normalizar_telefono(phone)
        estado = await obtener_estado(phone_norm)
        await proveedor.enviar_mensaje(vendedor_telefono, f"Estado de {phone}: {estado}")
```

### Pattern 5: Timeout Auto-Return

**What:** A background task (started at server lifespan) periodically checks for `humano` conversations older than `TAKEOVER_TIMEOUT_HOURS` and returns them to `bot`.

**Why asyncio.create_task (not a scheduler):**
- This codebase has no scheduler. APScheduler would be a new dependency.
- A simple `while True: await asyncio.sleep(3600)` loop inside an `asyncio.create_task()` is sufficient for hourly checks.
- The task is started in `lifespan()` in `main.py` — same pattern used for `cargar_cache_desde_supabase()`.

```python
# In agent/takeover.py

async def timeout_loop():
    """Runs forever, hourly. Returns timed-out human conversations to bot."""
    timeout_hours = int(os.getenv("TAKEOVER_TIMEOUT_HOURS", "4"))
    while True:
        await asyncio.sleep(3600)  # Check every hour
        devueltas = await check_and_apply_timeouts(timeout_hours)
        if devueltas:
            logger.info(f"Timeout: {len(devueltas)} conversaciones devueltas al bot: {devueltas}")
```

```python
# In agent/main.py lifespan():
import asyncio
from agent.takeover import timeout_loop

asyncio.create_task(timeout_loop())
```

### Pattern 6: Vendor Notification Message Format

**What:** The WhatsApp message sent to the vendor when a client requests a human. Must include: client phone (clickable in WA), what they're looking for, properties seen, budget.

**Format (plain text — no markdown, WhatsApp renders it):**

```
TAKEOVER — Cliente solicita asesor

Cliente: +549XXXXXXXXXX
Estado: en conversación activa

Resumen:
[RESUMEN GENERADO POR CLAUDE — incluye nombre si sabe, qué busca, zona, presupuesto, propiedades vistas con links]

---
Para devolver al bot: #bot +549XXXXXXXXXX
```

**Why Claude generates the resumen (not a template):** Claude already has the conversation history and can produce a natural, comprehensive summary. A hardcoded template would require regex extraction of name/zone/budget from the history — fragile. Better to let Claude summarize as part of calling the tool.

### Anti-Patterns to Avoid

- **Sending auto-reply when in humano state:** Never respond to the client while in `humano` mode. The client thinks they're talking to a human — any bot message breaks that. Silence is the correct behavior.
- **Checking state AFTER calling generar_respuesta:** The state check MUST be before Claude is called (no wasted tokens). Gate early in the webhook handler.
- **Storing vendor phone in GHL instead of .env:** Vendor phone is an operational config, not a data entity. `.env` is the right place; GHL lookup adds latency and a dependency.
- **Using asyncio.sleep in the tool itself:** `solicitar_humano` is called synchronously by the Claude tool loop. No blocking or sleeping in the tool function.
- **Multiple vendor phones:** HT-03 says "el vendedor asignado" (singular). Start with one `VENDEDOR_WHATSAPP`. Multi-vendor routing (by zone from GHL `asignar_vendedor()`) is a Phase 6+ enhancement.
- **Saving vendor commands to conversation history:** When the vendor sends `#bot <phone>`, that command must NOT be saved to the client's conversation `Mensaje` table. It's an admin action, not part of the client conversation.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Conversation state persistence | Custom state file or in-memory dict | SQLAlchemy `ConversationState` table | Survives restart; same async session pattern already in `memory.py` |
| Sending vendor notification | SMTP email | `proveedor.enviar_mensaje()` to vendor's WhatsApp | WhatsApp is real-time; SMTP has delivery delay; existing method works for any phone number |
| Scheduled timeout checks | APScheduler, Celery | `asyncio.create_task()` + `while True: sleep(3600)` | No new dependency; codebase already uses async throughout |
| Detecting takeover intent | Intent classifier | Claude `solicitar_humano` tool + system prompt instructions | Existing tool_use loop already handles this; Claude detects conversational intent reliably |
| Vendor command parsing | Regex-heavy parser | Simple `startswith("#bot")` string checks | Commands are short, structured, typed by the vendor — no complex parsing needed |

**Key insight:** This phase adds one new DB table, one new Python module, and hooks into three existing extension points (`main.py` webhook handler, `tools.py` TOOLS_DEFINITION, `brain.py` dispatcher). No new frameworks.

---

## Common Pitfalls

### Pitfall 1: Race Condition Between State Check and Message Processing

**What goes wrong:** Two webhook calls arrive simultaneously for the same phone (Whapi retry). First call sets state to `humano`. Second call already passed the state check and is calling Claude. Claude responds to a client that's in human mode.

**Why it happens:** The async webhook handler and the SQLite async session are both non-blocking. Between `obtener_estado()` returning `bot` and `set_estado("humano")` completing, another request can slip through.

**How to avoid:** The deduplication system (`agent/dedup.py`) already prevents Whapi retries from double-processing. The race window is only relevant for two DIFFERENT messages arriving very close together. Since `solicitar_humano` is called DURING the response (by Claude), the state only changes AFTER the first call completes. The second call's state check happens before the first call's tool execution. This is a genuine race but extremely rare in practice (requires two WhatsApp messages within milliseconds). Document it; don't over-engineer the fix.

**Warning signs:** Log lines showing `generar_respuesta` called after `set_estado("humano")` for the same telefono.

### Pitfall 2: Vendor's Own Phone Messages Trigger Claude

**What goes wrong:** The vendor sends `#bot 5493517575244` to the bot number. The webhook receives this, normalizes the phone, and routes it to Claude instead of command processing. Claude sees a message that starts with `#bot` and is confused.

**Why it happens:** If `VENDEDOR_WHATSAPP` is not set in `.env`, the vendor phone check is skipped. OR if the normalization of `msg.telefono` doesn't match `normalizar_telefono(VENDEDOR_WHATSAPP)`.

**How to avoid:**
1. The vendor phone check must run BEFORE rate limiting and Claude, early in the message loop.
2. Use `normalizar_telefono()` on BOTH sides of the comparison (not raw strings).
3. Add a log line when vendor command is processed to confirm detection.
4. If `VENDEDOR_WHATSAPP` is empty (not configured), log a WARNING at startup: "VENDEDOR_WHATSAPP not set — vendor command routing disabled".

**Warning signs:** Log showing `Mensaje de {vendedor_phone}: #bot ...` processed by Claude instead of command router.

### Pitfall 3: Timeout Loop Not Restarted After Server Restart

**What goes wrong:** Server restarts (Railway deploy). The `asyncio.create_task(timeout_loop())` in `lifespan()` is re-created correctly. BUT if a conversation was in `humano` state before the restart, it has been there for potentially hours — the timeout may have already passed. The timeout loop won't process it until 1 hour into the loop.

**Why it happens:** The `asyncio.sleep(3600)` runs before the first check.

**How to avoid:** Run `check_and_apply_timeouts()` ONCE at startup (in `lifespan()`, before the task is created), then enter the loop. This catches stale `humano` states immediately on restart.

**Warning signs:** `humano` state persisting well past the configured timeout after a server restart.

### Pitfall 4: Vendor Notification Message With Wrong WhatsApp Format

**What goes wrong:** `VENDEDOR_WHATSAPP=+5493517575244`. After `normalizar_telefono()`, it becomes `5493517575244`. Then `+ "@s.whatsapp.net"` = `5493517575244@s.whatsapp.net`. This is the correct Whapi format. BUT if the vendor's number starts with a country code that's NOT Argentina, `normalizar_telefono()` may apply the Argentina-specific `549` prefix logic incorrectly.

**Why it happens:** `normalizar_telefono()` has Argentina-specific logic (adds `549` for 10-digit numbers, fixes the "missing 9" pattern for AR numbers).

**How to avoid:** Document in `.env.example` that `VENDEDOR_WHATSAPP` must be in full international format with country code: `VENDEDOR_WHATSAPP=5493517575244` (or `+5493517575244`). Since Bertero is Argentina-based, this is fine — but note the constraint.

**Warning signs:** WhatsApp notification fails to deliver to vendor; check normalized phone in logs.

### Pitfall 5: Client Messages Saved to History While in Human Mode

**What goes wrong:** The `main.py` handler saves client messages to history (`guardar_mensaje`) AFTER the bot response. If we `continue` early when state is `humano`, we skip the `guardar_mensaje` call — which is correct behavior (don't save messages from human-mode conversations). BUT this means when the vendor returns control (`#bot`), the conversation history in DB is missing the messages exchanged during human mode.

**Why it happens:** By design — the bot doesn't see those messages.

**How to avoid:** This is acceptable and expected. Document it: "Messages exchanged while in human mode are NOT persisted to bot history. When returning to bot mode, the bot starts with history up to the takeover point." The vendor can catch Claude up by asking the client to briefly restate their need, or Claude will ask clarifying questions naturally.

**Warning signs:** None — this is intentional behavior, not a bug.

### Pitfall 6: solicitar_humano Called Repeatedly for Same Client

**What goes wrong:** Client sends multiple messages like "quiero hablar con alguien" "AYUDA" "necesito un asesor" in quick succession. Claude calls `solicitar_humano` for each. Vendor receives 3 WhatsApp notifications for the same client.

**Why it happens:** Each webhook call is independent; state check is `estado == "humano"` but the tool sets it to `humano` inside the tool execution — the second and third calls may not yet see the updated state.

**How to avoid:** In `solicitar_humano`, check the current state BEFORE sending the notification: `if await obtener_estado(telefono) == "humano": return "Ya en estado humano."`. If already `humano`, skip the WA notification and return early. This is an idempotency guard.

---

## Code Examples

### ConversationState Model (agent/memory.py addition)

```python
# Source: mirrors Mensaje model pattern in agent/memory.py

class ConversationState(Base):
    """Estado de la conversación por número de teléfono."""
    __tablename__ = "conversation_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    estado: Mapped[str] = mapped_column(String(20), default="bot")  # "bot" | "humano" | "cerrado"
    vendedor: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

### State Gate in main.py

```python
# Source: analysis of webhook handler, agent/main.py lines 155-165
# Insert AFTER rate limit check, BEFORE obtener_historial:

from agent.takeover import obtener_estado

estado_conv = await obtener_estado(telefono_normalizado)
if estado_conv == "humano":
    logger.info(f"Conversación {telefono_normalizado} en modo HUMANO — bot en pausa")
    continue  # Skip Claude entirely, no response sent, no history saved
```

### Idempotent solicitar_humano

```python
# Source: pattern derived from reiniciar_conversacion in agent/tools.py

async def solicitar_humano(telefono: str, resumen: str) -> str:
    from agent.takeover import obtener_estado, set_estado, construir_mensaje_vendedor

    # Idempotency: don't re-notify if already in human mode
    estado_actual = await obtener_estado(telefono)
    if estado_actual == "humano":
        return "Ya en estado humano. Vendedor ya fue notificado."

    # Set state first, then notify
    await set_estado(telefono, "humano")

    vendedor_phone_raw = os.getenv("VENDEDOR_WHATSAPP", "")
    if vendedor_phone_raw:
        from agent.utils import normalizar_telefono
        from agent.providers import obtener_proveedor
        prv = obtener_proveedor()
        msg = construir_mensaje_vendedor(telefono, resumen)
        vendedor_wa = normalizar_telefono(vendedor_phone_raw) + "@s.whatsapp.net"
        await prv.enviar_mensaje(vendedor_wa, msg)
        logger.info(f"Takeover notificación enviada a {vendedor_phone_raw}")
    else:
        logger.warning("VENDEDOR_WHATSAPP no configurado — notificación WhatsApp omitida")

    return (
        "Estado cambiado a 'humano'. Vendedor notificado por WhatsApp. "
        "Confirmar al cliente que lo va a atender un asesor."
    )
```

### Vendor Message Format Builder

```python
# In agent/takeover.py

def construir_mensaje_vendedor(cliente_telefono: str, resumen: str) -> str:
    """Construye el mensaje WhatsApp para notificar al vendedor del takeover."""
    return (
        f"*TAKEOVER — Cliente solicita asesor*\n\n"
        f"*Cliente:* {cliente_telefono}\n\n"
        f"*Resumen:*\n{resumen}\n\n"
        f"---\n"
        f"Para devolver al bot:\n"
        f"`#bot {cliente_telefono}`\n\n"
        f"Para ver estado:\n"
        f"`#estado {cliente_telefono}`"
    )
```

### Timeout Check (for check_and_apply_timeouts)

```python
# In agent/takeover.py
# Uses same async_session pattern as memory.py

from datetime import datetime, timedelta
from sqlalchemy import select, update

async def check_and_apply_timeouts(timeout_hours: int = 4) -> list[str]:
    """Devuelve al bot todas las conversaciones humano con inactividad > timeout_hours."""
    cutoff = datetime.utcnow() - timedelta(hours=timeout_hours)
    async with async_session() as session:
        query = (
            select(ConversationState)
            .where(ConversationState.estado == "humano")
            .where(ConversationState.updated_at < cutoff)
        )
        result = await session.execute(query)
        stale = result.scalars().all()
        telefonos = []
        for conv in stale:
            conv.estado = "bot"
            conv.updated_at = datetime.utcnow()
            telefonos.append(conv.telefono)
        await session.commit()
    return telefonos
```

### System Prompt Block (prompts.yaml addition)

```yaml
## Takeover — cuando el cliente pide hablar con un humano (HT-02)
Cuando el cliente diga explícitamente que quiere hablar con una persona
(frases: "quiero hablar con alguien", "me pasás con un asesor", "necesito un humano",
"hablar con una persona", "con alguien real", "con el equipo", o equivalentes):
1. Llamar a solicitar_humano con:
   - telefono: del contexto interno
   - resumen: "Nombre: [si se sabe]. Busca: [tipo] en [zona] para [compra/alquiler].
     Presupuesto: [si mencionó]. Propiedades vistas: [IDs/direcciones si vio].
     Motivo del takeover: [qué dijo el cliente que generó el pedido de humano]."
2. Responder al cliente: "¡Claro! Ya le avisé a uno de nuestros asesores. Te va a contactar en breve por este mismo chat para ayudarte personalmente. 😊"

IMPORTANTE: Una vez que llamaste a solicitar_humano, NO seguir respondiendo al cliente.
El bot está en pausa. El próximo mensaje del cliente no será procesado por el bot.
```

### .env.example additions

```env
# ── Human Takeover ────────────────────────────────────────
# Teléfono del vendedor en formato internacional completo (sin + ni @s.whatsapp.net)
# El bot enviará notificación WhatsApp a este número cuando un cliente pida hablar con alguien
# Ej: 5493517575244 para Argentina +549 (351) 757-5244
VENDEDOR_WHATSAPP=5493517575244

# Horas de inactividad antes de devolver automáticamente una conversación al bot (default 4)
TAKEOVER_TIMEOUT_HOURS=4
```

---

## State of the Art

| Old Approach | Current Approach (Phase 5) | Impact |
|--------------|---------------------------|--------|
| Bot always responds to every client message | State gate: skip Claude when estado == "humano" | HT-04 satisfied |
| No conversation state | `ConversationState` SQLAlchemy table | HT-01 satisfied |
| Vendor notification via email (slow) | Direct WhatsApp via `proveedor.enviar_mensaje()` | HT-03: real-time notification |
| No way for vendor to signal "I'm done" | `#bot <phone>` command via same WhatsApp | HT-05 satisfied |
| No timeout | `asyncio` background task + `TAKEOVER_TIMEOUT_HOURS` | HT-05 (auto-return) satisfied |

**Deprecated/outdated:**
- Nothing deprecated — this phase only adds to existing patterns.

---

## Open Questions

1. **Multi-vendor: which vendor gets the notification?**
   - What we know: `ghl.py` already has `asignar_vendedor(zona)` which maps zones to specific vendors (Abhay Bertero vs Martin Lopez). Each has a name but NOT a phone number stored yet.
   - What's unclear: Do we need per-vendor WhatsApp numbers, or is one shared `VENDEDOR_WHATSAPP` sufficient for now?
   - Recommendation: Start with single `VENDEDOR_WHATSAPP`. Add `VENDEDOR_ABHAY_WHATSAPP` / `VENDEDOR_MARTIN_WHATSAPP` in Phase 6 when per-vendor routing is needed. Phase 5 success criteria says "vendedor asignado recibe notificación" — singular is fine for now.

2. **`#bot` command format: phone format reliability**
   - What we know: The vendor will type the phone number as seen in the WA chat or the notification message. This could be `+549...` or `5493...` or just the local format.
   - What's unclear: Will `normalizar_telefono()` reliably parse whatever the vendor types?
   - Recommendation: In `construir_mensaje_vendedor()`, always include the phone in the exact canonical format (`5493XXXXXXXXXX`) AND in the `#bot` command example. Document to the vendor that they should copy-paste from the notification. Also: make the command parser tolerant — strip `+` and `@s.whatsapp.net` before normalizing.

3. **What if the client writes while in humano mode? Should the bot acknowledge?**
   - What we know: HT-04 says bot does NOT respond. Current plan is silence.
   - What's unclear: Is silence confusing to the client? Should there be a one-time "Un asesor ya está viendo tu caso" auto-reply on the FIRST new message in humano mode?
   - Recommendation: Keep silence as the default (per HT-04). If the client gets confused, the vendor can clarify in their response. Adding an auto-reply would require tracking "first message after takeover" state, adding complexity. Planner decision.

4. **Should `cerrado` state be implemented in Phase 5?**
   - What we know: HT-01 lists `cerrado` as a valid state alongside `bot` and `humano`.
   - What's unclear: Nothing in Phase 5 requirements actively uses `cerrado` — it's a future state for when a deal closes.
   - Recommendation: Include the `cerrado` state in the schema (it costs nothing) but don't add any logic to transition to it. That's Phase 6 territory.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis — `agent/memory.py` (SQLAlchemy patterns), `agent/main.py` (webhook handler gate point), `agent/tools.py` (TOOLS_DEFINITION pattern, `reiniciar_conversacion` as established template), `agent/brain.py` (`_ejecutar_herramienta` dispatcher), `agent/providers/whapi.py` (`enviar_mensaje` for outbound WA), `agent/ghl.py` (`asignar_vendedor` zone routing), `agent/utils.py` (`normalizar_telefono`)
- All claims about hook points, function signatures, and DB patterns are verified against live source code

### Secondary (MEDIUM confidence)
- asyncio task pattern for background loops — standard Python docs pattern, verified against Python 3.11 asyncio docs

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, verified against existing imports
- Architecture: HIGH — all patterns derived from direct code reading of existing extension points
- Pitfalls: HIGH — identified from reading `main.py` flow, `memory.py` session patterns, and `tools.py` tool execution loop

**Research date:** 2026-03-28
**Valid until:** Stable — only invalidated by changes to `memory.py` SQLAlchemy session, `main.py` webhook handler structure, or `providers/whapi.py` send API
