# Phase 2: Supabase Data Foundation - Research

**Researched:** 2026-03-28
**Domain:** Web scraping (Bertero detail pages) + Supabase Python SDK + FastAPI cache warm-up + n8n hourly refresh
**Confidence:** HIGH

---

## Summary

Phase 2 replaces the current live-scraping approach in `tools.py` (which hits the Bertero website on
every cache miss, taking 2-5 seconds per request) with a Supabase-backed property store. The
architecture has four clear layers: (1) a deep scraper that fetches both listing and detail pages to
extract full property data, (2) a Supabase table storing normalized property records, (3) the bot
querying Supabase via the Python SDK (< 1 second), and (4) an n8n workflow refreshing data hourly.

The existing `agent/tools.py` already has a functioning scraper for listing pages
(`_parsear_listado`) and detail pages (`_parsear_detalle`). Both use `re` (regex) for extraction
rather than BeautifulSoup, and they work well because the Bertero site HTML is structured HTML with
stable CSS IDs (`#lista_informacion_basica`, `#lista_superficies`). The deep scraper for Plan 02-01
is therefore an extension of the existing scraper — not a rewrite. The key delta is: the existing
scraper never persists data; this phase persists to Supabase.

For Supabase integration, `supabase-py` 2.28.3 (released March 20, 2026) is the standard SDK.
The sync client (`create_client`) is sufficient for use inside FastAPI because all Supabase calls
in this codebase will run inside async def endpoints (awaitable via `await ... .execute()`). The
async client (`acreate_client`) adds complexity without clear benefit for this use case — the sync
client works in async context via the underlying httpx transport.

**Primary recommendation:** Extend the existing scraper to persist to Supabase, build a thin
`agent/supabase_client.py` module for DB access, replace the two-function scraping path in
`buscar_propiedades` and `obtener_detalle_propiedad` with Supabase queries, warm up a module-level
list on startup in main.py's `lifespan`, and build the n8n workflow as a Schedule Trigger + HTTP
Code node (not the Supabase n8n node, which lacks upsert) calling the Supabase REST API.

---

## Standard Stack

### Core (already in requirements.txt — no new installs needed for scraping)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | >=0.25.0 | HTTP client for scraper | Already in use |
| re | stdlib | HTML parsing for Bertero pages | Already works; Bertero's HTML has stable IDs |
| python-dotenv | >=1.0.0 | SUPABASE_URL/SUPABASE_KEY env vars | Already in use |

### New Dependencies
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| supabase | 2.28.3 | Python SDK for Supabase DB queries | Plans 02-02 and 02-03 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| supabase-py sync client | supabase-py async (`acreate_client`) | Async client is needed ONLY for Realtime subscriptions; for CRUD queries the sync client awaitable pattern is simpler and official |
| supabase-py | Direct psycopg2/asyncpg to Supabase Postgres | psycopg2 requires SSL config and pooler port management; supabase-py handles this transparently |
| supabase-py | SQLAlchemy pointing at Supabase Postgres | Would work but loses the SDK ergonomics; also SQLAlchemy is already used for SQLite conversations — mixing engines for different concerns is fine but adds complexity |
| re (regex) for HTML parsing | BeautifulSoup4 | bs4 is cleaner for complex HTML; Bertero's HTML has stable `#lista_informacion_basica` and `#lista_superficies` IDs so regex is sufficient. Adding bs4 is a new dep with no benefit here. |

**Installation:**
```bash
pip install supabase==2.28.3
```

---

## Architecture Patterns

### Recommended Project Structure (additions/changes only)
```
agent/
├── supabase_client.py   # NEW — Supabase client singleton + query helpers
├── scraper.py           # NEW — deep scraper (listing + detail pages, batch persist)
├── tools.py             # MODIFIED — buscar_propiedades + obtener_detalle read from Supabase
├── main.py              # MODIFIED — lifespan warm-up from Supabase on startup
└── session.py           # UNCHANGED — per-user property cache for visita flow
```

### Pattern 1: Supabase Client Module (supabase_client.py)

**What:** A module-level singleton that initializes the Supabase client once and exposes typed
query helpers. All other modules import from here.

