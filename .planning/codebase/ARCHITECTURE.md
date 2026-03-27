# Architecture

**Analysis Date:** 2026-03-27

## Pattern Overview

**Overall:** Provider-agnostic AI agent with layered tool-use orchestration

**Key Characteristics:**
- Single FastAPI server exposing two inbound webhook routes (`/webhook` for WhatsApp, `/webhook/ghl` for CRM events)
- Claude API is called with a `tool_use` loop: first call may invoke data tools (search, lead registration), second call formulates the final human-facing response, optionally adding interactive UI elements (buttons/lists)
- All WhatsApp provider differences are hidden behind an abstract `ProveedorWhatsApp` interface; the rest of the codebase never imports provider-specific code directly
- Conversation state splits into two stores: persistent (SQLite via SQLAlchemy async for message history) and ephemeral (in-memory dict in `session.py` for properties shown in the current session)
- CRM integration (GoHighLevel) lives in a dedicated module (`agent/ghl.py`) and is called both from `agent/tools.py` (lead creation during conversation) and directly from `agent/main.py` (pipeline stage advancement on appointment booking)

## Layers

**HTTP / Entry Layer:**
- Purpose: Receive inbound webhooks from WhatsApp provider and GHL; validate and route
- Location: `agent/main.py`
- Contains: FastAPI app, `webhook_handler` (POST /webhook), `ghl_webhook_handler` (POST /webhook/ghl), health check (GET /)
- Depends on: `agent/brain.py`, `agent/memory.py`, `agent/providers/`, `agent/ghl.py`
- Used by: External — Whapi.cloud webhook, GHL appointment webhook

**Provider Abstraction Layer:**
- Purpose: Normalize inbound messages from any WhatsApp provider into `MensajeEntrante`; send outbound responses as text, buttons, or interactive lists
- Location: `agent/providers/`
- Contains: `base.py` (abstract class + dataclasses), `whapi.py` (only active adapter), `__init__.py` (factory via `obtener_proveedor()`)
- Depends on: FastAPI `Request`, `httpx`
- Used by: `agent/main.py`

**Brain (AI Orchestration) Layer:**
- Purpose: Drive Claude API calls with tool_use loop; decide response type (text/buttons/list); handle image vision via base64
- Location: `agent/brain.py`
- Contains: `generar_respuesta()`, tool execution dispatcher `_ejecutar_herramienta()`, image downloader `_descargar_imagen_base64()`, interactive response builder `_construir_respuesta_interactiva()`
- Depends on: `agent/tools.py`, `agent/providers/base.py` (Respuesta dataclass), Anthropic SDK
- Used by: `agent/main.py`

**Tools Layer:**
- Purpose: Domain-specific actions called by Claude via tool_use — property search (web scraping with 10-min cache), lead registration, session-aware property list for scheduling
- Location: `agent/tools.py`
- Contains: `buscar_propiedades()`, `obtener_detalle_propiedad()`, `registrar_lead_ghl()`, `obtener_link_agendar()`, `obtener_propiedades_para_visita()`, `TOOLS_DEFINITION` (schema list passed to Anthropic API)
- Depends on: `agent/session.py`, `agent/ghl.py`, `agent/providers/base.py`, `httpx`
- Used by: `agent/brain.py`

**CRM Integration Layer:**
- Purpose: All GoHighLevel operations — upsert contacts, create/move opportunities, look up contacts by email/phone, generate pre-filled booking links
- Location: `agent/ghl.py`
- Contains: `crear_o_actualizar_contacto()`, `crear_oportunidad()`, `mover_oportunidad()`, `buscar_oportunidad_por_contacto()`, `obtener_detalles_oportunidad()`, `buscar_contacto_por_email()`, `buscar_contacto_por_telefono()`, `obtener_link_booking()`
- Depends on: `httpx`, env vars (`GHL_API_KEY`, `GHL_LOCATION_ID`, etc.)
- Used by: `agent/tools.py` (lead creation), `agent/main.py` (pipeline stage move on booking)

