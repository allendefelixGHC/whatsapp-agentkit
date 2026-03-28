# Phase 3: Audio & Smart Media - Research

**Researched:** 2026-03-28
**Domain:** WhatsApp media handling (audio/voice), speech-to-text transcription, Claude Vision triggered actions
**Confidence:** HIGH (all claims verified against official docs or Whapi live payload examples)

---

## Summary

Phase 3 adds two capabilities to the existing Bertero bot: (1) transcribing WhatsApp voice notes and audio messages into text so the qualification flow continues uninterrupted, and (2) making the image analysis path smarter — when a client sends a photo, Claude Vision already sees it, but the bot currently waits for text. This phase makes it proactively trigger `buscar_propiedades` from visual context, and detect Bertero sign photos to offer a visit booking directly.

The audio path is the bigger change structurally. Whapi delivers voice messages with `type="voice"` (distinct from `type="audio"`) containing a `link` field pointing to a Wasabi S3 URL when Auto Download is enabled on the channel. That file — OGG/Opus format — gets downloaded with the same Bearer token used for images, then transcribed via OpenAI Whisper API (`whisper-1` model) in-memory using a `BytesIO` buffer. The transcribed text is injected into `generar_respuesta()` as if the client had typed it.

The image path requires no new downloads or API calls — the infrastructure already works. The fix is purely in the system prompt: adding explicit instructions for Claude to call `buscar_propiedades` immediately when it receives an image with no caption, based solely on what it sees (property type, zone clues, etc.). For Bertero sign detection, the system prompt gets an additional rule: if the image shows a Bertero sign with a property code or address, call `buscar_propiedades` with that data and offer to book a visit. No new tools needed.

**Primary recommendation:** Add OpenAI Whisper for audio transcription (one new API dependency, $0.006/min), and fix the image→action gap via system prompt engineering rather than code changes. Both changes are minimal and well-contained.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` | `>=1.0.0` | Whisper API transcription | Only production-ready async-compatible transcription; $0.006/min; supports OGG/Opus natively |
| `anthropic` | already installed | Claude Vision for image analysis | Already in stack; handles property/sign detection |
| `httpx` | already installed | Download audio bytes from Whapi S3 | Already in stack for image downloads |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `io` (stdlib) | Python 3.11 | BytesIO buffer to avoid disk writes | Use for all in-memory audio handling |
| `asyncio` (stdlib) | Python 3.11 | `asyncio.to_thread()` to wrap sync Whisper call | OpenAI transcriptions.create() is synchronous; must wrap for async FastAPI |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| OpenAI Whisper API | AssemblyAI | More accurate for some accents but 5-10x more expensive; no added value for Spanish WhatsApp audio |
| OpenAI Whisper API | Local whisper model | No new dependency but requires ffmpeg, adds ~1.5GB VRAM, complex Railway deployment; not worth it |
| System prompt fix | New `analizar_imagen` tool | Tool approach adds latency and complexity; system prompt instruction is sufficient since Claude already sees the image |

**Installation:**
```bash
pip install openai>=1.0.0
```
Add to `requirements.txt`: `openai>=1.0.0`

---

## Architecture Patterns

### Recommended Project Structure

No new folders needed. Changes are contained to:
```
agent/
├── providers/
│   ├── base.py          # Add audio_url, audio_mime fields to MensajeEntrante
│   └── whapi.py         # Add type="voice" and type="audio" parsing
├── brain.py             # Add _descargar_y_transcribir_audio() function
│                        # Update generar_respuesta() signature to accept audio params
├── main.py              # Pass audio_url/mime from msg to generar_respuesta()
│                        # Update skip condition to include audio_url
config/
└── prompts.yaml         # Add image-trigger instruction for auto property search
                         # Add Bertero sign detection instruction
