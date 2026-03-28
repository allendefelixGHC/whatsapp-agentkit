# Phase 1: Technical Hardening - Research

**Researched:** 2026-03-28
**Domain:** FastAPI webhook reliability — deduplication, phone normalization, webhook auth, rate limiting
**Confidence:** HIGH

---

## Summary

This phase hardens an existing, working FastAPI + WhatsApp bot. All six requirements are surgical
modifications to the existing codebase rather than greenfield work. No new major dependencies are
strictly required: the project already has SQLAlchemy + aiosqlite for deduplication storage, a
plain-dict in-memory pattern (session.py) as the model for the dedup cache, and FastAPI's
`Request` object for webhook auth header access.

The current codebase has three specific gaps to close:

1. **Reliability gap**: `obtener_historial()` hardcodes `limite=6` (TECH-01). `main.py` has no
   dedup logic — every webhook call triggers Claude (TECH-02). Phone normalization is copy-pasted
   in at least two places: `ghl.py` and `main.py` (TECH-03).

2. **Security gap**: Both `/webhook` and `/webhook/ghl` accept any POST with no origin check
   (TECH-04, TECH-05). GHL now signs webhooks with Ed25519 (header `X-GHL-Signature`), with
   RSA legacy (`X-WH-Signature`) deprecated July 1, 2026.

3. **Cost/abuse gap**: No rate limiting — a single user can trigger unlimited Claude API calls
   (TECH-06).

**Primary recommendation:** Implement all six changes as small, isolated modifications. Use
`cachetools.TTLCache` for in-memory message deduplication (no DB write needed). Use `slowapi`
0.1.9 for rate limiting with memory backend and a custom `key_func` that extracts phone from
the parsed webhook body. Use `cryptography` (already a transitive dep of `anthropic`) for GHL
Ed25519 verification.

---

## Standard Stack

### Core (already in requirements.txt — no new installs needed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.104.0 | Framework — `Request`, `HTTPException`, dep injection | Already in use |
| sqlalchemy | >=2.0.0 | ORM — no schema change needed for TECH-01/02/03 | Already in use |
| python-dotenv | >=1.0.0 | Env var loading for new secrets | Already in use |
| cryptography | (transitive) | Ed25519 verify for GHL webhook — ships with `anthropic` | Already present |

### New Dependencies
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| cachetools | >=5.3.0 | TTLCache for in-memory message-ID deduplication | TECH-02 only |
| slowapi | 0.1.9 | Per-user rate limiting for FastAPI | TECH-06 only |
| limits | (slowapi dep) | Backing store for slowapi; use `memory://` URI | TECH-06 — single instance |

**Installation:**
```bash
pip install cachetools slowapi
```

### Why NOT Redis for this phase
The app is a single Railway instance. Redis adds operational complexity with no benefit at this
scale. Both `cachetools.TTLCache` and `slowapi` with `storage_uri="memory://"` work correctly
for single-process deployments. If the app scales to multiple instances in a future phase, swap
to Redis by changing one URI string.

---

## Architecture Patterns

### Recommended File Structure Changes
```
agent/
├── utils.py           # NEW — centralizes normalizar_telefono() (TECH-03)
├── dedup.py           # NEW — TTLCache for message deduplication (TECH-02)
├── limiter.py         # NEW — slowapi Limiter instance (TECH-06)
├── main.py            # MODIFIED — add auth middleware + rate limit decorator
├── memory.py          # MODIFIED — change default limite=6 to limite=16 (TECH-01)
├── providers/
│   └── whapi.py       # MODIFIED — remove inline phone logic, call normalizar_telefono()
└── ghl.py             # MODIFIED — remove inline phone logic, call normalizar_telefono()
```

### Pattern 1: Phone Normalization Utility (TECH-03)

**What:** Single canonical function `normalizar_telefono(raw: str) -> str` that handles all
input variants and returns a consistent key used by memory.py, ghl.py, and whapi.py.

**When to use:** Called at the moment a phone string enters the system (webhook parse, GHL
webhook, any tool that writes to DB).

**Canonical form:** Store as `{digits_only}` — no `+`, no `@s.whatsapp.net`, no `@c.us`.
Always 11–13 digits. Argentina mobile = 13 digits starting with `549`.

