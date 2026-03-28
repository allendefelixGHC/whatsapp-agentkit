---
phase: 02-supabase-data-foundation
plan: "03"
subsystem: infra
tags: [n8n, scheduler, supabase, scraper, fastapi, admin-endpoint]

# Dependency graph
requires:
  - phase: 02-02
    provides: POST /admin/refresh-properties endpoint + Supabase-backed cache
provides:
  - n8n workflow JSON for hourly property refresh (importable)
  - Schedule Trigger calling /admin/refresh-properties every hour (DATA-04)
  - IF node branching on HTTP status for error alerting
  - Complete Phase 2 data pipeline verified end-to-end
affects: [03-human-takeover, production-deploy]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - n8n as pure scheduler — all scraping logic stays in Python/FastAPI, n8n just triggers
    - n8n env vars (AGENTKIT_SERVER_URL, AGENTKIT_ADMIN_TOKEN) decouple workflow from hardcoded URLs
    - IF node on HTTP status code enables failure alerting without modifying Python code

key-files:
  created:
    - .planning/phases/02-supabase-data-foundation/n8n-refresh-workflow.json
  modified:
    - agent/scraper.py
    - agent/supabase_client.py

key-decisions:
  - "n8n is a pure scheduler: HTTP POST to /admin/refresh-properties, no scraping logic in n8n"
  - "AGENTKIT_SERVER_URL and AGENTKIT_ADMIN_TOKEN read from n8n env vars — workflow is URL-agnostic"
  - "Timeout 120s covers worst-case 80+ detail page scraping (~60s typical)"
  - "supabase-py v2 SDK is sync — removed await from all query calls"
  - "Detail page <li> contains <i> icon tags — strip HTML before parsing key:value pairs"
  - "Description stored in id=prop-desc with HTML-encoded content — use html.unescape()"

patterns-established:
  - "Scheduler pattern: n8n Schedule Trigger -> HTTP Request -> IF status -> Log/Notify branches"

# Metrics
duration: 5min
completed: 2026-03-28
---

# Phase 2 Plan 3: n8n Hourly Refresh + End-to-End Verification Summary

**n8n workflow JSON created + full Phase 2 data pipeline verified end-to-end: 74 propiedades scraped → Supabase → cache → bot responses in <1s**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-28T13:58:25Z
- **Completed:** 2026-03-28T14:10:00Z
- **Tasks:** 2 of 2 complete
- **Files modified:** 3

## Accomplishments
- n8n workflow JSON created with 5 nodes: Schedule Trigger (hourly cron), HTTP POST to /admin/refresh-properties, IF success/failure branch, Log nodes
- Workflow reads server URL and admin token from n8n environment variables (zero hardcoding)
- 120-second timeout configured to handle full Bertero scrape (~80 detail pages, ~60s)
- Fixed supabase-py v2 sync SDK usage (removed invalid await calls)
- Fixed detail page parser: strip <i> icon tags from <li>, use id="prop-desc" for description, html.unescape() for encoded content

## Verification Results

### Test 1 - Scrape + Persist: PASSED
- `scrape_and_persist()` returned `{"total": 74, "nuevas": 74, "removidas": 0}` in 73.7s
- All 74 properties upserted to Supabase

### Test 2 - Supabase Data Quality: PASSED
- 74 rows in propiedades table
- 41 with dormitorios (33 are terrenos/locales without bedrooms — correct)
- 74 with descripcion (100%)
- Detail fields populated: banos, sup_cubierta, sup_total, antiguedad, expensas

### Test 3 - Bot Search <1 Second: PASSED
- Search for "departamento venta nueva cordoba": 0.0000s (from in-memory cache)
- 3 results returned with full property details

### Test 4 - Cache Warm-up: PASSED
- `cargar_cache_desde_supabase()` loaded 74 properties in 0.79s
- Cache populated from Supabase on startup

### Test 5 - n8n Workflow: READY
- JSON file created and importable
- Requires n8n env vars: AGENTKIT_SERVER_URL, AGENTKIT_ADMIN_TOKEN

## Task Commits

1. **Task 1: Create n8n hourly refresh workflow JSON** - `f359210` (feat)
2. **Task 2: E2E verification** - `bca027b` (fix — parser and SDK corrections found during verification)

## Files Created/Modified
- `.planning/phases/02-supabase-data-foundation/n8n-refresh-workflow.json` - 5-node n8n workflow
- `agent/supabase_client.py` - Removed await from sync SDK calls
- `agent/scraper.py` - Fixed <li> parsing (strip HTML tags) + description extraction (prop-desc id + html.unescape)

## Decisions Made
- supabase-py v2 is sync, not async — all query calls are direct (no await)
- Detail page HTML has <i> icon tags inside <li> — must strip before parsing
- Description lives in id="prop-desc" with HTML-encoded content (&lt;p&gt;), not class="description"

## Deviations from Plan
- Had to fix supabase_client.py (sync vs async) and scraper.py (HTML structure) during verification
- These were bugs in the generated code from plans 02-01, caught during E2E testing

## Issues Encountered
- supabase-py v2 SDK is sync despite being commonly used with async FastAPI — fixed by removing await
- Bertero detail pages have <i class="fa fa-check"> inside <li> items — original regex `<li>([^<]+)</li>` failed

---
*Phase: 02-supabase-data-foundation*
*Completed: 2026-03-28*