**When to use:** Every time the bot or scraper touches the `propiedades` table.

```python
# Source: supabase.com/docs/reference/python/initializing
import os
from supabase import create_client, Client

_client: Client | None = None

def get_supabase() -> Client:
    """Returns the singleton Supabase client. Initializes on first call."""
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


async def buscar_propiedades_db(
    tipo: str = "",
    operacion: str = "",
    zona: str = "",
    precio_min: int = 0,
    precio_max: int = 0,
    limite: int = 5,
    offset: int = 0,
) -> list[dict]:
    """Query propiedades from Supabase with filters."""
    sb = get_supabase()
    query = sb.table("propiedades").select("*")
    if tipo:
        query = query.ilike("tipo", f"%{tipo}%")
    if operacion:
        query = query.eq("operacion", operacion)
    if zona:
        query = query.ilike("zona", f"%{zona}%")
    if precio_min:
        query = query.gte("precio_num", precio_min)
    if precio_max:
        query = query.lte("precio_num", precio_max)
    query = query.range(offset, offset + limite - 1)
    response = await query.execute()
    return response.data or []


async def upsert_propiedades(propiedades: list[dict]) -> int:
    """Bulk upsert — insert or update by propiedad_id."""
    sb = get_supabase()
    # on_conflict="propiedad_id" means: if the ID exists, UPDATE; if not, INSERT
    response = await sb.table("propiedades").upsert(
        propiedades,
        on_conflict="propiedad_id",
    ).execute()
    return len(response.data or [])
```

### Pattern 2: Supabase Table Schema

**What:** A single `propiedades` table with all scraped fields, a `propiedad_id` unique key
(the numeric ID from the Bertero URL slug), and a `scraped_at` timestamp for detecting staleness.

**SQL (run once in Supabase SQL Editor):**
```sql
-- Source: verified from Bertero HTML inspection (2026-03-28)
CREATE TABLE IF NOT EXISTS propiedades (
    id              BIGSERIAL PRIMARY KEY,
    propiedad_id    TEXT UNIQUE NOT NULL,    -- e.g. "7778974"
    link            TEXT NOT NULL,           -- e.g. "/p/7778974-..."
    tipo            TEXT,                    -- "departamento", "casa", etc.
    operacion       TEXT,                    -- "venta", "alquiler"
    zona            TEXT,
    direccion       TEXT,
    precio          TEXT,                    -- "USD 55.000" (display string)
    precio_num      INTEGER DEFAULT 0,       -- 55000 (for range filtering)
    superficie      TEXT,                    -- from listing page
    ambientes       INTEGER,
    dormitorios     INTEGER,
    banos           INTEGER,
    sup_cubierta    TEXT,                    -- from detail page
    sup_total       TEXT,                    -- from detail page
    antiguedad      TEXT,
    expensas        TEXT,
    descripcion     TEXT,
    scraped_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Index for common filter patterns
CREATE INDEX IF NOT EXISTS idx_propiedades_operacion ON propiedades (operacion);
CREATE INDEX IF NOT EXISTS idx_propiedades_tipo ON propiedades (tipo);
CREATE INDEX IF NOT EXISTS idx_propiedades_precio ON propiedades (precio_num);
```

### Pattern 3: Deep Scraper (scraper.py)

**What:** Fetches all listing pages to get property IDs + basic data, then fetches each detail
page for the full data set. Persists via upsert to Supabase.

**Key insight from HTML inspection:**

Listing page: `#resultados-list li` cards. Price and superficie come from the HTML block between
consecutive `href="/p/ID-..."` anchors (existing `_parsear_listado` logic already handles this).

Detail page: Structured HTML with stable element IDs:
- `#lista_informacion_basica ul li` — contains "Ambientes : 2", "Dormitorios : 1", "Baños : 1",
  "Antigüedad : 36 Años", "Expensas : $ 109.000" as separate `<li>` elements
- `#lista_superficies ul li` — contains "Cubierta: 32 m²", "Total Construido: 40 m²"
- Price: plain text in page heading matching regex `(USD|U\$S)\s*[\d.,]+`
- Description: `div#prop-desc` or `class="prop-desc"`

