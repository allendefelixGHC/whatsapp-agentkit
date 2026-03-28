---
phase: 02-supabase-data-foundation
plan: 01
subsystem: database
tags: [supabase, scraper, httpx, python, bertero, regex]

# Dependency graph
requires: []
provides:
  - "agent/supabase_client.py: singleton Supabase client + buscar_propiedades_db, upsert_propiedades, obtener_todas_propiedades, marcar_removidas"
  - "agent/scraper.py: deep scraper (listing + detail pages) with batch persist to Supabase"
  - "scripts/create_propiedades_table.sql: propiedades table DDL with indexes"
  - "supabase==2.28.3 dependency in requirements.txt"
affects: [02-02-query-integration, 02-03-admin-refresh, 02-04-n8n-refresh]

# Tech tracking
tech-stack:
  added: [supabase==2.28.3]
  patterns:
    - "Supabase singleton client: _client: Client | None = None + get_supabase() initializes on first call"
    - "Two-stage scraper: listing stubs first, then detail page enrichment with asyncio.sleep(0.5)"
    - "Detail page price as authoritative (DATA-05): merges over listing page price"

key-files:
  created:
    - agent/supabase_client.py
    - agent/scraper.py
    - scripts/create_propiedades_table.sql
  modified:
    - requirements.txt
    - .env

key-decisions:
  - "supabase-py sync client (create_client) used in async context via await .execute() — no acreate_client needed"
  - "Detail page price always overrides listing page price (DATA-05 requirement)"
  - "asyncio.sleep(0.5) between detail page requests as anti-rate-limiting precaution"
  - "marcar_removidas guards against empty ids_activos list (no-op if list empty to prevent full table wipe)"
  - "_parsear_listado_raw uses propiedad_id key (not id) to match Supabase schema"

patterns-established:
  - "Pattern: All Supabase operations go through agent/supabase_client.py — no direct SDK calls elsewhere"
  - "Pattern: scrape_and_persist() is the single entry point for full refresh; returns stats dict"

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 02 Plan 01: Supabase Data Foundation Summary

**Supabase client module with singleton pattern + deep scraper that extracts full Bertero property data (listing + detail pages) including authoritative detail-page prices and persists to Supabase via bulk upsert**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-28T13:46:53Z
- **Completed:** 2026-03-28T13:50:06Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Built `agent/supabase_client.py` with singleton Supabase client and full set of query/upsert helpers
- Built `agent/scraper.py` as two-stage deep scraper: listing stubs + detail page enrichment with batch persist
- Created `scripts/create_propiedades_table.sql` with full DDL and indexes for common filter patterns
- All unit verifications pass: import checks, detail page parsing, `_safe_int` helper

## Task Commits

Each task was committed atomically:

1. **Task 1: Supabase client module + SQL schema + dependencies** - `88e3935` (feat)
2. **Task 2: Deep scraper with listing + detail page extraction** - `f5c79a9` (feat)

**Plan metadata:** (docs commit — created next)

## Files Created/Modified

- `agent/supabase_client.py` — Singleton Supabase client; buscar_propiedades_db, upsert_propiedades, obtener_todas_propiedades, marcar_removidas
- `agent/scraper.py` — Two-stage deep scraper; scrape_and_persist(), _parsear_listado_raw(), _parsear_detalle_campos(), _safe_int()
- `scripts/create_propiedades_table.sql` — propiedades table DDL with indexes on operacion, tipo, precio_num
- `requirements.txt` — Added supabase==2.28.3
- `.env` — Added SUPABASE_URL and SUPABASE_KEY placeholders (git-ignored)

## Decisions Made

- **supabase-py sync client in async context:** Used `create_client` (sync) with `await .execute()` pattern. The underlying httpx transport is async-compatible — no need for `acreate_client` which adds complexity with no benefit for CRUD-only operations.
- **Detail page price is authoritative (DATA-05):** When merging stub + detail data, `precio` and `precio_num` from the detail page always override listing page values. Fallback to listing price only if detail has none.
- **asyncio.sleep(0.5) between detail requests:** Conservative anti-rate-limiting precaution. Total scrape time ~40-80s for 80 properties — acceptable for hourly n8n refresh.
- **marcar_removidas guards empty list:** If `ids_activos` is empty, function returns 0 and logs warning instead of deleting entire table. Prevents catastrophic wipe on scraping failure.
- **propiedad_id key in scraper:** `_parsear_listado_raw` outputs `propiedad_id` (matching Supabase schema) instead of `id` (used in tools.py display format). The two coexist without conflict.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

**External services require manual configuration before using scraper or Supabase queries:**

1. Create a Supabase project at supabase.com
2. Run `scripts/create_propiedades_table.sql` in Supabase SQL Editor
3. Add to `.env`:
   ```
   SUPABASE_URL=https://<your-project>.supabase.co
   SUPABASE_KEY=<your-anon-key>
   ```
   Both values from: Supabase Dashboard → Settings → API

## Next Phase Readiness

- **02-02 (tools.py query integration):** `buscar_propiedades_db` and `obtener_todas_propiedades` are ready to use. `get_supabase()` will lazily init on first call.
- **02-03 (admin refresh endpoint):** `scrape_and_persist()` is the single entry point; just needs to be called from a FastAPI route.
- **02-04 (n8n hourly refresh):** Architecture is ready — n8n calls POST `/admin/refresh-properties` which calls `scrape_and_persist()`.
- **Blocker:** Supabase credentials must be in `.env` before any Supabase operations work (credentials are not yet configured).

---
*Phase: 02-supabase-data-foundation*
*Completed: 2026-03-28*

## Self-Check: PASSED

- agent/supabase_client.py: FOUND
- agent/scraper.py: FOUND
- scripts/create_propiedades_table.sql: FOUND
- 02-01-SUMMARY.md: FOUND
- Commit 88e3935: FOUND
- Commit f5c79a9: FOUND
