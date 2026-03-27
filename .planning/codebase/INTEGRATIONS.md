# External Integrations

**Analysis Date:** 2026-03-27

## APIs & External Services

**AI / LLM:**
- Anthropic Claude API — AI brain for all responses, tool use orchestration, and image vision
  - SDK/Client: `anthropic>=0.40.0` via `AsyncAnthropic` in `agent/brain.py`
  - Auth: `ANTHROPIC_API_KEY`
  - Model: `claude-haiku-4-5-20251001` (default, overridable via `CLAUDE_MODEL`)
  - Usage: Two-call tool use loop. First call may return `tool_use`; second call formats final response. Supports multimodal (base64 images from Whapi)

**WhatsApp Provider:**
- Whapi.cloud — Sole active WhatsApp provider (only `whapi.py` exists in `agent/providers/`)
  - SDK/Client: REST via `httpx` in `agent/providers/whapi.py`
  - Auth: `WHAPI_TOKEN` (Bearer token)
  - Base URL: `https://gate.whapi.cloud`
  - Endpoints used:
    - `POST /messages/text` — plain text messages
    - `POST /messages/interactive` — buttons and list menus
    - `PUT /presences/{telefono}` — typing indicator
  - Note: `WHATSAPP_PROVIDER` env var selects provider. Factory in `agent/providers/__init__.py` also supports `meta` and `twilio` (adapter stubs are not present in repo, only `whapi.py` is implemented)

**GoHighLevel (GHL) CRM:**
- Used for contact management, sales pipeline, opportunity tracking, and appointment booking
  - SDK/Client: REST via `httpx` in `agent/ghl.py`
  - Auth: `GHL_API_KEY` (Bearer token), API version `2021-07-28`
  - Base URL: `https://services.leadconnectorhq.com`
  - Endpoints used:
    - `POST /contacts/upsert` — create or update contacts by phone
    - `GET /contacts/` — search contacts by email or phone
    - `POST /opportunities/` — create new opportunity in pipeline
    - `PUT /opportunities/{id}` — move opportunity to pipeline stage
    - `GET /opportunities/search` — find opportunities by contact
    - `GET /opportunities/{id}` — fetch opportunity custom fields
  - Location ID: `GHL_LOCATION_ID` (default hardcoded: `TdZdFVt3WVzL6OoSX7iQ`)
  - Pipeline: `mld8sxsQ9YaNUEOxcw6M` with stages: `lead_nuevo`, `contactado_bot`, `visita_agendada`, `visita_realizada`, `negociacion`, `cerrado_ganado`, `cerrado_perdido`
  - Calendar booking widget: `https://api.leadconnectorhq.com/widget/booking/lHxMCC26XkVuh8bSVCYz`
  - Custom fields tracked: `operacion`, `tipo_propiedad`, `zona`, `vendedor` on contacts; `propiedad_id`, `propiedad_link`, `propiedad_direccion`, `resumen` on opportunities

**Real Estate Property Listing (Inmobiliaria Bertero website):**
- HTML scraping of `https://www.inmobiliariabertero.com.ar/Propiedades` — no API key
  - SDK/Client: `httpx` in `agent/tools.py`
  - Scrapes up to 4 pages of listings (80 properties max)
  - Cache TTL: 10 minutes in-memory (`_propiedades_cache`)
  - Also scrapes individual property detail pages at `/p/{id}-{slug}`
  - Filtering done client-side: type, zone, operation, price range, rooms

**n8n Automation Platform:**
- Self-hosted n8n on EasyPanel, used for email dispatch after appointment booking
  - Endpoint: `N8N_EMAIL_WEBHOOK` (default: `https://n8n-n8n.bacu5y.easypanel.host/webhook/agentkit-send-emails`)
  - Auth: None (open webhook URL)
  - Triggered from: `agent/main.py` in `/webhook/ghl` handler
  - Payload: customer name, emails, phone, property details, appointment datetime, Zoom link, appointment type
  - Also referenced: `N8N_ERROR_WEBHOOK` in `agent/tools.py` for error reporting

## Data Storage