**Extraction approach for detail page `#lista_informacion_basica`:**
```python
# Source: verified from live page inspection 2026-03-28
# Each <li> is "Key : Value" or "Key: Value"
import re

def _parsear_info_basica(html: str) -> dict:
    """Parses #lista_informacion_basica <li> items into a dict."""
    result = {}
    # Find the ul block
    bloque = re.search(r'id="lista_informacion_basica"[^>]*>(.*?)</ul>', html, re.DOTALL)
    if not bloque:
        return result
    lis = re.findall(r'<li>([^<]+)</li>', bloque.group(1))
    for li in lis:
        if ':' in li:
            key, _, val = li.partition(':')
            result[key.strip().lower()] = val.strip()
    return result

def _parsear_superficies(html: str) -> dict:
    """Parses #lista_superficies <li> items."""
    result = {}
    bloque = re.search(r'id="lista_superficies"[^>]*>(.*?)</ul>', html, re.DOTALL)
    if not bloque:
        return result
    lis = re.findall(r'<li>([^<]+)</li>', bloque.group(1))
    for li in lis:
        if ':' in li:
            key, _, val = li.partition(':')
            result[key.strip().lower()] = val.strip()
    return result
```

Confirmed `<li>` values from live page:
- `"ambientes : 2"` → key="ambientes", val="2"
- `"dormitorios : 1"` → key="dormitorios", val="1"
- `"baños : 1"` → key="baños", val="1"
- `"antigüedad : 36 años"` → key="antigüedad", val="36 años"
- `"expensas : $ 109.000"` → key="expensas", val="$ 109.000"
- `"cubierta: 79 m²"` → key="cubierta", val="79 m²"
- `"total construido: 358 m²"` → key="total construido", val="358 m²"

**Price from detail page:**
```python
# Detail page price is in the heading as plain text "USD65.000" or "USD 65.000"
# This price is the authoritative price (DATA-05)
precio_match = re.search(r'(USD|U\$S)\s*([\d.,]+)', detail_html)
```

### Pattern 4: Cache Warm-up in lifespan (main.py)

**What:** At server start, load all propiedades from Supabase into `_propiedades_cache` in
`tools.py`. This fulfills TECH-07 (warm cache on startup).

```python
# Source: FastAPI lifespan docs + supabase-py select pattern
# In agent/main.py
from agent.tools import cargar_cache_desde_supabase  # new function

@asynccontextmanager
async def lifespan(app: FastAPI):
    await inicializar_db()
    await cargar_cache_desde_supabase()  # NEW — warm-up (TECH-07)
    logger.info("Cache de propiedades cargado desde Supabase")
    yield

# In agent/tools.py
async def cargar_cache_desde_supabase():
    """Pre-loads all properties from Supabase into module-level cache."""
    global _propiedades_cache, _propiedades_cache_time
    import time
    from agent.supabase_client import get_supabase
    sb = get_supabase()
    response = await sb.table("propiedades").select("*").execute()
    if response.data:
        _propiedades_cache = response.data
        _propiedades_cache_time = time.time()
        logger.info(f"Cache warm-up: {len(_propiedades_cache)} propiedades cargadas")
```

### Pattern 5: n8n Hourly Refresh Workflow (Plan 02-04)

**What:** n8n Schedule Trigger runs every hour. For each Bertero listing page (up to 4 pages),
scrape + upsert to Supabase via HTTP Request node using the Supabase REST API directly.

**Why HTTP Request node, not Supabase n8n node:** The native Supabase n8n node does NOT support
upsert (only insert/get/delete). This is a known open feature request as of 2026. The HTTP Request
node calling Supabase's PostgREST REST API is the standard workaround.

**n8n Supabase REST upsert call:**
```
Method: POST
URL: https://<project_ref>.supabase.co/rest/v1/propiedades
Headers:
  apikey: <supabase_anon_key>
  Authorization: Bearer <supabase_anon_key>
  Content-Type: application/json
  Prefer: resolution=merge-duplicates
Query params: on_conflict=propiedad_id
Body: [array of property objects]
```