```python
# agent/utils.py
import re

def normalizar_telefono(raw: str) -> str:
    """
    Normaliza cualquier formato de teléfono a dígitos puros con prefijo correcto.

    Entradas aceptadas:
      - "5493517575244@s.whatsapp.net"  → "5493517575244"
      - "+543517575244"                 → "5493517575244"  (agrega 9 móvil AR)
      - "543517575244"                  → "5493517575244"
      - "0351 7575244"                  → "5493517575244"  (agrega 54+9)
      - "3517575244"                    → "5493517575244"  (agrega 54+9)
      - "15 7575244"                    → depende del área (LOW confidence)
    """
    # Quitar sufijo WhatsApp y símbolos
    s = re.sub(r"@.*", "", raw)
    s = re.sub(r"[^\d]", "", s)

    # Remover trunk prefix "0" de Argentina
    if s.startswith("0"):
        s = s[1:]

    # Remover prefijo móvil local "15"
    # Solo si el número tiene longitud consistente con un número sin código de país
    if s.startswith("15") and len(s) <= 10:
        s = s[2:]

    # Si es número local AR sin código de país (10 dígitos: area+abonado)
    if len(s) == 10:
        s = "549" + s

    # Si tiene código de país 54 pero sin 9 móvil (12 dígitos)
    if s.startswith("54") and not s.startswith("549") and len(s) == 12:
        s = "549" + s[2:]

    # Si no tiene código de país y es > 10 dígitos (error de datos), dejar como está
    return s
```

**Confidence:** HIGH for the main cases (Whapi always sends 13-digit `549...@s.whatsapp.net`,
GHL always sends `+543...`). LOW confidence for "15" prefix edge case — verify in production.

### Pattern 2: Message Deduplication with TTLCache (TECH-02)

**What:** In-memory set-like cache of recently seen `mensaje_id` strings. TTL of 5 minutes
(Whapi retries happen within seconds to minutes). If ID is already in cache, return 200 OK
immediately without calling Claude.

**When to use:** First check inside `webhook_handler`, before historial fetch.

```python
# agent/dedup.py
from cachetools import TTLCache

# 10 000 message IDs, each lives 5 minutes
# At 100 msgs/min peak, this handles 30x the expected load
_seen: TTLCache = TTLCache(maxsize=10_000, ttl=300)


def es_duplicado(mensaje_id: str) -> bool:
    """Retorna True si ya procesamos este mensaje_id recientemente."""
    if not mensaje_id:
        return False
    if mensaje_id in _seen:
        return True
    _seen[mensaje_id] = True
    return False
```

```python
# En main.py — primer check dentro del loop de mensajes:
from agent.dedup import es_duplicado

for msg in mensajes:
    if msg.es_propio or (not msg.texto and not msg.imagen_url):
        continue
    if es_duplicado(msg.mensaje_id):
        logger.debug(f"Mensaje duplicado ignorado: {msg.mensaje_id}")
        continue
    # ... resto del procesamiento
```

**Confidence:** HIGH — pattern is identical to the existing `session.py` TTL-dict, uses
standard `cachetools` library.

### Pattern 3: Webhook Authentication (TECH-04 — Whapi)

**What:** Whapi supports custom headers in webhook callbacks configured via PATCH `/settings`.
Strategy: configure Whapi to send `X-Whapi-Token: {secret}` on every callback. Verify in
FastAPI before processing.

**How it works:**
1. Generate a random secret: store as `WHAPI_WEBHOOK_SECRET` in `.env`
2. Configure Whapi channel via one-time API call to set the custom header
3. In `webhook_handler`, check header before parsing body

```python
# In main.py — at top of webhook_handler POST
WHAPI_WEBHOOK_SECRET = os.getenv("WHAPI_WEBHOOK_SECRET", "")

async def webhook_handler(request: Request):
    if WHAPI_WEBHOOK_SECRET:
        token = request.headers.get("X-Whapi-Token", "")
        if token != WHAPI_WEBHOOK_SECRET:
            logger.warning(f"Webhook Whapi rechazado — token inválido: {token[:20]}")
            raise HTTPException(status_code=401, detail="Unauthorized")
    # ... existing processing
```

**Whapi setup (one-time API call):**
```python
# Script to configure Whapi channel settings (run once after deploy)
import httpx, os
httpx.patch(
    "https://gate.whapi.cloud/settings",
    headers={"Authorization": f"Bearer {os.getenv('WHAPI_TOKEN')}",
             "Content-Type": "application/json"},
    json={"webhooks": [{
        "events": [{"type": "messages", "method": "post"}],
        "mode": "body",
        "headers": {"X-Whapi-Token": os.getenv("WHAPI_WEBHOOK_SECRET")},
        "url": os.getenv("WEBHOOK_URL")
    }]}
)
```

**Confidence:** MEDIUM — Whapi custom headers feature is documented (verified via official docs).
The specific `X-Whapi-Token` header name is our choice (not a Whapi standard). The Whapi auth
mechanism does not include automatic signature verification like HMAC — the shared-secret-in-header
pattern is the only option they provide.

