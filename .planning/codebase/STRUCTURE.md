# Codebase Structure

**Analysis Date:** 2026-03-27

## Directory Layout

```
whatsapp-agentkit/
├── agent/                      # Core application package
│   ├── __init__.py
│   ├── main.py                 # FastAPI app + all webhook routes
│   ├── brain.py                # Claude API orchestration + tool_use loop
│   ├── memory.py               # SQLAlchemy async — persistent conversation history
│   ├── session.py              # In-memory ephemeral state (properties shown per session)
│   ├── tools.py                # Domain tools called by Claude (search, lead reg, booking)
│   ├── ghl.py                  # GoHighLevel CRM integration (contacts, opportunities, pipeline)
│   ├── email_service.py        # SMTP email notifications (Microsoft 365) — currently unused in prod
│   └── providers/              # WhatsApp provider abstraction layer
│       ├── __init__.py         # Factory: obtener_proveedor() reads WHATSAPP_PROVIDER
│       ├── base.py             # Abstract class + MensajeEntrante/Respuesta/Boton dataclasses
│       └── whapi.py            # Active adapter: Whapi.cloud (text, buttons, lists, images)
├── config/                     # Runtime configuration (YAML — not code)
│   ├── business.yaml           # Business identity: name, address, hours, agent persona
│   └── prompts.yaml            # System prompt + fallback/error messages
├── knowledge/                  # Business knowledge files for ingestion into system prompt
│   └── .gitkeep
├── tests/
│   ├── __init__.py
│   ├── test_local.py           # Interactive terminal chat simulator
│   ├── test_flows.py           # Automated multi-turn conversation flow tests
│   └── TEST_PLAN.md            # Manual QA checklist
├── .planning/
│   └── codebase/               # GSD codebase analysis documents
├── .tmp/                       # Disposable scratch files (not committed)
├── .claude/                    # Claude Code settings
├── agentkit.db                 # SQLite database (dev — not committed)
├── .env                        # Active secrets (never committed)
├── .env.example                # Template for required env vars
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Production image
├── docker-compose.yml          # Local Docker orchestration
├── start.sh                    # Bootstrap script (checks Python + Claude Code)
├── CLAUDE.md                   # AgentKit onboarding instructions for Claude Code
├── README.md
└── LICENSE
```

## Directory Purposes

**`agent/`:**
- Purpose: Entire application logic — HTTP server, AI orchestration, CRM, memory, providers
- Key files: `main.py` (entry point), `brain.py` (AI layer), `tools.py` (domain actions), `ghl.py` (CRM)

**`agent/providers/`:**
- Purpose: Isolate WhatsApp provider API differences; rest of codebase only imports from `base.py`
- Key files: `base.py` (ABC + shared dataclasses), `whapi.py` (only deployed adapter)
- Adding a new provider: create `agent/providers/meta.py` or `agent/providers/twilio.py` implementing `ProveedorWhatsApp`, register in `__init__.py`

**`config/`:**
- Purpose: Declarative runtime configuration — change business behavior without touching code
- Key files: `prompts.yaml` (system prompt drives all AI behavior), `business.yaml` (structured business data)
- Note: `brain.py` caches `prompts.yaml` in memory — server restart required after edits

**`knowledge/`:**
- Purpose: Drop-in business documents (PDF, TXT, CSV, MD) referenced by tools for FAQ lookup
- Currently: empty (`.gitkeep` only) — content intentionally excluded from git
- Usage: `buscar_en_knowledge()` in `agent/tools.py` does substring search across all files here

**`tests/`:**
- Purpose: Local development testing without real WhatsApp connection
- `test_local.py`: human-in-the-loop terminal chat
- `test_flows.py`: automated assertions over multi-turn scenarios

**`.tmp/`:**
- Purpose: Scratch files from development sessions — disposable, ignored by git
- Contains: n8n workflow update scripts, JSON payload samples

## Key File Locations

**Entry Points:**
- `agent/main.py`: FastAPI app — all routes defined here
- `start.sh`: User-facing bootstrap (checks Python 3.11+, Claude Code)
- `Dockerfile` / `docker-compose.yml`: Production container config

**Configuration:**
- `config/prompts.yaml`: System prompt and fallback messages — primary lever for AI behavior tuning
- `config/business.yaml`: Structured business metadata
- `.env.example`: Canonical list of all required environment variables
- `agent/ghl.py` lines 20–50: Hardcoded GHL pipeline/stage IDs and custom field IDs

