---
phase: 01-technical-hardening
verified: 2026-03-28T12:27:04Z
status: passed
score: 5/5 must-haves verified
re_verification: false
---

# Phase 01: Technical Hardening Verification Report

**Phase Goal:** El bot procesa mensajes de forma confiable sin duplicados, con autenticacion de webhooks y proteccion contra abuso
**Verified:** 2026-03-28T12:27:04Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Cuando Whapi reintenta un webhook, el bot no responde dos veces al mismo mensaje | VERIFIED | `agent/dedup.py` — `TTLCache(maxsize=10_000, ttl=300)` + `es_duplicado()` called in main.py before Claude API; confirmed via unit test: second call with same ID returns True |
| 2  | El bot recuerda los ultimos 16 mensajes de cada conversacion (no solo 6) | VERIFIED | `agent/memory.py` line 63: `async def obtener_historial(telefono: str, limite: int = 16)` — confirmed via `inspect.signature` test |
| 3  | Un mismo numero de telefono en distintos formatos (+54, 54, 0, sin prefijo) se resuelve siempre al mismo contacto | VERIFIED | `agent/utils.py` `normalizar_telefono()` — tested: `5493517575244@s.whatsapp.net`, `+543517575244`, `03517575244`, `3517575244` all return `5493517575244`. Used in both `main.py` (memory ops) and `ghl.py` (`_formatear_telefono_ghl`, `buscar_contacto_por_telefono`) |
| 4  | Webhooks de origen desconocido (sin token valido de Whapi o GHL) son rechazados con 401 | VERIFIED | Whapi: `main.py` lines 98-102 — checks `X-Whapi-Token` header vs `WHAPI_WEBHOOK_SECRET` env var, raises HTTP 401. GHL: `main.py` lines 195-201 — calls `verificar_firma_ghl()` from `agent/auth.py` (Ed25519 public key), raises HTTP 401 on invalid/missing sig; configurable strict mode via `GHL_WEBHOOK_AUTH_STRICT` |
| 5  | Si un usuario envia mas de N mensajes por minuto, el bot no llama a Claude API y responde con mensaje de rate limit | VERIFIED | `agent/limiter.py` — `TTLCache(maxsize=10_000, ttl=60)`, default limit 15/min. Wired in `main.py` lines 122-125: blocks before `generar_respuesta()`, sends `RATE_LIMIT_MESSAGE` via WhatsApp. Confirmed via flood test: blocked after 15 messages |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `agent/utils.py` | Centralized `normalizar_telefono()` | VERIFIED | Exists, 72 lines, full Argentina phone normalization with docstring and examples |
| `agent/dedup.py` | TTLCache deduplication with `es_duplicado()` | VERIFIED | Exists, 47 lines, `TTLCache(maxsize=10_000, ttl=300)`, handles empty IDs |
| `agent/memory.py` | History default = 16 | VERIFIED | `limite: int = 16` on line 63, docstring updated |
| `agent/auth.py` | GHL Ed25519 signature verification | VERIFIED | Exists, 54 lines, GHL public key hardcoded (correctly — public key), `verificar_firma_ghl()` returns False on invalid sig |
| `agent/limiter.py` | Per-phone rate limiting | VERIFIED | Exists, 56 lines, configurable via `RATE_LIMIT_PER_MINUTE` env var, `RATE_LIMIT_MESSAGE` constant |
| `tools/configure_whapi_webhook.py` | One-time Whapi webhook setup script | VERIFIED | Exists, 81 lines, reads `WHAPI_WEBHOOK_SECRET` from .env, calls Whapi PATCH /settings with auth header |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `agent/main.py` | `agent/dedup.py` | `es_duplicado(msg.mensaje_id)` before Claude | WIRED | Line 111: `if es_duplicado(msg.mensaje_id):` — runs before `obtener_historial` and `generar_respuesta` |
| `agent/main.py` | `agent/utils.py` | `normalizar_telefono(msg.telefono)` for memory ops | WIRED | Line 117: `telefono_normalizado = normalizar_telefono(msg.telefono)` used for `obtener_historial` (line 142) and `guardar_mensaje` (lines 163-164). Original `msg.telefono` preserved for Whapi sending |
| `agent/ghl.py` | `agent/utils.py` | `from agent.utils import normalizar_telefono` | WIRED | Line 13: import present. Used at line 114 in `_formatear_telefono_ghl()` and line 387 in `buscar_contacto_por_telefono()` |
| `agent/main.py` | `agent/auth.py` | `verificar_firma_ghl(raw_body, sig)` in GHL handler | WIRED | Line 195: called with `raw_body` (read before JSON parse to avoid double-read). 401 raised on failure |
| `agent/main.py` | `agent/limiter.py` | `verificar_rate_limit()` after dedup, before Claude | WIRED | Lines 122-125: called after `es_duplicado`, before `obtener_historial`/`generar_respuesta`. Sends `RATE_LIMIT_MESSAGE` and `continue`s |
| `agent/main.py` | `WHAPI_WEBHOOK_SECRET` env var | `X-Whapi-Token` header check | WIRED | Lines 49, 98-102: loaded at module level, checked at handler entry. Opt-in (empty = disabled) |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| TECH-01 (history 16 msgs) | SATISFIED | `memory.py` default changed from 6 to 16 |
| TECH-02 (dedup on retry) | SATISFIED | `dedup.py` TTLCache, wired in `main.py` |
| TECH-03 (phone normalization) | SATISFIED | `utils.py` centralizes logic; `ghl.py` and `main.py` both use it |
| TECH-04 (Whapi auth) | SATISFIED | `X-Whapi-Token` header validation in `main.py`, setup script in `tools/` |
| TECH-05 (GHL auth) | SATISFIED | Ed25519 `agent/auth.py`, wired in `ghl_webhook_handler`, configurable strict mode |
| TECH-06 (rate limiting) | SATISFIED | `agent/limiter.py`, wired before Claude API call, sends WhatsApp message on limit |

### Anti-Patterns Found

None. No TODOs, FIXMEs, placeholder returns, empty handlers, or stub implementations found in any of the phase artifacts.

**Note:** `agent/ghl.py` line 427 contains inline string replacement in `obtener_link_booking()` (URL pre-fill utility). This is out of scope for TECH-03 — that function builds a booking widget URL, not an identity key — and does not affect phone normalization correctness for memory or GHL contact matching.

### Human Verification Required

None required for automated checks. The following items can be validated manually but are not blocking:

1. **Whapi auth end-to-end** — Set `WHAPI_WEBHOOK_SECRET` in `.env`, then send a POST to `/webhook` without the header and confirm 401 is returned in production. Expected: HTTP 401 with body `{"detail": "Unauthorized"}`.

2. **Rate limit WhatsApp response** — Send 16+ messages from the same phone number within 60 seconds and confirm the bot replies with the rate limit message without calling Claude. Expected: friendly message in WhatsApp, no Claude API call visible in logs.

### Gaps Summary

No gaps. All 5 observable truths are verified end-to-end. All 6 artifacts exist and are substantive. All key links are wired. All 6 requirements are satisfied.

---

_Verified: 2026-03-28T12:27:04Z_
_Verifier: Claude (gsd-verifier)_