### Pattern 4: GHL Webhook Authentication (TECH-05)

**What:** GHL signs every webhook with an Ed25519 signature in `X-GHL-Signature` header.
The `cryptography` library (already present as an `anthropic` transitive dep) can verify it.

**Public key (hardcode — this is a public key, not a secret):**
```
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAi2HR1srL4o18O8BRa7gVJY7G7bupbN3H9AwJrHCDiOg=
-----END PUBLIC KEY-----
```

**Implementation:**
```python
# agent/auth.py
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

GHL_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAi2HR1srL4o18O8BRa7gVJY7G7bupbN3H9AwJrHCDiOg=
-----END PUBLIC KEY-----"""

_ghl_pubkey: Ed25519PublicKey = serialization.load_pem_public_key(GHL_PUBLIC_KEY_PEM)


def verificar_firma_ghl(raw_body: bytes, signature_b64: str) -> bool:
    """Verifica X-GHL-Signature (Ed25519). Retorna True si es válida."""
    try:
        sig = base64.b64decode(signature_b64)
        _ghl_pubkey.verify(sig, raw_body)
        return True
    except (InvalidSignature, Exception):
        return False
```

```python
# In main.py — ghl_webhook_handler — CRITICAL: must read body BEFORE calling request.json()
async def ghl_webhook_handler(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-GHL-Signature", "")
    if sig and not verificar_firma_ghl(raw_body, sig):
        logger.warning("Webhook GHL rechazado — firma inválida")
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Fallback: if no sig header at all and env says strict mode, also reject
    body = json.loads(raw_body)  # Use parsed raw body instead of request.json()
    # ... rest of handler
```

**Confidence:** HIGH — GHL public key and Ed25519 method verified via official GHL developer
documentation. `cryptography` library verified available (ships with `anthropic>=0.40`).

**Important edge:** GHL's legacy `X-WH-Signature` (RSA) is deprecated July 1, 2026. Implement
`X-GHL-Signature` (Ed25519) only. If both headers are present, prefer `X-GHL-Signature`.

### Pattern 5: Rate Limiting with slowapi (TECH-06)

**What:** Apply per-phone rate limiting to the Whapi webhook handler. The phone number is
extracted from the parsed message body by a custom `key_func`. If rate exceeded, return a
friendly WhatsApp message instead of calling Claude.

**Challenge:** slowapi's `key_func` receives only the raw `Request` — the phone is in the JSON
body, which can only be read once. Solution: extract the phone from the parsed message object
AFTER parsing, not in `key_func`. Use a simpler approach: manual per-phone counter with
`TTLCache` (same pattern as dedup).

**Recommended approach — manual rate limiter (avoids slowapi body-read issue):**

```python
# agent/limiter.py
from cachetools import TTLCache

# Sliding window: max N messages per 60 seconds per phone
_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
_counters: TTLCache = TTLCache(maxsize=10_000, ttl=60)


def verificar_rate_limit(telefono: str) -> bool:
    """
    Retorna True si el teléfono está dentro del límite.
    Retorna False si excedió el límite (debe enviarse mensaje de rate limit).
    """
    count = _counters.get(telefono, 0)
    if count >= _RATE_LIMIT:
        return False
    _counters[telefono] = count + 1
    return True
```

```python
# In main.py — inside the message loop, after dedup check:
from agent.limiter import verificar_rate_limit

if not verificar_rate_limit(msg.telefono):
    logger.warning(f"Rate limit excedido para {msg.telefono}")
    await proveedor.enviar_mensaje(
        msg.telefono,
        "Estás enviando muchos mensajes seguidos. Por favor espera un momento antes de continuar. 🙏"
    )
    continue  # Do NOT call Claude
```

**Why not slowapi:** slowapi needs to read the body in `key_func` to extract phone, but FastAPI
can only read the body once before `.json()` is called. This pattern avoids that problem entirely
and is simpler. The TTLCache approach is consistent with `dedup.py` (same library, same pattern).

**Confidence:** HIGH — pattern proven by existing `session.py` in this codebase.

### Anti-Patterns to Avoid

- **Reading request body twice:** In `ghl_webhook_handler`, use `raw_body = await request.body()`
  once, then `json.loads(raw_body)` instead of calling `await request.json()` separately.
- **Phone normalization inline:** Never normalize phones inside `ghl.py` or `whapi.py` directly.
  Always call `utils.normalizar_telefono()`.
- **TTLCache in async context without lock:** `cachetools.TTLCache` is NOT thread-safe for writes.
  In asyncio (single thread), this is fine. If migrating to threading, add `asyncio.Lock`.
