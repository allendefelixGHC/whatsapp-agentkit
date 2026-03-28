---
phase: 01-technical-hardening
plan: 02
subsystem: webhook-security
tags: [authentication, rate-limiting, ed25519, security, webhook]
dependency_graph:
  requires: [agent/utils.py, agent/dedup.py]
  provides: [agent/auth.py, agent/limiter.py, tools/configure_whapi_webhook.py]
  affects: [agent/main.py, .env.example]
tech_stack:
  added: []
  patterns: [Ed25519 public-key verification, TTLCache rate counter, opt-in shared-secret header auth]
key_files:
  created: [agent/auth.py, agent/limiter.py, tools/configure_whapi_webhook.py]
  modified: [agent/main.py, .env.example]
decisions:
  - "WHAPI_WEBHOOK_SECRET opt-in: no secret = no auth check (graceful degradation, not failure)"
  - "GHL_WEBHOOK_AUTH_STRICT=false default: allow unsigned GHL webhooks from internal automations"
  - "Rate limit key is normalized phone (canonical), send uses original msg.telefono (Whapi format)"
metrics:
  duration: "3 minutes"
  completed: "2026-03-28T12:22:xx"
  tasks_completed: 2
  files_modified: 5
---

# Phase 1 Plan 2: Webhook Authentication and Rate Limiting

**One-liner:** Ed25519 GHL signature verification, opt-in Whapi shared-secret header auth, and TTLCache-backed per-phone rate limiter blocking Claude API calls above 15 msg/min.

---

## What Was Built

### agent/auth.py (new)
GHL webhook authentication using Ed25519 public key verification. The GHL public key is hardcoded (it is a public key, not a secret). `verificar_firma_ghl(raw_body, signature_b64)` decodes the base64 signature and calls `Ed25519PublicKey.verify()`. Returns `True` on valid signature, `False` on `InvalidSignature` or any other error. Uses `cryptography` library already present as a transitive dependency of `anthropic`.

### agent/limiter.py (new)
Per-phone rate limiter using `TTLCache(maxsize=10_000, ttl=60)` — same library and pattern as `dedup.py`. Default limit: 15 messages/minute per phone (configurable via `RATE_LIMIT_PER_MINUTE`). `verificar_rate_limit(telefono)` increments the counter and returns `False` when threshold is exceeded. Includes `RATE_LIMIT_MESSAGE` constant with the user-facing WhatsApp response.

### tools/configure_whapi_webhook.py (new)
One-time setup script to register the webhook URL and auth header in the Whapi channel via `PATCH /settings`. Reads `WHAPI_TOKEN`, `WHAPI_WEBHOOK_SECRET`, and `WEBHOOK_URL` from `.env`. Validates all three are set before making the API call, and prints clear error messages if any are missing. Run once after deploy to activate the Whapi auth header.

### agent/main.py (modified)
Three security additions:

1. **Whapi auth (TECH-04):** Module-level `WHAPI_WEBHOOK_SECRET = os.getenv(...)`. At the top of `webhook_handler`, before body parsing: check `X-Whapi-Token` header when secret is set. Opt-in design: no secret = no check (graceful degradation for development).

2. **GHL auth (TECH-05):** In `ghl_webhook_handler`, `raw_body = await request.body()` is read first (avoids double-read pitfall). If `X-GHL-Signature` is present and invalid: 401. If absent and `GHL_WEBHOOK_AUTH_STRICT=true`: 401. If absent and strict=false (default): warning log, process anyway. Body parsed with `json.loads(raw_body)` instead of `await request.json()`.

3. **Rate limiting (TECH-06):** In `webhook_handler` message loop, after dedup check and phone normalization: calls `verificar_rate_limit(telefono_normalizado)`. On limit exceeded: sends `RATE_LIMIT_MESSAGE` via `proveedor.enviar_mensaje()` and `continue` (skips Claude API call).

### .env.example (modified)
Added three new documented variables: `WHAPI_WEBHOOK_SECRET`, `GHL_WEBHOOK_AUTH_STRICT`, `RATE_LIMIT_PER_MINUTE`.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create auth module (GHL Ed25519) and rate limiter module | d89ba78 | agent/auth.py, agent/limiter.py, .env.example |
| 2 | Wire auth and rate limiting into main.py webhook handlers | 77c5880 | agent/main.py, tools/configure_whapi_webhook.py |

---

## Verification Results

All success criteria met:

- [x] `agent/auth.py` with `verificar_firma_ghl()` using Ed25519PublicKey
- [x] `agent/limiter.py` with `verificar_rate_limit()` using TTLCache counter, default 15/min
- [x] Rate limiter blocks message #16 from same phone (15/min limit confirmed)
- [x] GHL auth rejects invalid signatures (tested with dummy base64 data)
- [x] `agent/main.py` `webhook_handler` checks `X-Whapi-Token` when `WHAPI_WEBHOOK_SECRET` is set
- [x] `agent/main.py` `ghl_webhook_handler` checks `X-GHL-Signature` with configurable strict mode
- [x] `agent/main.py` `webhook_handler` calls `verificar_rate_limit()` before Claude API, sends friendly message on limit
- [x] `tools/configure_whapi_webhook.py` exists and parses correctly
- [x] `.env.example` documents `WHAPI_WEBHOOK_SECRET`, `GHL_WEBHOOK_AUTH_STRICT`, `RATE_LIMIT_PER_MINUTE`
- [x] Server starts without errors on port 8112

---

## Deviations from Plan

None — plan executed exactly as written.

---

## Decisions Made

1. **`WHAPI_WEBHOOK_SECRET` opt-in design.** When the env var is empty (default), the Whapi auth check is skipped entirely. This allows development without configuring the secret, and prevents a bad deploy from breaking the webhook. The check is only activated when the operator explicitly sets the secret and runs `configure_whapi_webhook.py`.

2. **`GHL_WEBHOOK_AUTH_STRICT=false` default.** Some GHL internal automations (internal calendar triggers, test sends) may not include the `X-GHL-Signature` header. The default permissive mode logs a debug warning but does not block. Only explicitly invalid signatures (header present but wrong) are rejected in all modes.

3. **Rate limit key uses normalized phone (canonical).** `verificar_rate_limit()` receives `telefono_normalizado` (digits-only canonical form) as the counter key. This ensures consistent counting regardless of whether the same phone arrives in `549...@s.whatsapp.net` or `+543...` format. The original `msg.telefono` is still used for `proveedor.enviar_mensaje()` (Whapi needs `@s.whatsapp.net`).

---

## Self-Check: PASSED

Files created/verified:
- `agent/auth.py` — exists with `verificar_firma_ghl`
- `agent/limiter.py` — exists with `verificar_rate_limit` and `RATE_LIMIT_MESSAGE`
- `tools/configure_whapi_webhook.py` — exists with `WHAPI_WEBHOOK_SECRET` reference

Commits verified:
- `d89ba78` feat(01-02): add GHL Ed25519 auth module and per-phone rate limiter
- `77c5880` feat(01-02): wire webhook auth and rate limiting into main.py handlers