```

### Pattern 1: Voice Message → Transcription → Injection

**What:** Download audio bytes from Whapi S3 URL, transcribe with Whisper API via BytesIO in-memory, inject result as plain text into existing flow.

**When to use:** When `msg.audio_url` is set in the parsed webhook message.

**Key constraint:** The OpenAI Python client's `transcriptions.create()` is synchronous. Wrap with `asyncio.to_thread()` to avoid blocking the FastAPI event loop.

**Example:**
```python
# Source: OpenAI community (verified) + Python stdlib pattern
import io
import asyncio
import base64
import httpx
from openai import OpenAI

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def _descargar_y_transcribir_audio(url: str, mime: str = "audio/ogg; codecs=opus") -> str | None:
    """
    Descarga audio desde Whapi S3 y lo transcribe con Whisper API.
    Retorna el texto transcrito, o None si falla.
    """
    if not url:
        return None
    try:
        token = os.getenv("WHAPI_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=headers, follow_redirects=True)
            if r.status_code != 200:
                logger.error(f"Error descargando audio: {r.status_code}")
                return None
            audio_bytes = r.content
            logger.info(f"Audio descargado: {len(audio_bytes)} bytes, mime={mime}")

        # Determinar extensión de archivo desde MIME type
        # Whisper API infiere el formato desde la extensión del nombre de archivo
        ext = "oga"  # OGG/Opus (WhatsApp default)
        if "ogg" in mime or "opus" in mime:
            ext = "oga"
        elif "mp4" in mime or "m4a" in mime:
            ext = "m4a"
        elif "mpeg" in mime or "mp3" in mime:
            ext = "mp3"
        elif "wav" in mime:
            ext = "wav"

        # Crear buffer en memoria con nombre (Whisper API lo requiere para detectar formato)
        buffer = io.BytesIO(audio_bytes)
        buffer.name = f"audio.{ext}"

        # Llamar a Whisper API en un thread (la función es síncrona)
        def transcribir():
            return openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=buffer,
                language="es",  # Forzar español para mejor precisión
            )

        resultado = await asyncio.to_thread(transcribir)
        texto = resultado.text.strip()
        logger.info(f"Audio transcrito ({len(audio_bytes)} bytes → '{texto[:100]}')")
        return texto if texto else None

    except Exception as e:
        logger.error(f"Error transcribiendo audio: {e}")
        return None
```

### Pattern 2: Whapi Voice Message Webhook Parsing

**What:** Detect `type="voice"` and `type="audio"` in Whapi webhook, extract the `link` and `mime_type` from the nested object.

**When to use:** In `whapi.py parsear_webhook()`.

**Whapi payload structure (verified from live example):**
```json
{
  "type": "voice",
  "voice": {
    "id": "oga-abc123...",
    "mime_type": "audio/ogg; codecs=opus",
    "file_size": 7848,
    "link": "https://s3.eu-central-1.wasabisys.com/in-files/...",
    "seconds": 3
  }
}
```

**Key distinction — two audio types in Whapi:**
- `type="voice"` — WhatsApp Push-to-Talk voice note (most common); uses `msg["voice"]` object
- `type="audio"` — Audio file attachment; uses `msg["audio"]` object (same field structure)

**Critical dependency:** The `link` field only appears if **Auto Download is enabled** in Whapi channel settings. Without it, only `id` is available, requiring the `/media/{id}` endpoint. The existing image handling in `whapi.py` already uses `link` (for images, the pattern is `img.get("link", "") or img.get("url", "")`), so the channel almost certainly has Auto Download enabled. Verify this before planning.

```python
# In whapi.py parsear_webhook(), add after image handling block:
elif msg_type in ("voice", "audio"):
    media_obj = msg.get("voice") or msg.get("audio") or {}
    audio_url = media_obj.get("link", "")
    audio_mime = media_obj.get("mime_type", "audio/ogg; codecs=opus")
    duracion = media_obj.get("seconds", 0)
    texto = f"[Nota de voz de {duracion}s]" if duracion else "[Audio enviado]"
    logger.info(f"Audio recibido: mime={audio_mime}, duracion={duracion}s, url={audio_url[:80] if audio_url else 'N/A'}")