**Memory Layer:**
- Purpose: Persist conversation history per phone number across sessions; retrieve last N messages as context for Claude
- Location: `agent/memory.py`
- Contains: `Mensaje` SQLAlchemy model, `inicializar_db()`, `guardar_mensaje()`, `obtener_historial()`, `limpiar_historial()`
- Depends on: SQLAlchemy async, aiosqlite (dev) or asyncpg (prod)
- Used by: `agent/main.py`

**Session Cache Layer:**
- Purpose: In-memory ephemeral state per conversation — stores which properties were shown so the user can later pick one for a visit
- Location: `agent/session.py`
- Contains: `guardar_propiedades()`, `obtener_propiedades()`, `limpiar_cache_expirado()` — in-memory dict with 2-hour TTL
- Depends on: nothing (stdlib only)
- Used by: `agent/tools.py`

**Configuration Layer:**
- Purpose: Business identity and AI persona, loaded at runtime from YAML; system prompt cached in-memory after first read
- Location: `config/business.yaml`, `config/prompts.yaml`
- Contains: business name, address, hours, agent persona, full system prompt, fallback/error messages
- Depends on: nothing (read by `agent/brain.py` and `agent/tools.py`)
- Used by: `agent/brain.py`, `agent/tools.py`

## Data Flow

**Inbound WhatsApp Message:**

1. Whapi.cloud POSTs to `POST /webhook` in `agent/main.py`
2. `proveedor.parsear_webhook(request)` normalizes payload into `list[MensajeEntrante]` — handles text, buttons, lists, images
3. `main.py` builds a context string injecting internal metadata (phone number, new/returning client flag, interaction type) that Claude must not surface to the user
4. `obtener_historial(telefono)` fetches up to 6 prior messages from SQLite
5. `generar_respuesta(contexto, historial)` in `agent/brain.py`:
   - First Claude call with `ALL_TOOLS` (domain tools + interactive tools)
   - If `stop_reason == "tool_use"`: execute each tool via `_ejecutar_herramienta()`
   - If tool result is a `Respuesta` (interactive), return immediately with that UI element
   - Otherwise: second Claude call with only `INTERACTIVE_TOOLS` to allow post-search buttons/lists
6. Returns `Respuesta` object (tipo: texto | botones | lista)
7. `guardar_mensaje()` called twice: user message + assistant response persisted to SQLite
8. `proveedor.enviar_respuesta(telefono, respuesta)` routes to `enviar_mensaje`, `enviar_botones`, or `enviar_lista` depending on type

**GHL Appointment Booking Webhook:**

1. GHL POSTs to `POST /webhook/ghl` in `agent/main.py`
2. Contact identified via `contact_id`, email, or phone (fallback lookups via `agent/ghl.py`)
3. `buscar_oportunidad_por_contacto()` finds open pipeline opportunity
4. `obtener_detalles_oportunidad()` fetches property address and link from custom fields
5. `mover_oportunidad(opp_id, "visita_agendada")` advances CRM stage
6. WhatsApp confirmation sent to client via `proveedor.enviar_mensaje()`
7. Emails (client confirmation + vendor notification) dispatched via n8n webhook (`N8N_EMAIL_WEBHOOK`)

**State Management:**
- Persistent conversation history: SQLite table `mensajes` (phone, role, content, timestamp) — survives restarts
- In-session property cache: Python dict in `agent/session.py` — lost on restart, 2-hour TTL per phone
- System prompt: in-memory dict `_config_cache` in `agent/brain.py` — loaded once from `config/prompts.yaml`, never reloaded without restart
- Property listing cache: module-level list `_propiedades_cache` in `agent/tools.py` — refreshed every 10 minutes via web scrape

## Key Abstractions

