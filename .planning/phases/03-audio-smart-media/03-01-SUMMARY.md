---
phase: 03-audio-smart-media
plan: 01
subsystem: api
tags: [openai, whisper, audio, voice, transcription, whapi, fastapi]

# Dependency graph
requires:
  - phase: 02-supabase-data-foundation
    provides: "Supabase property cache and GHL webhook integration already wired in main.py"
provides:
  - "Voice note and audio file transcription via OpenAI Whisper (whisper-1)"
  - "MensajeEntrante.audio_url and audio_mime fields for audio message routing"
  - "Whapi voice/audio webhook parsing with /media/{id} fallback"
  - "Non-blocking transcription using asyncio.to_thread"
  - "Contexto prefix preservation via rsplit on audio placeholder replacement"
affects:
  - 03-audio-smart-media (plan 02 — smart image search builds on same audio pipeline)

# Tech tracking
tech-stack:
  added: [openai>=1.0.0]
  patterns:
    - "BytesIO + .name attribute for in-memory Whisper API calls (no disk writes)"
    - "asyncio.to_thread for sync OpenAI SDK calls within async FastAPI handlers"
    - "rsplit('\\n', 1) to replace only the audio placeholder in the contexto string without destroying [CONTEXTO INTERNO] tags"

key-files:
  created: []
  modified:
    - agent/providers/base.py
    - agent/providers/whapi.py
    - agent/brain.py
    - agent/main.py
    - requirements.txt

key-decisions:
  - "asyncio.to_thread() for Whisper call — openai SDK is sync; wrapping avoids blocking the FastAPI event loop"
  - "BytesIO.name = 'audio.{ext}' is critical — Whisper API infers audio format from filename"
  - "mime.split(';')[0].strip() strips codec suffix from 'audio/ogg; codecs=opus' before MIME mapping"
  - "rsplit('\\n', 1) replaces only the last line (audio placeholder) while preserving [CONTEXTO INTERNO] and [CLIENTE NUEVO/RECURRENTE] markers"
  - "Whapi /media/{id} fallback URL used when link field is absent in voice/audio webhook payload"
  - "Failed transcription returns friendly fallback ('No pude escuchar...') rather than empty response or error"

patterns-established:
  - "In-memory audio processing: BytesIO only, never write to disk"
  - "Audio and image are parallel media paths — neither replaces the other in generar_respuesta()"

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 3 Plan 01: Audio Transcription Summary

**WhatsApp voice notes and audio files transcribed via OpenAI Whisper whisper-1, injected into the existing contexto pipeline without breaking [CONTEXTO INTERNO] tags or button/list IDs**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-28T15:02:43Z
- **Completed:** 2026-03-28T15:07:13Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Voice notes (type="voice") and audio files (type="audio") from Whapi are parsed with URL, MIME type, and duration
- Audio bytes are downloaded and transcribed in-memory via OpenAI Whisper (whisper-1) — no disk writes
- Transcription replaces only the audio placeholder (last line of contexto) preserving all [CONTEXTO INTERNO] tags, [CLIENTE NUEVO/RECURRENTE] markers, and boton/lista IDs
- Non-blocking Whisper call via asyncio.to_thread prevents event loop stall under load
- Fallback to /media/{id} URL when Whapi omits the link field in the webhook payload
- Failed transcriptions return a friendly "please type" message instead of silence

## Task Commits

Each task was committed atomically:

1. **Task 1: Add audio fields to MensajeEntrante and parse voice/audio in Whapi webhook** - `f96f1c9` (feat)
2. **Task 2: Add Whisper transcription to brain.py and wire audio through main.py** - `91429cc` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `agent/providers/base.py` - Added audio_url and audio_mime fields to MensajeEntrante dataclass
- `agent/providers/whapi.py` - Added voice/audio elif block with link extraction, MIME, duration, /media/{id} fallback
- `agent/brain.py` - Added openai import, OpenAI client, _descargar_y_transcribir_audio(), audio params and logic in generar_respuesta()
- `agent/main.py` - Updated skip condition, added audio logging branch, pass audio_url/audio_mime to generar_respuesta()
- `requirements.txt` - Added openai>=1.0.0

## Decisions Made
- **asyncio.to_thread for Whisper**: openai SDK is synchronous; wrapping in asyncio.to_thread prevents blocking FastAPI's async event loop
- **BytesIO.name is critical**: Whisper API infers audio codec from filename — without `.name = "audio.oga"` it would fail or misdetect format
- **MIME stripping**: `audio/ogg; codecs=opus` must be stripped to `audio/ogg` before the mime→ext mapping
- **rsplit instead of full replace**: Replacing only the last line of contexto (the audio placeholder) preserves all GSD-specific context tags built before the audio text
- **Fallback message on failure**: Silent failures lose leads — a friendly "please type" message keeps the conversation alive

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

**OPENAI_API_KEY must be set before audio transcription works at runtime.**

Add to `.env`:
```
OPENAI_API_KEY=sk-...your-key-here...
```

Obtain at: https://platform.openai.com/api-keys

Cost: ~$0.006/minute of audio transcribed (Whisper API pricing).

Verification after adding key:
```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); k=os.getenv('OPENAI_API_KEY',''); print('OK' if k.startswith('sk-') else 'NOT SET')"
```

## Next Phase Readiness
- Audio transcription pipeline complete and wired end-to-end
- Ready for Plan 02: Smart Image Search (03-02) — parallel media pipeline already established
- OPENAI_API_KEY needed in .env before audio features work in production

---
*Phase: 03-audio-smart-media*
*Completed: 2026-03-28*