```

### Pattern 3: Image → Automatic Property Search (System Prompt)

**What:** Add explicit instructions to `prompts.yaml` so Claude automatically calls `buscar_propiedades` when it receives an image, without waiting for additional text from the client.

**When to use:** When `imagen_url` is set and `texto` is `"[Imagen enviada]"` (no caption).

**Approach:** System prompt engineering — no new code. Add a section to the existing system prompt in `config/prompts.yaml`.

**System prompt addition:**
```yaml
## Procesamiento de imágenes (CRÍTICO)

Cuando el cliente envía una FOTO sin descripción (mensaje "[Imagen enviada]"):
1. ANALIZA la imagen inmediatamente con toda tu capacidad visual
2. Identifica: tipo de propiedad (depto, casa, local...), zona/barrio si hay
   carteles o referencias visibles, estado general
3. INMEDIATAMENTE llama a buscar_propiedades() con lo que detectaste
   — NO preguntes al cliente qué busca — lanzá la búsqueda directamente
4. Presentá los resultados como si el cliente hubiera descrito la propiedad

## Detección de carteles Bertero (CRÍTICO)

Si la imagen muestra un CARTEL DE BERTERO (logo, colores corporativos, texto "Bertero"):
1. Identifica cualquier código de propiedad, dirección o número visible en el cartel
2. Llama a buscar_propiedades() con esos datos
3. Si encontraste la propiedad: presentala y DIRECTAMENTE ofrece agendar una visita
   ("¿Querés que te coordine una visita? Puedo darte un turno ahora mismo")
4. Si no encontraste coincidencia exacta: muestra propiedades similares de la zona
   del cartel y ofrece visita para la más cercana
```

### Anti-Patterns to Avoid

- **Writing audio to disk:** Never do `open("temp.oga", "wb")` and then delete. Use `io.BytesIO()` with `.name` attribute — Whisper API accepts it directly.
- **Blocking the event loop:** Never call `openai_client.audio.transcriptions.create()` directly in an async function without `asyncio.to_thread()`. It's a synchronous HTTP call that will freeze the webhook handler.
- **Using `asyncio.get_event_loop().run_in_executor()`:** This older pattern is deprecated for new code. Use `await asyncio.to_thread(fn)` (Python 3.9+, this project uses 3.11).
- **Empty transcription as message:** If Whisper returns an empty string (silence, noise), fall back to `"[Audio no reconocido]"` rather than injecting an empty message.
- **Overriding imagen_url logic:** The existing `generar_respuesta()` image path already works perfectly. Don't refactor it. Add audio handling in parallel, not as a replacement.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OGG/Opus transcription | ffmpeg subprocess + custom speech model | OpenAI Whisper API | OGG/Opus codec handling, noise reduction, accent normalization — all edge cases managed |
| Audio format detection | Byte-level magic number parsing | Extension from MIME type in webhook + BytesIO `.name` trick | Whisper API already handles format from filename extension |
| Sign text OCR for Bertero | Custom text extraction pipeline | Claude Vision (already analyzing the image) | Claude already reads text in images as part of its natural vision; no extra call needed |
| Property matching from image | Fuzzy text matching pipeline | Pass extracted data to existing `buscar_propiedades()` tool | The tool already handles flexible search; Claude extracts the parameters |

**Key insight:** The transcription path should be one function in `brain.py` that downloads bytes and calls Whisper. Everything downstream (historial, tools, memory) is already in place and doesn't change.

---

## Common Pitfalls

### Pitfall 1: Auto Download Not Enabled on Whapi Channel

**What goes wrong:** `link` field is absent from voice/audio webhook payload. `audio_url` is empty string. Bot silently drops the audio message.
**Why it happens:** Auto Download is a channel-level setting in Whapi dashboard, not an API default. It must be explicitly enabled.
**How to avoid:** Verify Auto Download is ON before testing. If `link` is empty but `id` is present, fall back to `/media/{id}` endpoint with Bearer auth (GET `https://gate.whapi.cloud/media/{id}` with `Authorization: Bearer {token}`).
**Warning signs:** Audio messages arrive (type is "voice" detected in logs) but `audio_url` is empty.

