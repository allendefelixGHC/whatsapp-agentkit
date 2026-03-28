# Roadmap: Soporte Bertero v2

## Overview

Evolucionar el bot de WhatsApp de Bertero desde un MVP funcional a un sistema de produccion robusto. El camino: primero endurecer la base tecnica, luego migrar datos a Supabase para respuestas rapidas, agregar capacidades de media (audios/fotos), completar flujos de negocio faltantes, implementar human takeover, y cerrar con seguimiento automatizado post-consulta.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Technical Hardening** - Fix reliability issues: deduplication, phone normalization, webhook auth, rate limiting, longer history
- [ ] **Phase 2: Supabase Data Foundation** - Scraping profundo + Supabase como fuente de propiedades con refresh automatico via n8n
- [ ] **Phase 3: Audio & Smart Media** - Transcripcion de audios y analisis inteligente de fotos con busqueda automatica
- [ ] **Phase 4: Business Flows** - Flujos completos para tasacion, vender, alquiler y reinicio de calificacion
- [ ] **Phase 5: Human Takeover** - Estado bot/humano por conversacion con notificacion real-time al vendedor
- [ ] **Phase 6: Follow-up & Notifications** - Seguimiento post-consulta automatizado y deteccion de horario

## Phase Details

### Phase 1: Technical Hardening
**Goal**: El bot procesa mensajes de forma confiable sin duplicados, con autenticacion de webhooks y proteccion contra abuso
**Depends on**: Nothing (first phase)
**Requirements**: TECH-01, TECH-02, TECH-03, TECH-04, TECH-05, TECH-06
**Success Criteria** (what must be TRUE):
  1. Cuando Whapi reintenta un webhook, el bot no responde dos veces al mismo mensaje
  2. El bot recuerda los ultimos 16 mensajes de cada conversacion (no solo 6)
  3. Un mismo numero de telefono en distintos formatos (+54, 54, 0, sin prefijo) se resuelve siempre al mismo contacto
  4. Webhooks de origen desconocido (sin token valido de Whapi o GHL) son rechazados con 401
  5. Si un usuario envia mas de N mensajes por minuto, el bot no llama a Claude API y responde con mensaje de rate limit
**Plans**: TBD

Plans:
- [ ] 01-01: Message deduplication and phone normalization
- [ ] 01-02: Webhook authentication and rate limiting
- [ ] 01-03: Conversation history expansion

### Phase 2: Supabase Data Foundation
**Goal**: El bot responde con datos de propiedades completos y actualizados desde Supabase en menos de 1 segundo
**Depends on**: Phase 1
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05, TECH-07
**Success Criteria** (what must be TRUE):
  1. El bot muestra precio, dormitorios, banos, superficie y descripcion de cada propiedad (datos del detalle, no solo del listado)
  2. Buscar propiedades tarda menos de 1 segundo (desde Supabase, no scraping en vivo)
  3. Propiedades nuevas en la web de Bertero aparecen en el bot dentro de 1 hora (n8n refresh automatico)
  4. El precio mostrado al cliente coincide exactamente con el precio de la pagina de detalle de la propiedad
  5. Al iniciar el servidor, las propiedades ya estan cargadas en cache (warm-up desde Supabase)
**Plans**: TBD

Plans:
- [ ] 02-01: Deep scraper for Bertero website (listing + detail pages)
- [ ] 02-02: Supabase schema and data ingestion
- [ ] 02-03: Bot queries Supabase + cache warm-up
- [ ] 02-04: n8n hourly refresh workflow

### Phase 3: Audio & Smart Media
**Goal**: El bot entiende audios y fotos de los clientes y los procesa como parte natural del flujo de calificacion
**Depends on**: Phase 2
**Requirements**: AUDIO-01, AUDIO-02, IMG-01, IMG-02
**Success Criteria** (what must be TRUE):
  1. Un cliente envia un audio de 30 segundos describiendo lo que busca, y el bot responde como si hubiera escrito un mensaje de texto
  2. Un cliente envia foto de una propiedad/cartel y el bot lanza busqueda automatica sin preguntar datos adicionales
  3. Si la foto muestra un cartel de Bertero con datos visibles, el bot identifica la propiedad y ofrece agendar visita
