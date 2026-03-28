# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-28)

**Core value:** El bot debe atender al cliente como lo haria el mejor asesor de Bertero: rapido, con informacion precisa, sin perder ningun lead, y sabiendo cuando ceder el control a un humano.
**Current focus:** Phase 2 - Supabase Data Foundation

## Current Position

Phase: 2 of 6 (Supabase Data Foundation)
Plan: 1 of 4 in current phase
Status: In progress
Last activity: 2026-03-28 — Plan 02-01 complete (Supabase client module + deep scraper)

Progress: [███░░░░░░░] 18%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: 3.3 minutes
- Total execution time: 0.17 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-technical-hardening | 2 | 6 min | 3 min |
| 02-supabase-data-foundation | 1 | 4 min | 4 min |

**Recent Trend:**
- Last 5 plans: 01-01 (3 min), 01-02 (3 min), 02-01 (4 min)
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
- [02-01]: supabase-py sync client (create_client) used in async context via await .execute() — no acreate_client needed
- [02-01]: Detail page price always overrides listing page price (DATA-05)
- [02-01]: marcar_removidas guards empty ids_activos list to prevent full table wipe on scraping failure

### Pending Todos

None yet.

### Blockers/Concerns

- Sin API Key de Tokko: integracion directa diferida a v2
- Numero de test de Propulsar: todo el desarrollo es sobre numero no-produccion

## Session Continuity

Last session: 2026-03-28
Stopped at: Phase 2 Plan 1 complete — Supabase client module + deep scraper (listing + detail pages)
Resume file: None