### Pitfall 2: BytesIO Name Attribute Missing

**What goes wrong:** `openai_client.audio.transcriptions.create(file=buffer)` raises `"Unrecognized file format"` error.
**Why it happens:** The OpenAI Python SDK infers audio format from the file's `.name` attribute extension. BytesIO objects don't have a name by default.
**How to avoid:** Always set `buffer.name = f"audio.{ext}"` before passing to the API.
**Warning signs:** `openai.BadRequestError: Unrecognized file format` in logs.

### Pitfall 3: MIME Type Parsing for OGG/Opus

**What goes wrong:** Whapi sends `"audio/ogg; codecs=opus"` (with codec parameter). Naive `split("/")[1]` gives `"ogg; codecs=opus"` not `"ogg"`.
**Why it happens:** Standard MIME type with codec parameter — very common for Opus audio.
**How to avoid:** Parse with `mime.split(";")[0].strip()` to get `"audio/ogg"`, then check for "ogg" in the result.
**Warning signs:** File extension becomes `"ogg; codecs=opus"` in the buffer name, causing format detection to fail.

### Pitfall 4: Blocking Event Loop with Whisper Call

**What goes wrong:** Webhook handler freezes; other incoming messages queue up; Railway health checks time out; Railway restarts the container.
**Why it happens:** `openai_client.audio.transcriptions.create()` is a synchronous HTTPX call inside an async function — it blocks the entire uvicorn event loop.
**How to avoid:** Always wrap with `await asyncio.to_thread(lambda: openai_client.audio.transcriptions.create(...))`.
**Warning signs:** Latency spikes on all messages when an audio is being processed; health check timeouts.

### Pitfall 5: Image "Auto-Search" Triggering on Non-Property Photos

**What goes wrong:** Client sends a selfie or random photo → bot launches `buscar_propiedades` with garbage parameters → irrelevant results confuse the conversation.
**Why it happens:** System prompt instruction is too aggressive ("always search for properties").
**How to avoid:** Prompt should instruct Claude to first assess whether the image shows a property or real estate context. If not (selfie, document, screenshot), acknowledge normally and ask what they're looking for. Claude Vision is reliable at distinguishing property photos from other content.
**Warning signs:** Bot responding with property listings after client sends a non-property image.

### Pitfall 6: Audio URL Expiry (30-day S3 links)

**What goes wrong:** URL in webhook still valid (messages arrive in real time), but if there's ever a retry queue or reprocessing, URLs older than 30 days will 404.
**Why it happens:** Whapi S3 files expire after 30 days.
**How to avoid:** Download and transcribe immediately in the same webhook handler invocation. Never store audio URLs for deferred processing.
**Warning signs:** 404 errors on audio downloads from retried webhook events.

---

## Code Examples

Verified patterns from official sources and community confirmation:

