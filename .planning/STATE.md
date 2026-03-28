# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-28)

**Core value:** El bot debe atender al cliente como lo haria el mejor asesor de Bertero: rapido, con informacion precisa, sin perder ningun lead, y sabiendo cuando ceder el control a un humano.
**Current focus:** Phase 3 - Audio & Smart Media

## Current Position

Phase: 3 of 6 (Audio & Smart Media)
Plan: 0 of 2 in current phase
Status: Not started
Last activity: 2026-03-28 — Phase 2 complete (Supabase Data Foundation verified 5/5)

Progress: [████████░░] 33%

## Performance Metrics

**Velocity:**
- Total plans completed: 5
- Average duration: 4.6 minutes
- Total execution time: 0.38 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-technical-hardening | 2 | 6 min | 3 min |
| 02-supabase-data-foundation | 3 | 17 min | 5.7 min |

**Recent Trend:**
- Last 5 plans: 01-01 (3 min), 01-02 (3 min), 02-01 (4 min), 02-02 (8 min), 02-03 (5 min)
- Trend: On track

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Supabase como fuente de propiedades (reemplaza scraping en vivo)
- Human takeover como flag en DB (bot/humano/cerrado)
- n8n para refresco horario de propiedades
- [01-01] Canonical phone form = digits-only 549XXXXXXXXXX for DB keys; GHL format derived on demand
- [01-01] TTLCache (no DB) for dedup — acceptable trade-off: resets on restart, covers all Whapi retry windows
- [Phase 01-02]: WHAPI_WEBHOOK_SECRET opt-in: no secret = no auth check (graceful degradation)
- [Phase 01-02]: GHL_WEBHOOK_AUTH_STRICT=false default: allow unsigned GHL webhooks, reject only invalid signatures
- [Phase 01-02]: Rate limit key is normalized phone (canonical digits-only) for consistent counting across phone format variants
- [02-01]: supabase-py v2 is sync — all SDK calls are direct (no await), async wrappers for FastAPI compat
- [02-03]: Fixed detail page parsing — strip <i> tags from <li>, use id="prop-desc" for description with html.unescape()
- [02-01]: Detail page price always overrides listing page price (DATA-05)
- [02-01]: marcar_removidas guards empty ids_activos list to prevent full table wipe on scraping failure
- [Phase 02-02]: Cache loaded from Supabase at startup, not per-request — property search is O(n) in-memory, <1 second (DATA-03)
- [Phase 02-02]: ADMIN_TOKEN empty = auth disabled on /admin/* (dev mode); non-empty = X-Admin-Token required (production)
- [Phase 02-03]: n8n is pure scheduler — all scraping stays in Python; n8n only fires HTTP POST to /admin/refresh-properties
- [Phase 02-03]: n8n env vars AGENTKIT_SERVER_URL and AGENTKIT_ADMIN_TOKEN decouple workflow from hardcoded URLs

### Pending Todos

None yet.

### Blockers/Concerns

- Sin API Key de Tokko: integracion directa diferida a v2
- Numero de test de Propulsar: todo el desarrollo es sobre numero no-produccion

## Session Continuity

Last session: 2026-03-28
Stopped at: Phase 2 complete — ready for Phase 3 planning
Resume file: None