**Databases:**
- SQLite (development/local)
  - Connection: `DATABASE_URL` (default: `sqlite+aiosqlite:///./agentkit.db`)
  - Client: SQLAlchemy async ORM + aiosqlite driver
  - Schema: single `mensajes` table with columns `id`, `telefono`, `role`, `content`, `timestamp`
  - File: `agentkit.db` in project root (committed to repo — contains test data)

- PostgreSQL (production)
  - Connection: `DATABASE_URL` starting with `postgresql://` — auto-converted to `postgresql+asyncpg://`
  - Client: SQLAlchemy async ORM + asyncpg driver (not in requirements.txt — must be added for production)
  - Provided by Railway as add-on

**In-Memory Cache:**
- Session property cache in `agent/session.py` — dict keyed by phone number, 2-hour TTL
- System prompt cache in `agent/brain.py` — loaded once from `config/prompts.yaml`, never invalidated without restart

**File Storage:**
- Local filesystem: `knowledge/` directory for business documents (PDFs, TXT, CSV, MD, JSON)
- Mounted as Docker volume in `docker-compose.yml`

**Caching:**
- In-process Python dicts only (no Redis or external cache)

## Authentication & Identity

**Auth Provider:**
- None (custom)
  - Webhooks are unauthenticated POST endpoints — no signature validation on `/webhook` or `/webhook/ghl`
  - GHL webhook `/webhook/ghl` relies on GHL knowing the URL (security through obscurity)
  - Whapi.cloud webhook: no signature verification implemented

## Email

**SMTP Provider:**
- Microsoft 365 (smtp.office365.com:587 with STARTTLS)
  - Implementation: `agent/email_service.py` — synchronous `smtplib`
  - Auth vars: `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
  - Note: `email_service.py` exists but is NOT called from `main.py`. Emails are delegated to n8n webhook instead. This module is unused/legacy.

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry or equivalent)

**Logs:**
- Python `logging` module, level `DEBUG` in development, `INFO` in production
- Logger name: `agentkit`
- Full traceback logged on webhook exceptions via `traceback.format_exc()`
- Error webhook to n8n (`N8N_ERROR_WEBHOOK`) referenced in `agent/tools.py` — not implemented as active alerting

## CI/CD & Deployment

**Hosting:**
- Railway (primary) — one-click deploy from GitHub, env vars set in Railway dashboard
- EasyPanel — hosts n8n instance used for email automation

**CI Pipeline:**
- None detected

## Webhooks & Callbacks

**Incoming:**
- `POST /webhook` — receives WhatsApp messages from Whapi.cloud
- `GET /webhook` — Meta Cloud API verification challenge (passthrough, returns 200 for Whapi)
- `POST /webhook/ghl` — receives appointment events from GoHighLevel (cita agendada/confirmada)

**Outgoing:**
- Whapi.cloud API — sends WhatsApp messages and typing indicators
- GHL API — creates/updates contacts and opportunities, fetches data
- n8n webhook — triggers email notifications on appointment booking

## Environment Configuration

**Required env vars:**
```
ANTHROPIC_API_KEY        # Anthropic API key (sk-ant-...)
WHAPI_TOKEN              # Whapi.cloud bearer token
GHL_API_KEY              # GoHighLevel API key
GHL_LOCATION_ID          # GHL location/subaccount ID
WHATSAPP_PROVIDER        # "whapi" | "meta" | "twilio"
PORT                     # Server port (default: 8000)
ENVIRONMENT              # "development" | "production"
DATABASE_URL             # SQLite or PostgreSQL URL
```

**Optional env vars:**
```
CLAUDE_MODEL             # Claude model ID (default: claude-haiku-4-5-20251001)
N8N_EMAIL_WEBHOOK        # n8n webhook URL for emails
N8N_ERROR_WEBHOOK        # n8n webhook URL for error alerts
VENDEDOR_EMAIL           # Sales rep email for notifications
ADMIN_EMAIL              # Admin email for error alerts
SMTP_HOST                # SMTP server (default: smtp.office365.com)
SMTP_PORT                # SMTP port (default: 587)
SMTP_USER                # SMTP username
SMTP_PASSWORD            # SMTP password
SMTP_FROM                # From address for emails
```

**Secrets location:**
- `.env` file in project root (not committed — present in `.gitignore`)
- `.env.example` present as template reference

---

*Integration audit: 2026-03-27*