**Alternative (also valid):** Python script called from n8n Code node — call the Bertero scraper
logic (same Python code as scraper.py) and upsert directly. This is simpler but requires the Code
node to have httpx available, which n8n's Code node supports via `require('axios')` in JS or via
HTTP Request. Recommendation: keep the scraper logic in Python (called via n8n's Execute Command
node or via an HTTP endpoint on the FastAPI server) rather than reimplementing in JS.

**Simplest reliable n8n architecture for 02-04:**
```
Schedule Trigger (every 1 hour)
  → HTTP Request: POST https://<agent-url>/admin/refresh-properties
    (new FastAPI endpoint that triggers the Python scraper + upsert)
    Headers: X-Admin-Token: <secret>
```
This delegates all scraping logic to Python (where it already exists) and keeps n8n as a simple
scheduler. No JS scraping code duplication.

### Anti-Patterns to Avoid

- **Scraping detail pages in the bot's request path**: Never trigger a detail-page HTTP request
  when Claude calls `obtener_detalle_propiedad`. All detail data must already be in Supabase.
- **Using the Supabase n8n node for upsert**: It doesn't support upsert. Use HTTP Request node.
- **Loading properties from Supabase on each bot message**: Load once to module cache on startup;
  refresh from Supabase after each n8n refresh cycle.
- **Storing the service_role key in .env that goes to Railway**: Use the anon key for all bot
  operations. Service_role key only in n8n environment (for upsert via HTTP).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB connection pool | Custom connection manager | `supabase-py` create_client | SDK handles pooling, retries, and SSL |
| Upsert logic | Custom SELECT + INSERT/UPDATE | `supabase.table().upsert(on_conflict=...)` | SDK wraps PostgREST's native UPSERT |
| Pagination | Custom slice logic | `.range(offset, limit)` in supabase-py | Correct range semantics, handles edge cases |
| n8n upsert | Supabase n8n node | HTTP Request node with `Prefer: resolution=merge-duplicates` | Native node lacks upsert |
| HTML parsing of Bertero | Custom BS4 parser | Extend existing `_parsear_listado` / `_parsear_detalle` | Regex works; Bertero has stable IDs |

**Key insight:** The existing scraper regex code already handles most of the parsing. Phase 02-01
is an extension (add detail page field extraction using `#lista_informacion_basica`), not a rewrite.

---

## Common Pitfalls

### Pitfall 1: Price discrepancy (DATA-05 — critical requirement)

