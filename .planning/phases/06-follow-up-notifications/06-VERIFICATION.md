---
phase: 06-follow-up-notifications
verified: 2026-03-28T18:24:20Z
status: passed
score: 3/3 must-haves verified
re_verification: false
---

# Phase 6: Follow-up & Notifications Verification Report

**Phase Goal:** El bot hace seguimiento automatico post-consulta y respeta horarios de atencion reales
**Verified:** 2026-03-28T18:24:20Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Un cliente que vio propiedades pero no agendo recibe mensaje de seguimiento 24-48 horas despues | VERIFIED | buscar_propiedades() calls programar_followup() after saving results (tools.py:297-303); procesar_followups_pendientes() sends FOLLOWUP_MESSAGE (followup.py:155-183); /admin/process-followups endpoint wired in main.py:143 |
| 2 | Cuando se registra un lead o se hace handoff el vendedor recibe resumen completo por WhatsApp | VERIFIED | construir_mensaje_lead() in takeover.py:96 formats all FU-02 fields; notification injected in registrar_lead_ghl() success path (tools.py:653-679) using VENDEDOR_WHATSAPP; presupuesto conveyed via resumen |
| 3 | Fuera de horario el bot responde automaticamente con horario y registra al lead para seguimiento | VERIFIED | esta_en_horario() in business_hours.py:39 checks America/Argentina/Cordoba timezone; gate in main.py:222 sends AFTER_HOURS_MESSAGE and calls programar_followup(); BUSINESS_HOURS_ENABLED toggles gate |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| agent/business_hours.py | Timezone-aware business hours detection | VERIFIED | 68 lines; exports esta_en_horario() + AFTER_HOURS_MESSAGE; ZoneInfo(America/Argentina/Cordoba) with correct HORARIOS dict |
| agent/memory.py FollowUpSchedule | FollowUpSchedule SQLAlchemy model | VERIFIED | class FollowUpSchedule(Base) at line 55; fields: id, telefono (indexed), status, propiedades_json, scheduled_at, created_at, updated_at |
| agent/main.py gate+endpoint | After-hours gate + /admin/process-followups | VERIFIED | Gate at line 222 correct ordering (after rate limit line 216, before takeover line 238); endpoint at line 143 with admin auth |
| agent/followup.py | Follow-up CRUD: programar, cancelar, procesar | VERIFIED | 193 lines; 3 async functions; upsert in programar_followup; per-item try/except in procesar_followups_pendientes |
| agent/takeover.py construir_mensaje_lead | Lead registration notification builder | VERIFIED | construir_mensaje_lead() at line 96; formats nombre, telefono, email, operacion, tipo, zona, resumen, propiedad + link |
| agent/tools.py follow-up wiring | Trigger in buscar_propiedades + cancellation in registrar_lead_ghl + solicitar_humano | VERIFIED | programar_followup at line 299; cancelar_followup at lines 683 and 821 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| agent/main.py | agent/business_hours.py | from agent.business_hours import esta_en_horario, AFTER_HOURS_MESSAGE | WIRED | Import at line 28; used in gate at line 222 |
| agent/main.py | after-hours gate | if BUSINESS_HOURS_ENABLED and not esta_en_horario() | WIRED | Env var at line 72; gate condition at line 222 |
| agent/main.py | programar_followup lazy | from agent.followup import programar_followup in try/except ImportError | WIRED | main.py:225 inside try/except ImportError |
| agent/memory.py | FollowUpSchedule table | SQLAlchemy model in Base | WIRED | Class at memory.py:55; created by inicializar_db() via Base.metadata.create_all |
| agent/tools.py | construir_mensaje_lead | from agent.takeover import construir_mensaje_lead | WIRED | Lazy import at tools.py:657; called at tools.py:661 |
| agent/tools.py registrar_lead_ghl | proveedor.enviar_mensaje | WhatsApp send in success path | WIRED | prv.enviar_mensaje(vendedor_wa, msg_lead) at tools.py:674 |
| agent/tools.py buscar_propiedades | programar_followup | schedule follow-up after property search | WIRED | await programar_followup at tools.py:299-301 |
| agent/tools.py registrar_lead_ghl | cancelar_followup | cancel follow-up when lead books | WIRED | await cancelar_followup(telefono) at tools.py:684 |
| agent/tools.py solicitar_humano | cancelar_followup | cancel follow-up on human handoff | WIRED | await cancelar_followup(telefono) at tools.py:822 |
| agent/main.py /admin/process-followups | procesar_followups_pendientes | n8n hourly trigger | WIRED | await procesar_followups_pendientes() at main.py:153-154 |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|---------|
| FU-01: Cliente que vio propiedades pero no agendo recibe follow-up 24-48h | SATISFIED | buscar_propiedades schedules via programar_followup; procesar_followups_pendientes sends; cancels on lead or handoff |
| FU-02: Lead registration/handoff triggers full vendor WhatsApp summary | SATISFIED | construir_mensaje_lead + injection in registrar_lead_ghl success path with all FU-02 fields |
| FU-03: After-hours detection with auto-response + next-day follow-up registration | SATISFIED | esta_en_horario() with Cordoba timezone; gate in webhook_handler; AFTER_HOURS_MESSAGE sent; programar_followup called |

### Anti-Patterns Found

No anti-patterns in phase 06 code. The except ImportError pass at main.py:229 is intentional graceful degradation (followup.py is wave 2; gate needed to work before it existed). All return {} occurrences found by scan are in pre-existing code (scraper.py, ghl.py) unrelated to this phase.

### Human Verification Required

#### 1. After-hours gate fires at correct clock time

**Test:** Set BUSINESS_HOURS_ENABLED=true, send a message after 18:00 Cordoba time (UTC-3) on a weekday
**Expected:** Bot responds with AFTER_HOURS_MESSAGE (horario + website link), does NOT call Claude API
**Why human:** Cannot verify timezone behavior without running app at specific wall-clock time

#### 2. Follow-up WhatsApp delivery

**Test:** Search properties as a client, set FOLLOWUP_DELAY_HOURS=0, trigger POST /admin/process-followups with admin token
**Expected:** Client receives FOLLOWUP_MESSAGE from bot; follow-up status changes to sent in DB
**Why human:** Requires real WhatsApp integration to verify actual delivery

#### 3. Vendor notification content on lead registration

**Test:** Complete lead qualification flow where Claude calls registrar_lead_ghl() with VENDEDOR_WHATSAPP set
**Expected:** Vendor receives WhatsApp with all FU-02 fields including presupuesto context in resumen field
**Why human:** Requires real WhatsApp delivery and device-level message formatting verification

### Gaps Summary

No gaps found. All three success criteria are fully implemented with substantive, wired code:

- agent/business_hours.py correctly implements Argentina/Cordoba timezone detection with HORARIOS dict (Mon-Fri 9-18, Sat 10-14, Sun closed)
- The after-hours gate is in the correct position: after rate limiting (line 216) and before takeover gate (line 238)
- construir_mensaje_lead() covers all FU-02 required fields; presupuesto is conveyed via resumen (documented design decision)
- agent/followup.py implements complete follow-up lifecycle with DB persistence, upsert pattern, and humano-state skipping
- All wiring verified: trigger in buscar_propiedades, cancellation in registrar_lead_ghl and solicitar_humano, processing endpoint in main.py
- n8n integration documented as manual setup step (cannot auto-provision external workflows)

---

_Verified: 2026-03-28T18:24:20Z_
_Verifier: Claude (gsd-verifier)_