**`MensajeEntrante` (dataclass):**
- Purpose: Normalized inbound message regardless of provider
- Location: `agent/providers/base.py`
- Fields: `telefono`, `texto`, `mensaje_id`, `es_propio`, `boton_id`, `lista_id`, `imagen_url`, `imagen_mime`

**`Respuesta` (dataclass):**
- Purpose: Typed outbound response that can carry text, buttons, or interactive list
- Location: `agent/providers/base.py`
- Fields: `tipo` (texto|botones|lista), `texto`, `botones: list[Boton]`, `texto_boton_lista`, `secciones: list[SeccionLista]`

**`ProveedorWhatsApp` (ABC):**
- Purpose: Interface contract all WhatsApp adapters must fulfill
- Location: `agent/providers/base.py`
- Abstract methods: `parsear_webhook()`, `enviar_mensaje()`
- Default implementations: `enviar_botones()`, `enviar_lista()`, `enviar_respuesta()`, `enviar_indicador_tipeo()`

**`TOOLS_DEFINITION` + `INTERACTIVE_TOOLS` (lists):**
- Purpose: Anthropic tool_use schemas passed to Claude; define callable domain actions and UI-generating actions separately
- Location: `agent/tools.py` (domain tools), `agent/brain.py` (interactive tools)
- Pattern: JSON Schema objects with `name`, `description`, `input_schema`

## Entry Points

**FastAPI application:**
- Location: `agent/main.py` — `app = FastAPI(...)`
- Start command: `uvicorn agent.main:app --reload --port 8000`
- Init: `lifespan()` context manager calls `inicializar_db()` on startup
- Routes: `GET /`, `GET /webhook`, `POST /webhook`, `POST /webhook/ghl`

**Test runner (local chat simulator):**
- Location: `tests/test_local.py`
- Triggers: `python tests/test_local.py`
- Responsibilities: Terminal REPL simulating client messages, calls `generar_respuesta()` and `guardar_mensaje()` directly

**Automated flow tests:**
- Location: `tests/test_flows.py`
- Triggers: `python tests/test_flows.py [--flow <name>] [--verbose]`
- Responsibilities: Multi-turn conversation simulations asserting expected response patterns

**Docker entry:**
- Location: `Dockerfile`
- Command: `uvicorn agent.main:app --host 0.0.0.0 --port 8000`

## Error Handling

**Strategy:** Catch-and-log with graceful fallback — never propagate errors to the WhatsApp client

**Patterns:**
- `agent/brain.py`: `generar_respuesta()` wraps entire Claude call in `try/except`, returns `obtener_mensaje_error()` string on any failure
- `agent/main.py` `webhook_handler`: outer `try/except` raises `HTTPException(500)` so the WhatsApp provider gets a 5xx and may retry
- `agent/main.py` `ghl_webhook_handler`: returns `{"status": "error"}` JSON (not 500) to avoid GHL retry loops
- All `agent/ghl.py` functions: return `{}`, `None`, or `False` on failure — callers check these sentinel values
- Provider adapters: button/list send failures fall back to plain text via `super().enviar_botones()` / `super().enviar_lista()`
- Full tracebacks logged via `traceback.format_exc()` at `ERROR` level in all critical paths

## Cross-Cutting Concerns

**Logging:** `logging.getLogger("agentkit")` used throughout; level set to `DEBUG` in development, `INFO` in production via `ENVIRONMENT` env var

**Validation:** Phone number normalization for Argentina (+549 → +54) done in both `agent/ghl.py` and `agent/main.py` GHL webhook handler — two independent implementations

**Authentication:** No auth on public webhook endpoints (rely on secret URL obscurity); GHL calls authenticated via `Bearer {GHL_API_KEY}` header; Whapi calls via `Bearer {WHAPI_TOKEN}`

**Configuration loading:** YAML files read at first function call then cached in module-level variables; no hot-reload — requires server restart for prompt/business config changes

---

*Architecture analysis: 2026-03-27*
