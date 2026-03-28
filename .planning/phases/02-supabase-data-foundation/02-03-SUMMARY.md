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
  modified: []

key-decisions:
  - "n8n is a pure scheduler: HTTP POST to /admin/refresh-properties, no scraping logic in n8n"
  - "AGENTKIT_SERVER_URL and AGENTKIT_ADMIN_TOKEN read from n8n env vars — workflow is URL-agnostic"
  - "Timeout 120s covers worst-case 80+ detail page scraping (~60s typical)"

patterns-established:
  - "Scheduler pattern: n8n Schedule Trigger -> HTTP Request -> IF status -> Log/Notify branches"

# Metrics
duration: 2min
completed: 2026-03-28
---

# Phase 2 Plan 3: n8n Hourly Refresh + End-to-End Verification Summary

**n8n workflow JSON (5-node: Schedule Trigger + HTTP Request + IF + Log Success/Error) ready to import for hourly Supabase property refresh — pipeline verification checkpoint pending**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-28T13:58:25Z
- **Completed:** 2026-03-28T14:00:00Z
- **Tasks:** 1 of 2 (paused at checkpoint)
- **Files modified:** 1

## Accomplishments
- n8n workflow JSON created with 5 nodes: Schedule Trigger (hourly cron), HTTP POST to /admin/refresh-properties, IF success/failure branch, Log nodes
- Workflow reads server URL and admin token from n8n environment variables (zero hardcoding)
- 120-second timeout configured to handle full Bertero scrape (~80 detail pages, ~60s)
- Log Error node has placeholder/comment for user to add Telegram/email notification

## Task Commits

Each task was committed atomically:

1. **Task 1: Create n8n hourly refresh workflow JSON** - `f359210` (feat)

**Plan metadata:** pending (checkpoint not yet cleared)

## Files Created/Modified
- `.planning/phases/02-supabase-data-foundation/n8n-refresh-workflow.json` - 5-node n8n workflow for hourly Supabase refresh; import into n8n and set AGENTKIT_SERVER_URL + AGENTKIT_ADMIN_TOKEN env vars

## Decisions Made
- n8n acts as pure scheduler only — all scraping and persistence logic stays in Python (per RESEARCH.md recommendation)
- Workflow uses n8n environment variables instead of hardcoded values — reusable across Railway staging/production environments
- 120s timeout because Bertero detail page scraping of 80+ properties takes ~60s in practice

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## Checkpoint: Task 2 — Human Verification Required

**Status:** PAUSED — awaiting human end-to-end verification

**What needs to be verified (5 Phase 2 success criteria):**

### Pre-requisites (one-time setup if not done yet)
1. Create Supabase project at supabase.com
2. Run `scripts/create_propiedades_table.sql` in Supabase SQL Editor
3. Copy `SUPABASE_URL` and `SUPABASE_KEY` (anon key) from Supabase Dashboard -> Settings -> API
4. Add to `.env`:
   ```
   SUPABASE_URL=https://xxx.supabase.co
   SUPABASE_KEY=eyJ...
   ADMIN_TOKEN=my-secret-123
   ```
5. Run `pip install -r requirements.txt`

### Test 1 - Initial scrape + persist
```bash
# Start server first
uvicorn agent.main:app --reload --port 8000

# Then in another terminal:
curl -X POST http://localhost:8000/admin/refresh-properties -H "X-Admin-Token: my-secret-123"
# Expected: {"status": "ok", "stats": {"total": 60+, "nuevas": 60+, "removidas": 0}}
```

### Test 2 - Verify Supabase has data
- Go to Supabase Dashboard -> Table Editor -> propiedades
- Verify 60+ rows exist with dormitorios, banos, sup_cubierta filled

### Test 3 - Bot responds from cache (sub-1-second)
```bash
python tests/test_local.py
# Ask: "Busco departamentos en venta en Nueva Cordoba"
# Verify response comes in under 1 second with property details
```

### Test 4 - Server warm-up
- Restart server, check logs for: `Cache de propiedades cargado desde Supabase`

### Test 5 (optional) - n8n workflow
- Import `.planning/phases/02-supabase-data-foundation/n8n-refresh-workflow.json` into n8n
- Set `AGENTKIT_SERVER_URL` and `AGENTKIT_ADMIN_TOKEN` in n8n environment variables
- Test execute manually and verify response

## User Setup Required

**Supabase configuration required before running verification:**
- Set `SUPABASE_URL` and `SUPABASE_KEY` in `.env`
- Set `ADMIN_TOKEN` in `.env`
- Run `scripts/create_propiedades_table.sql` in Supabase SQL Editor

## Next Phase Readiness
- n8n workflow JSON is ready to import — pipeline end-to-end verification is the only remaining blocker
- Once checkpoint cleared: Phase 2 is complete and Phase 3 (Human Takeover) can begin
- Phase 3 depends on the Supabase `conversaciones` table and `estado_conversacion` column in `propiedades`

---
*Phase: 02-supabase-data-foundation*
*Completed: 2026-03-28 (partial — checkpoint pending)*