**What goes wrong:** The listing page price (shown in the HTML between property card links) can
differ from the detail page price. The detail page is authoritative (it's what the client sees).

**Why it happens:** The Bertero listing page shows a summary price that may be truncated or
formatted differently. The detail page shows the full formatted price in the `<h1>` or heading area.

**How to avoid:** In Plan 02-01, always scrape the detail page and use ITS price in the `precio`
field. Never persist listing-page prices as authoritative.

**Warning signs:** If `precio` from Supabase doesn't match what the user sees on the Bertero detail
URL, it came from the listing page instead of the detail page.

### Pitfall 2: supabase-py sync client in async context

**What goes wrong:** `create_client()` returns a sync client. Calling `.execute()` without `await`
works but blocks the event loop. Calling `await` on a sync execute returns the result correctly
because the underlying httpx transport is async-compatible.

**How to avoid:** Always `await` every `.execute()` call in this codebase (all endpoints are
`async def`). Do NOT use the sync client in a synchronous context (e.g., a non-async function).

**Pattern:**
```python
# CORRECT — in async def context
response = await sb.table("propiedades").select("*").execute()

# WRONG — blocks event loop
response = sb.table("propiedades").select("*").execute()
```

### Pitfall 3: Supabase environment variables naming collision

**What goes wrong:** The existing `requirements.txt` and codebase use `DATABASE_URL` for SQLite/
Postgres (SQLAlchemy). Supabase uses `SUPABASE_URL` and `SUPABASE_KEY`. These are different things
and must not be confused.

**How to avoid:**
```
DATABASE_URL      = sqlite+aiosqlite:///./agentkit.db   # SQLAlchemy (conversations)
SUPABASE_URL      = https://<project>.supabase.co       # Supabase SDK (properties)
SUPABASE_KEY      = eyJ...                               # Supabase anon key
```

### Pitfall 4: n8n calling Python scraper vs. scraping in JS

**What goes wrong:** Implementing the Bertero scraper logic in n8n's JavaScript Code node means
maintaining the same parsing logic in two places (Python + JS). HTML structure changes break both.

**How to avoid:** Plan 02-04 should expose a `/admin/refresh-properties` endpoint on the FastAPI
server. n8n's Schedule Trigger POSTs to that endpoint. All scraping logic stays in Python.

### Pitfall 5: Detail page scraping rate — blocking Bertero

**What goes wrong:** Fetching 80+ detail pages in sequence as fast as possible may trigger
rate limiting or a temporary IP block on Bertero's server.

**How to avoid:** In `scraper.py`, add `asyncio.sleep(0.5)` between detail page requests. The
n8n refresh runs hourly so total scraping time of ~60 seconds (80 pages * 0.5s) is acceptable.

### Pitfall 6: Cache invalidation after n8n refresh

**What goes wrong:** n8n upserts new data to Supabase but the bot's in-memory cache
(`_propiedades_cache` in tools.py) still holds the old data until the 10-minute TTL expires.

**How to avoid:** The `/admin/refresh-properties` endpoint (called by n8n) should reload the
module-level cache after completing the upsert. Or n8n can make a second call to a
`/admin/reload-cache` endpoint. This ensures the bot serves fresh data within seconds of the refresh.

---

## Code Examples

### Initialize Supabase client (singleton pattern)
```python
# Source: supabase.com/docs/reference/python/initializing (verified 2026-03-28)
import os
from supabase import create_client, Client

_supabase: Client | None = None

def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
    return _supabase
```

### Select with combined filters
```python
# Source: supabase.com/docs/reference/python/select (verified 2026-03-28)
response = await (
    sb.table("propiedades")
    .select("*")
    .eq("operacion", "venta")
    .ilike("zona", "%nueva cordoba%")
    .gte("precio_num", 50000)
    .lte("precio_num", 100000)
    .range(0, 4)           # first 5 results
    .execute()
)
propiedades = response.data  # list[dict]
```

### Bulk upsert by propiedad_id
```python
# Source: supabase.com/docs/reference/python/upsert (verified 2026-03-28)
batch = [
    {"propiedad_id": "7778974", "tipo": "departamento", "precio_num": 55000, ...},
    {"propiedad_id": "7803143", "tipo": "local", "precio_num": 65000, ...},
]
response = await (
    sb.table("propiedades")
    .upsert(batch, on_conflict="propiedad_id")
    .execute()
)
```

### Cache warm-up in FastAPI lifespan
```python
# Source: fastapi.tiangolo.com/advanced/events/ + pattern from this codebase
@asynccontextmanager
async def lifespan(app: FastAPI):
    await inicializar_db()          # existing
    await cargar_cache_propiedades()  # new — loads from Supabase
    logger.info("Propiedades cargadas en cache")
    yield
```

### Bertero detail page field extraction
```python
# Source: verified from live page inspection of inmobiliariabertero.com.ar 2026-03-28
# #lista_informacion_basica structure:
# <ul id="lista_informacion_basica">
#   <li>Ambientes : 2</li>
#   <li>Dormitorios : 1</li>
#   <li>Baños : 1</li>
#   <li>Antigüedad : 36 Años</li>
#   <li>Expensas : $ 109.000</li>
# </ul>
#
# #lista_superficies structure:
# <ul id="lista_superficies">
#   <li>Cubierta: 79 m²</li>
#   <li>Total Construido: 40 m²</li>
# </ul>

bloque = re.search(r'id="lista_informacion_basica"[^>]*>(.*?)</ul>', html, re.DOTALL)
if bloque:
    lis = re.findall(r'<li>([^<]+)</li>', bloque.group(1))
    info = {}
    for li in lis:
        if ':' in li:
            k, _, v = li.partition(':')
            info[k.strip().lower()] = v.strip()
    dormitorios = int(info.get("dormitorios", "0").split()[0]) if "dormitorios" in info else None
    banos       = int(info.get("baños", "0").split()[0])       if "baños" in info else None
    ambientes   = int(info.get("ambientes", "0").split()[0])   if "ambientes" in info else None
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Scraping listing + detail on every cache miss | Pre-scrape to Supabase; serve from cache | This phase | Response time 2-5s → <100ms |
| 10-min in-memory TTL cache | Supabase as source of truth; in-memory cache refreshed from Supabase | This phase | Data survives server restarts |
| No detail data in listing | Full detail data (dormitorios, baños, sup, desc) stored at scrape time | This phase | Bot can answer detail questions without live HTTP |
| n8n: Supabase native node | n8n: HTTP Request node with `Prefer: resolution=merge-duplicates` | Ongoing (upsert feature request open) | Must use HTTP node for upsert |

**Deprecated/outdated:**
- Live scraping in the bot's response path: replaces with Supabase query in Phase 2
- `_propiedades_cache` TTL-based expiry: replaces with explicit refresh via n8n/admin endpoint

---

## Open Questions

1. **Supabase project already exists?**
   - What we know: The project uses Supabase for human takeover flag (ROADMAP decision). A project
     may already be set up.
   - What's unclear: Does a Supabase project + credentials exist? If yes, what is the `project_ref`?
   - Recommendation: Planner should note: Task 02-02 must include "create Supabase project if not
     exists, create table, get `SUPABASE_URL` and `SUPABASE_KEY`" as a prerequisite step.

2. **Bertero rate limiting on detail page scraping**
   - What we know: No robots.txt restrictions found; 80+ properties means 80+ HTTP requests.
   - What's unclear: Whether Bertero blocks rapid sequential requests.
   - Recommendation: Default to 0.5s sleep between detail page requests. If blocked, increase to
     1s. Total scrape time: ~40-80 seconds per refresh cycle (acceptable for hourly refresh).

3. **n8n workflow trigger: POST to FastAPI vs. direct Supabase REST**
   - What we know: Both approaches work. FastAPI approach keeps Python logic in one place.
     Direct Supabase REST from n8n requires JS scraping reimplementation.
   - Recommendation: POST to `/admin/refresh-properties` on FastAPI. Simpler, no code duplication.
   - What's unclear: Whether the Railway-deployed server URL is stable/known at planning time.
     Planner note: The n8n workflow URL will be configured post-deploy.

---

## Sources

### Primary (HIGH confidence)
- supabase.com/docs/reference/python/initializing — sync client init pattern
- supabase.com/docs/reference/python/select — filter chaining, async syntax
- supabase.com/docs/reference/python/upsert — upsert with on_conflict, bulk upsert
- pypi.org/project/supabase/ — version 2.28.3 (released March 20, 2026)
- inmobiliariabertero.com.ar live page inspection — confirmed HTML structure:
  `#lista_informacion_basica`, `#lista_superficies` IDs; price in heading as `USD65.000`
- fastapi.tiangolo.com/advanced/events/ — lifespan warm-up pattern

### Secondary (MEDIUM confidence)
- github.com/orgs/supabase/discussions/28843 — async FastAPI integration recommendation
- n8n community forum — confirmed Supabase n8n node lacks upsert; HTTP Request node workaround
- Supabase REST API docs — `POST /rest/v1/table?on_conflict=col` + `Prefer: resolution=merge-duplicates` header for upsert

### Tertiary (LOW confidence)
- Bertero rate limiting behavior — not tested; 0.5s sleep is a reasonable precaution based on
  general web scraping best practices, not Bertero-specific data

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — supabase-py version and API verified from PyPI and official docs
- Architecture: HIGH — Supabase table schema and scraping approach verified from live page inspection
- Pitfalls: HIGH — price discrepancy (DATA-05) and n8n upsert gap are verified facts
- n8n workflow: MEDIUM — architecture recommendation (POST to FastAPI) is logical deduction, not
  documented as an official n8n best practice

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (supabase-py version may increment; Bertero HTML structure stable)