- **Verifying GHL signature with RSA:** Only verify `X-GHL-Signature` (Ed25519). RSA legacy
  key ends support July 1, 2026.
- **Blocking the event loop in auth:** `Ed25519PublicKey.verify()` is synchronous but CPU-fast
  (~microseconds). No need to run in executor.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TTL expiry for dedup cache | Custom dict with timestamp loop | `cachetools.TTLCache` | Handles maxsize + TTL atomically, battle-tested |
| Argentina phone regex | Complex re.sub chain | `utils.normalizar_telefono()` (centralized) | One place to fix when edge cases appear |
| Ed25519 crypto | Custom base64 decode loop | `cryptography` library (already present) | Correct padding, exception handling |
| Rate limit sliding window | Time-bucketed dict | `TTLCache(ttl=60)` counter | Same library already used for dedup |

**Key insight:** All "storage" in this phase is in-memory with TTL. The existing `session.py`
already demonstrates this pattern. Follow it exactly rather than introducing Redis or additional
DB tables.

---

## Common Pitfalls

### Pitfall 1: TTLCache is not thread-safe
**What goes wrong:** Under concurrent requests (asyncio with multiple coroutines), a TTLCache
write can be interleaved with a read causing inconsistent state.
**Why it happens:** cachetools is designed for threading, not asyncio — but in asyncio, the GIL
and single-threaded event loop prevent true concurrent dict writes.
**How to avoid:** In asyncio (no `threading` involved), `TTLCache` is safe. If uvicorn workers > 1
are ever used (`--workers N`), each worker has its own in-memory cache — dedup won't work across
workers. For Phase 1, this is acceptable (document it).
**Warning signs:** Same message processed twice in logs.

### Pitfall 2: GHL sends webhook without X-GHL-Signature in some workflows
**What goes wrong:** Some GHL workflow triggers (internal automations, test sends) may omit the
signature header entirely.
**Why it happens:** Legacy internal GHL events may not sign payloads.
**How to avoid:** Make GHL auth configurable: `GHL_WEBHOOK_AUTH_STRICT=false` in `.env` allows
unauthenticated if no signature header. Only reject if header IS present but signature is wrong.
**Warning signs:** Legitimate GHL webhooks returning 401 after deploy.

### Pitfall 3: request.body() consumed before request.json()
**What goes wrong:** FastAPI's `request.body()` and `request.json()` both read the stream.
After one is called, the other returns empty bytes.
**Why it happens:** HTTP request body is a stream, not a buffer — unless FastAPI caches it.
**How to avoid:** In `ghl_webhook_handler`, read `raw_body = await request.body()` FIRST, then
parse with `body = json.loads(raw_body)`. Do NOT call `await request.json()` after.
**Warning signs:** `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`

### Pitfall 4: Phone normalization breaks WhatsApp send format
**What goes wrong:** `normalizar_telefono()` returns `5493517575244` but Whapi expects
`5493517575244@s.whatsapp.net` for outgoing messages.
**Why it happens:** The normalized form (digits only) is the storage key, not the send format.
**How to avoid:** Keep `normalizar_telefono()` as the DB/memory key function. For Whapi sends,
the `chat_id` from the incoming webhook (`msg.telefono`) already includes `@s.whatsapp.net` —
use it directly. Normalize only for storage lookups.
**Warning signs:** Whapi returns 400 on send with "invalid to" error.

### Pitfall 5: Whapi retries same message_id within the TTL window
**What goes wrong:** The TTLCache stores the ID on first sight, so all retries are silently
dropped. This is correct behavior — but must be confirmed in logs.
**Why it happens:** This is intentional. But if `mensaje_id` is ever empty string `""`, the
dedup check `if not mensaje_id: return False` means empty IDs are never deduplicated.
**How to avoid:** Log a warning when `mensaje_id` is empty. Never treat empty string as a
valid dedup key.
**Warning signs:** Multiple identical responses to same message.

### Pitfall 6: RATE_LIMIT_PER_MINUTE counter resets on restart
**What goes wrong:** Server restart resets all TTLCache counters. A user who sent 9 messages
just before restart can immediately send 10 more.
**Why it happens:** In-memory cache is not persistent.
**How to avoid:** This is acceptable for Phase 1. Document that rate limit is best-effort for
in-process restarts. If needed in future, use Redis TTL keys.
**Warning signs:** Abuse during deployment windows.

---

## Code Examples

### History limit change (TECH-01)

```python
# agent/memory.py — change ONE line
async def obtener_historial(telefono: str, limite: int = 16) -> list[dict]:
    # (was: limite: int = 6)
```

