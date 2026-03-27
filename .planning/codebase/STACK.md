# Technology Stack

**Analysis Date:** 2026-03-27

## Languages

**Primary:**
- Python 3.11+ - All application code, agent logic, API server

**Secondary:**
- Bash - `start.sh` setup/verification script

## Runtime

**Environment:**
- Python 3.11+ (enforced in `start.sh` and `Dockerfile`)

**Package Manager:**
- pip (no version pinned)
- Lockfile: absent — only `requirements.txt` with `>=` version constraints

## Frameworks

**Core:**
- FastAPI `>=0.104.0` - HTTP server, webhook endpoints (`agent/main.py`)
- Uvicorn `[standard] >=0.24.0` - ASGI server, production runner

**Database ORM:**
- SQLAlchemy `>=2.0.0` - Async ORM for conversation memory (`agent/memory.py`)
- aiosqlite `>=0.19.0` - Async SQLite driver (local dev)

**AI / LLM:**
- Anthropic SDK `>=0.40.0` - Claude API client with tool use and vision (`agent/brain.py`)

**HTTP Client:**
- httpx `>=0.25.0` - Async HTTP for all external API calls (Whapi, GHL, n8n, property scraping)

**Config / Utilities:**
- python-dotenv `>=1.0.0` - `.env` loading in every module
- PyYAML `>=6.0.1` - Reading `config/prompts.yaml` and `config/business.yaml`
- python-multipart `>=0.0.6` - Form data parsing (Twilio webhook format)

**Build/Dev:**
- Docker + Docker Compose - Containerization (`Dockerfile`, `docker-compose.yml`)

## Key Dependencies

**Critical:**
- `anthropic>=0.40.0` - Core AI brain. Uses `AsyncAnthropic` with `client.messages.create()`, tool use loop, and vision (base64 image). Model selectable via `CLAUDE_MODEL` env var, default `claude-haiku-4-5-20251001`
- `fastapi>=0.104.0` - Exposes `/webhook` (POST/GET), `/webhook/ghl` (POST), and `/` health check
- `sqlalchemy>=2.0.0` + `aiosqlite` - Persists conversation history per phone number in `agentkit.db`
- `httpx>=0.25.0` - All outbound HTTP: Whapi.cloud, GHL CRM, n8n webhook, real estate site scraping

**Infrastructure:**
- `uvicorn[standard]>=0.24.0` - Production ASGI server
- `python-dotenv>=1.0.0` - Used at module level in every file with `load_dotenv()`
- `pyyaml>=6.0.1` - System prompt and business config loaded from YAML

## Configuration

**Environment:**
- All secrets and config via `.env` file (loaded by `python-dotenv`)
- `.env.example` present as reference template
- Required variables: `ANTHROPIC_API_KEY`, `WHAPI_TOKEN`, `GHL_API_KEY`, `GHL_LOCATION_ID`, `WHATSAPP_PROVIDER`, `PORT`, `ENVIRONMENT`, `DATABASE_URL`
- Optional variables: `CLAUDE_MODEL`, `N8N_EMAIL_WEBHOOK`, `N8N_ERROR_WEBHOOK`, `VENDEDOR_EMAIL`, `ADMIN_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`

**Build:**
- `Dockerfile` — `python:3.11-slim`, installs deps, exposes port 8000, runs uvicorn
- `docker-compose.yml` — mounts `./knowledge` and `./config` as volumes, reads `.env` file

**Agent Config:**
- `config/prompts.yaml` — system prompt, fallback/error messages, cached in memory on first load
- `config/business.yaml` — business name, description, hours, agent persona

## Platform Requirements

**Development:**
- Python 3.11+
- Claude Code CLI (`claude`) — referenced in `start.sh` for onboarding
- Docker Desktop (optional, for container testing)

**Production:**
- Railway (primary deploy target, referenced in `CLAUDE.md` and `start.sh`)
- EasyPanel with n8n self-hosted (email webhook: `n8n-n8n.bacu5y.easypanel.host`)
- PostgreSQL (Railway add-on) replaces SQLite in production — URL auto-detected by prefix in `agent/memory.py`

---

*Stack analysis: 2026-03-27*