**Core Logic:**
- `agent/brain.py`: `generar_respuesta()` — the central function driving Claude + tool_use
- `agent/tools.py`: `TOOLS_DEFINITION` list — schemas exposed to Claude; `buscar_propiedades()` — scrapes and filters live property data
- `agent/ghl.py`: `crear_o_actualizar_contacto()`, `crear_oportunidad()` — CRM write path; `mover_oportunidad()` — pipeline stage transitions

**Data Models:**
- `agent/memory.py`: `Mensaje` — only SQLAlchemy model (table: `mensajes`)
- `agent/providers/base.py`: `MensajeEntrante`, `Respuesta`, `Boton`, `FilaLista`, `SeccionLista` — all shared dataclasses

**Testing:**
- `tests/test_local.py`: run with `python tests/test_local.py`
- `tests/test_flows.py`: run with `python tests/test_flows.py [--flow <name>]`

## Naming Conventions

**Files:**
- Snake_case, Spanish nouns for modules: `brain.py`, `memory.py`, `session.py`, `email_service.py`
- Provider adapters named after service: `whapi.py`, `meta.py` (not yet created), `twilio.py` (not yet created)

**Directories:**
- Lowercase, singular: `agent/`, `config/`, `knowledge/`, `tests/`

**Functions:**
- Snake_case, Spanish verbs: `generar_respuesta()`, `guardar_mensaje()`, `obtener_historial()`, `parsear_webhook()`, `enviar_mensaje()`
- Private helpers prefixed with `_`: `_get_config()`, `_headers()`, `_ejecutar_herramienta()`, `_construir_respuesta_interactiva()`

**Classes:**
- PascalCase, Spanish nouns: `ProveedorWhatsApp`, `ProveedorWhapi`, `MensajeEntrante`, `Respuesta`, `Mensaje`

**Constants:**
- UPPER_SNAKE_CASE: `BASE_URL`, `CACHE_TTL`, `PIPELINE_ID`, `STAGES`, `TOOLS_DEFINITION`, `MODEL`

**Variables:**
- Snake_case, Spanish: `todas`, `historial`, `telefono`, `proveedor`, `respuesta`

**Logger:**
- Single shared logger across all modules: `logging.getLogger("agentkit")`

## Where to Add New Code

**New Claude-callable tool (domain action):**
1. Implement async function in `agent/tools.py`
2. Add entry to `TOOLS_DEFINITION` list in `agent/tools.py` with name, description, input_schema
3. Add dispatch case in `_ejecutar_herramienta()` in `agent/brain.py`
4. Update system prompt in `config/prompts.yaml` to describe when Claude should use the new tool

**New interactive UI tool (buttons or lists):**
1. Add entry to `INTERACTIVE_TOOLS` list in `agent/brain.py`
2. Add dispatch case in `_ejecutar_herramienta()` using `_construir_respuesta_interactiva()`
3. The `Respuesta` dataclass already handles the output — no provider changes needed

**New WhatsApp provider:**
1. Create `agent/providers/<name>.py` implementing `ProveedorWhatsApp` from `agent/providers/base.py`
2. Register in `agent/providers/__init__.py` factory (`obtener_proveedor()`)
3. Set `WHATSAPP_PROVIDER=<name>` in `.env`

**New CRM operation:**
1. Add async function to `agent/ghl.py` using `_headers()` for auth and `httpx.AsyncClient`
2. Call from either `agent/tools.py` (if triggered by Claude) or `agent/main.py` (if triggered by webhook)

**New webhook endpoint:**
1. Add route in `agent/main.py` — follow existing pattern of try/except with full traceback logging
2. Return `{"status": "ok"}` on success, never raise exceptions in GHL-style webhooks to avoid retry loops

**New configuration key:**
1. Add to `config/prompts.yaml` (AI-facing) or `config/business.yaml` (business data)
2. Read via `_get_config()` in `agent/brain.py` or `cargar_info_negocio()` in `agent/tools.py`
3. Values are cached after first read — restart server after changes

**New environment variable:**
1. Add to `.env.example` with comment explaining source and format
2. Read with `os.getenv("VAR_NAME", default)` — never import `.env` directly

## Special Directories

**`.planning/`:**
- Purpose: GSD methodology artifacts (codebase analysis, project plans, roadmaps)
- Generated: By GSD commands
- Committed: Yes

**`.tmp/`:**
- Purpose: Scratch files, debug payloads, one-off scripts
- Generated: Manually during development
- Committed: No (in `.gitignore`)

**`knowledge/`:**
- Purpose: Business documents for FAQ/search functionality
- Generated: Manually uploaded by user
- Committed: No (in `.gitignore`, only `.gitkeep` committed)

**`agent/providers/__pycache__/`, `agent/__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Automatically by Python
- Committed: No

---

*Structure analysis: 2026-03-27*