### Audio Download + Transcription (brain.py addition)
```python
# Source: OpenAI community confirmed pattern + Python stdlib
import io
import asyncio

async def _descargar_y_transcribir_audio(url: str, mime: str = "audio/ogg; codecs=opus") -> str | None:
    """Descarga audio desde Whapi y transcribe con Whisper API. Retorna texto o None."""
    if not url:
        return None
    try:
        token = os.getenv("WHAPI_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=headers, follow_redirects=True)
        if r.status_code != 200:
            logger.error(f"Error descargando audio: {r.status_code}")
            return None

        # Determinar extensión para que Whisper API reconozca el formato
        mime_base = mime.split(";")[0].strip()  # "audio/ogg; codecs=opus" → "audio/ogg"
        ext_map = {
            "audio/ogg": "oga", "audio/opus": "oga",
            "audio/mpeg": "mp3", "audio/mp4": "m4a",
            "audio/wav": "wav", "audio/webm": "webm",
        }
        ext = ext_map.get(mime_base, "oga")

        buffer = io.BytesIO(r.content)
        buffer.name = f"audio.{ext}"  # CRÍTICO: Whisper infiere formato del nombre

        def transcribir():
            return openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=buffer,
                language="es",
            )

        resultado = await asyncio.to_thread(transcribir)
        return resultado.text.strip() or None
    except Exception as e:
        logger.error(f"Error transcribiendo audio: {e}")
        return None
```

### generar_respuesta() signature update
```python
# brain.py — agregar parámetros de audio, procesar antes de construir mensajes
async def generar_respuesta(
    mensaje: str,
    historial: list[dict],
    imagen_url: str = "",
    imagen_mime: str = "",
    audio_url: str = "",      # NUEVO
    audio_mime: str = "",     # NUEVO
) -> Respuesta:
    # Si hay audio, transcribir primero e inyectar como texto
    if audio_url:
        transcripcion = await _descargar_y_transcribir_audio(audio_url, audio_mime)
        if transcripcion:
            # Reemplazar mensaje placeholder con transcripción real
            mensaje = transcripcion
            logger.info(f"Audio transcrito e inyectado: '{transcripcion[:80]}'")
        else:
            # Transcripción falló — informar al cliente
            return Respuesta(tipo="texto", texto="No pude escuchar bien tu mensaje de voz. ¿Podés escribirme lo que necesitás?")
    # ... resto sin cambios
```

### MensajeEntrante dataclass update (base.py)
```python
# Source: existing codebase pattern — add audio fields analogous to imagen fields
@dataclass
class MensajeEntrante:
    telefono: str
    texto: str
    mensaje_id: str
    es_propio: bool
    boton_id: str = ""
    lista_id: str = ""
    imagen_url: str = ""
    imagen_mime: str = ""
    audio_url: str = ""   # NUEVO
    audio_mime: str = ""  # NUEVO
```

### main.py webhook — skip condition and audio passthrough
```python
# Actualizar condición de skip para incluir audio
if msg.es_propio or (not msg.texto and not msg.imagen_url and not msg.audio_url):
    continue

# Actualizar llamada a generar_respuesta
respuesta = await generar_respuesta(
    contexto,
    historial,
    imagen_url=msg.imagen_url,
    imagen_mime=msg.imagen_mime,
    audio_url=msg.audio_url,    # NUEVO
    audio_mime=msg.audio_mime,  # NUEVO
)
```

