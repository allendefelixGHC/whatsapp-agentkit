---
phase: 02-supabase-data-foundation
plan: "02"
subsystem: database
tags: [supabase, cache, scraper, fastapi, admin-endpoint]

# Dependency graph
requires:
  - phase: 02-01
    provides: supabase_client.py with obtener_todas_propiedades, upsert_propiedades; scraper.py with scrape_and_persist
provides:
  - buscar_propiedades reads from in-memory cache loaded from Supabase (DATA-03)
  - obtener_detalle_propiedad reads from cache (no live HTTP on request path)
  - cargar_cache_desde_supabase() loads all properties into memory on startup (TECH-07)
  - POST /admin/refresh-properties endpoint for n8n hourly scraping trigger
  - Graceful degradation: server starts even without SUPABASE_URL/KEY configured
affects: [02-03-n8n-hourly-refresh, 03-human-takeover, testing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - In-memory cache populated from Supabase at startup — no DB hit per request
    - Graceful degradation via try/except in lifespan warm-up
    - Optional admin auth via X-Admin-Token header (empty ADMIN_TOKEN disables check)
    - Fallback to live scraping when cache is empty (dev without Supabase creds)

key-files:
  created: []
  modified:
    - agent/tools.py
    - agent/main.py

key-decisions:
  - "Cache loaded from Supabase at startup, not per-request — property search is O(n) in-memory, <1 second"
  - "Fallback to live scraping when _propiedades_cache is empty (Supabase not configured)"
  - "ADMIN_TOKEN empty = auth disabled on /admin/* (dev mode); non-empty = X-Admin-Token required"
  - "obtener_detalle_propiedad reads from cache using propiedad_id or id field — handles both Supabase and legacy fallback cache schema"

patterns-established:
  - "Cache warm-up pattern: try/except in lifespan so missing creds don't block server start"
  - "Admin endpoint pattern: optional token auth via env var — permissive by default, strict in production"

# Metrics
duration: 8min
completed: 2026-03-28
---

# Phase 2 Plan 2: Wire Bot to Supabase Cache Summary

**In-memory property cache loaded from Supabase on server startup, with /admin/refresh-properties endpoint for n8n hourly trigger — bot now serves properties in <1 second instead of live-scraping Bertero**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-28T00:00:00Z
- **Completed:** 2026-03-28T00:08:00Z
- **Tasks:** 2
- **Files modified:** 2 (+ .env updated locally)

## Accomplishments
- Bot reads properties from Supabase-backed in-memory cache instead of live Bertero scraping
- Server starts with cache warm-up (TECH-07): all properties loaded into memory at boot
- POST /admin/refresh-properties triggers full scrape + Supabase upsert + cache reload for n8n plan 02-03
- Graceful degradation: server starts even if SUPABASE_URL/KEY are not configured
- obtener_detalle_propiedad now reads from cache (zero HTTP calls to Bertero on detail queries)

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace live scraping in tools.py with Supabase queries** - `6f28e25` (feat)
2. **Task 2: Cache warm-up in lifespan + /admin/refresh-properties endpoint** - `407c9a0` (feat)

## Files Created/Modified
- `agent/tools.py` - Added cargar_cache_desde_supabase(); rewrote buscar_propiedades (cache-first) and obtener_detalle_propiedad (cache lookup); marked _parsear_listado/_parsear_detalle as legacy
- `agent/main.py` - Imports cargar_cache_desde_supabase and scrape_and_persist; lifespan warm-up with try/except; ADMIN_TOKEN env var; POST /admin/refresh-properties endpoint

## Decisions Made
- Cache is populated from Supabase once at startup and on each refresh trigger — no per-request DB hit, property search is O(n) in-memory, satisfying DATA-03 (<1 second)
- Fallback to live scraping in buscar_propiedades when cache is empty — allows bot to work during development without Supabase credentials
- ADMIN_TOKEN empty disables auth check on /admin endpoints (dev mode); set in production for security
- obtener_detalle_propiedad tries both `propiedad_id` and `id` fields when looking up in cache — handles both Supabase schema and the legacy live-scraping fallback cache

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required

None - ADMIN_TOKEN placeholder was added to .env (gitignored). In production, set a strong random token in Railway environment variables.

## Next Phase Readiness
- /admin/refresh-properties endpoint is ready for n8n Schedule Trigger (plan 02-03)
- Bot serves properties from Supabase cache — no scraping on request path
- SUPABASE_URL and SUPABASE_KEY must be populated for cache to load on startup

---
*Phase: 02-supabase-data-foundation*
*Completed: 2026-03-28*