Also update the callers in `main.py` and `tests/test_local.py` if they pass `limite` explicitly.

### Whapi configuration script (one-time setup)

```python
# tools/configure_whapi_webhook.py — run once to register auth header
import httpx, os
from dotenv import load_dotenv
load_dotenv()

r = httpx.patch(
    "https://gate.whapi.cloud/settings",
    headers={
        "Authorization": f"Bearer {os.getenv('WHAPI_TOKEN')}",
        "Content-Type": "application/json",
    },
    json={"webhooks": [{
        "events": [{"type": "messages", "method": "post"}],
        "mode": "body",
        "headers": {"X-Whapi-Token": os.getenv("WHAPI_WEBHOOK_SECRET", "")},
        "url": os.getenv("WEBHOOK_URL", ""),
    }]},
)
print(r.status_code, r.text)
```

### GHL signature verification (TECH-05)

```python
# Source: https://marketplace.gohighlevel.com/docs/webhook/WebhookIntegrationGuide/index.html
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
import base64

GHL_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAi2HR1srL4o18O8BRa7gVJY7G7bupbN3H9AwJrHCDiOg=
-----END PUBLIC KEY-----"""
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GHL `X-WH-Signature` (RSA) | `X-GHL-Signature` (Ed25519) | ~2024 | Must use new header before July 1, 2026 |
| Redis-required rate limiting | In-memory limiter for single instance | Always valid | Simpler for Railway single-dyno |
| DB dedup (extra table) | TTLCache in-memory | N/A | No schema migration needed |

**Deprecated/outdated:**
- `X-WH-Signature` (GHL RSA): deprecated, removed July 1, 2026. Do not implement.
- `limite=6` in `obtener_historial`: hardcoded parameter, simply change the default.

---

## Open Questions

1. **Does Whapi actually support `headers` via PATCH `/settings`?**
   - What we know: Feature documented in Whapi help desk under "Customizable Webhook Headers"
   - What's unclear: Whether the specific `PATCH /settings` endpoint with `webhooks[].headers`
     works for the Bertero channel plan tier
   - Recommendation: Test with a single PATCH call during implementation. If unavailable, fall
     back to IP allowlist or URL-embedded token (`/webhook?token=secret`)

2. **Does GHL always send `X-GHL-Signature` on the calendar appointment webhook?**
   - What we know: GHL signs app marketplace webhooks; calendar triggers may behave differently
   - What's unclear: Whether internal calendar triggers include the signature
   - Recommendation: Implement strict=False by default (env var `GHL_WEBHOOK_AUTH_STRICT`).
     Log all GHL webhook headers during testing to confirm.

3. **What is the right `RATE_LIMIT_PER_MINUTE` default?**
   - What we know: Typical WhatsApp conversation = 2–5 msgs/min max for normal users
   - What's unclear: Whether Bertero's clients send rapid bursts (e.g., multiple images)
   - Recommendation: Default to 15/min. Configurable via env var `RATE_LIMIT_PER_MINUTE`.

---

## Sources

### Primary (HIGH confidence)
- GHL Developer Docs — `https://marketplace.gohighlevel.com/docs/webhook/WebhookIntegrationGuide/index.html` — Ed25519 public key, X-GHL-Signature header format
- Whapi Help Desk — `https://support.whapi.cloud/help-desk/account/customizable-webhook-headers` — custom headers in webhook callbacks
- cachetools PyPI — `https://pypi.org/project/cachetools/` — TTLCache API
- slowapi PyPI — `https://pypi.org/project/slowapi/` — version 0.1.9, memory backend

### Secondary (MEDIUM confidence)
- GHL Changelog — `https://ideas.gohighlevel.com/changelog/app-marketplace-security-update-webhook-authentication` — deprecation date July 1, 2026
- Whapi Webhooks Guide — `https://support.whapi.cloud/help-desk/receiving/webhooks` — webhook event format
- slowapi GitHub — `https://github.com/laurentS/slowapi` — key_func pattern

### Tertiary (LOW confidence)
- Argentina phone format: Wikipedia + multiple blog sources agree on `549` mobile pattern,
  but "15" prefix edge cases vary by region

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified via official PyPI/docs pages
- Architecture: HIGH — patterns derived from existing codebase conventions (session.py)
- Pitfalls: HIGH — derived from reading actual code (request.body double-read, phone format)
- GHL auth: HIGH — public key and method verified via official GHL developer portal
- Whapi auth: MEDIUM — custom headers documented but specific plan tier support unconfirmed

**Research date:** 2026-03-28
**Valid until:** 2026-06-28 (stable domain; GHL deprecation deadline July 1, 2026 is the key date)