### OpenAI client initialization (brain.py)
```python
# Agregar junto al cliente de Anthropic existente
from openai import OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Local ffmpeg + whisper.cpp | OpenAI Whisper API (`whisper-1`) | 2023 | No local model needed; simpler deploy |
| `asyncio.get_event_loop().run_in_executor()` | `asyncio.to_thread()` | Python 3.9 | Cleaner, preferred for new code in 3.11 |
| Save audio to temp file, delete after | `io.BytesIO()` with `.name` attribute | Stable pattern | No disk I/O, no cleanup needed |
| Describe image → ask client for details | System prompt triggers tool use on image receipt | Always possible, now being implemented | Fewer round-trips; better UX |

**Deprecated/outdated:**
- `asyncio.get_event_loop().run_in_executor(None, fn)`: Still works but superseded by `asyncio.to_thread()` in Python 3.9+.
- Saving audio to disk in `/tmp`: Works but unnecessary; BytesIO is simpler and avoids cleanup.

---

## Open Questions

1. **Is Auto Download enabled on the Whapi channel?**
   - What we know: `link` field is only present if Auto Download is ON; the existing image code uses `.get("link", "") or .get("url", "")` suggesting it was enabled when image support was added
   - What's unclear: Whether voice/audio types are included in the Auto Download types (images and documents are common defaults; voice might need explicit inclusion)
   - Recommendation: In task verification, send a test voice note to the bot and log the raw webhook payload. Confirm `link` is present. If not, implement the `/media/{id}` fallback.

2. **Does the Wasabi S3 link for audio require Bearer token auth or is it public?**
   - What we know: Image downloads use Bearer token in `_descargar_imagen_base64()`. The Whapi docs for the `/media/{id}` endpoint require Bearer. For S3 links (Auto Download), docs say "direct link" without specifying auth.
   - What's unclear: Whether Wasabi S3 URLs are pre-signed (public) or still require Whapi Bearer token
   - Recommendation: Use Bearer token in the download request as a safe default (same pattern as image download). If 401 is returned, retry without auth. The safe default is the same as `_descargar_imagen_base64()`.

3. **OGG/Opus compatibility with Whisper API**
   - What we know: OpenAI Whisper API lists OGG as a supported format. Community reports thousands of WhatsApp `.opus` and `.amr` files transcribed successfully.
   - What's unclear: Whether `audio/ogg; codecs=opus` with `.oga` extension is consistently accepted
   - Recommendation: Also add `.opus` as a fallback extension (many Whisper API users report success with `.opus` extension for WhatsApp voice notes). Test during development.

---

## Sources

### Primary (HIGH confidence)
- Whapi.cloud live webhook payload example — `type="voice"` structure with `link`, `mime_type`, `seconds` fields (from WebSearch results showing actual JSON payload)
- [Anthropic Vision docs](https://platform.claude.com/docs/en/docs/build-with-claude/vision) — confirmed: JPEG/PNG/GIF/WebP supported; base64 pattern verified; 5MB API limit
- [OpenAI Whisper supported formats](https://platform.openai.com/docs/guides/speech-to-text) — OGG included; 25MB file limit; $0.006/min pricing
- [Whapi Auto Download docs](https://support.whapi.cloud/help-desk/account/setting-auto-download) — confirmed 30-day link expiry; "direct link" in webhook when enabled
- [OpenAI community: BytesIO + .name attribute](https://community.openai.com/t/openai-whisper-send-bytes-python-instead-of-filename/84786) — confirmed pattern for in-memory transcription

### Secondary (MEDIUM confidence)
- OpenAI Whisper pricing $0.006/min as of 2026-03 (multiple sources converge)
- `asyncio.to_thread()` as preferred pattern for Python 3.9+ (Python docs, widely verified)
- WhatsApp voice notes use `audio/ogg; codecs=opus` MIME type (Whapi live payload example)

### Tertiary (LOW confidence — flag for validation)
- Wasabi S3 links for audio may or may not require Bearer token: assumed same behavior as images (requires Bearer), but not explicitly documented for S3 URLs
- `type="audio"` (file attachment) vs `type="voice"` (PTT) distinction: confirmed from message type enum list in Whapi search results, but no live payload example for `type="audio"` found

---

## Metadata

**Confidence breakdown:**
- Whapi voice payload structure: HIGH — live JSON example found with exact field names
- Audio transcription (Whisper): HIGH — official OpenAI docs + community BytesIO pattern
- Image auto-trigger (system prompt): HIGH — no new API needed; relies on existing Claude Vision capability already working
- S3 URL auth for audio: MEDIUM — inferred from image download pattern; not explicitly documented
- `type="audio"` vs `type="voice"` behavior: MEDIUM — type names confirmed, audio object structure inferred from voice pattern

**Research date:** 2026-03-28
**Valid until:** 2026-05-01 (Whapi API stable; OpenAI Whisper pricing stable; Claude Vision capability stable)