**Plans**: TBD

Plans:
- [ ] 03-01: WhatsApp audio download and transcription pipeline
- [ ] 03-02: Smart image analysis with automatic property search

### Phase 4: Business Flows
**Goal**: Los clientes pueden completar flujos de tasacion, venta y alquiler de principio a fin, y reiniciar la calificacion en cualquier momento
**Depends on**: Phase 2
**Requirements**: BF-01, BF-02, BF-03, BF-04
**Success Criteria** (what must be TRUE):
  1. Un cliente que dice "quiero tasar mi propiedad" completa un flujo guiado (direccion, tipo, m2, antiguedad) y queda registrado como lead de captacion
  2. Un cliente que dice "quiero vender mi casa" recibe informacion sobre el servicio y queda registrado como lead vendedor
  3. Un cliente que dice "quiero poner en alquiler" recibe info del servicio de administracion y queda registrado como lead
  4. Un cliente puede decir "empezar de nuevo" o "quiero buscar otra cosa" en cualquier punto y el flujo se reinicia limpiamente
**Plans**: TBD

Plans:
- [ ] 04-01: Tasacion, venta and alquiler conversation flows
- [ ] 04-02: Flow restart and re-qualification logic

### Phase 5: Human Takeover
**Goal**: Cuando el cliente necesita un humano, el bot cede el control al vendedor asignado con contexto completo, y el vendedor puede devolverlo
**Depends on**: Phase 2
**Requirements**: HT-01, HT-02, HT-03, HT-04, HT-05
**Success Criteria** (what must be TRUE):
  1. Cuando un cliente dice "quiero hablar con alguien", el bot se pausa y deja de responder a ese cliente
  2. El vendedor asignado recibe un WhatsApp con resumen completo: nombre del cliente, que busca, propiedades vistas, presupuesto
  3. Mientras el estado es "humano", nuevos mensajes del cliente NO generan respuesta del bot
  4. El vendedor puede devolver el control al bot con un comando o despues de un timeout configurable
**Plans**: TBD

Plans:
- [ ] 05-01: Conversation state management (bot/human/closed)
- [ ] 05-02: Vendor notification and handoff with context summary
- [ ] 05-03: Return-to-bot mechanism (command + timeout)

### Phase 6: Follow-up & Notifications
**Goal**: El bot hace seguimiento automatico post-consulta y respeta horarios de atencion reales
**Depends on**: Phase 5
**Requirements**: FU-01, FU-02, FU-03
**Success Criteria** (what must be TRUE):
  1. Un cliente que vio propiedades pero no agendo recibe mensaje de seguimiento 24-48 horas despues
  2. Cada vez que se registra un lead o se hace handoff, el vendedor recibe resumen completo por WhatsApp (nombre, telefono, email, operacion, tipo, zona, presupuesto, propiedades con links)
  3. Fuera de horario (L-V despues de 18h, Sab despues de 14h, domingos) el bot responde automaticamente con el horario y registra al lead para seguimiento al dia siguiente
**Plans**: TBD

Plans:
- [ ] 06-01: Business hours detection and after-hours response
- [ ] 06-02: Vendor notification on lead registration and handoff
- [ ] 06-03: Automated follow-up scheduling via n8n

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Technical Hardening | 0/3 | Not started | - |
| 2. Supabase Data Foundation | 0/4 | Not started | - |
| 3. Audio & Smart Media | 0/2 | Not started | - |
| 4. Business Flows | 0/2 | Not started | - |
| 5. Human Takeover | 0/3 | Not started | - |
| 6. Follow-up & Notifications | 0/3 | Not started | - |
