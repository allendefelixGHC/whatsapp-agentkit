# Requirements: Soporte Bertero v2

**Defined:** 2026-03-28
**Core Value:** El bot debe atender al cliente como lo haría el mejor asesor de Bertero: rápido, con información precisa, sin perder ningún lead, y sabiendo cuándo ceder el control a un humano.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Data & Properties

- [ ] **DATA-01**: Scraping profundo de web Bertero extrae datos completos de cada propiedad (precio real del detalle, dormitorios, baños, superficie cubierta/total, antigüedad, expensas, descripción, URLs de fotos)
- [ ] **DATA-02**: Propiedades se almacenan en Supabase con estructura normalizada y filtrable por tipo, operación, zona, precio, ambientes
- [ ] **DATA-03**: Bot consulta Supabase en vez de scraping en vivo, con respuesta <1 segundo
- [ ] **DATA-04**: n8n refresca datos de propiedades en Supabase cada hora automáticamente, detectando propiedades nuevas y removidas
- [ ] **DATA-05**: Precio mostrado al cliente coincide con el precio real de la página de detalle de la propiedad

### Audio & Media

- [ ] **AUDIO-01**: Bot recibe audios/voice notes de WhatsApp y los transcribe a texto
- [ ] **AUDIO-02**: Texto transcrito se procesa como mensaje normal del flujo de calificación
- [ ] **IMG-01**: Bot analiza foto recibida, extrae tipo de propiedad, zona/dirección visible, y lanza búsqueda automática sin preguntar al cliente
- [ ] **IMG-02**: Si la foto muestra un cartel de Bertero, el bot identifica la propiedad y ofrece agendar visita directamente

### Human Takeover

- [ ] **HT-01**: Cada conversación tiene un estado persistente: bot, humano, o cerrado
- [ ] **HT-02**: Cuando el cliente pide hablar con una persona (o equivalente), el bot se pausa y notifica al vendedor asignado
- [ ] **HT-03**: El vendedor recibe notificación real-time (WhatsApp al número del vendedor) con resumen completo del cliente: nombre, qué busca, propiedades vistas, presupuesto
- [ ] **HT-04**: Mientras el estado es "humano", el bot no responde a mensajes de ese cliente
- [ ] **HT-05**: El vendedor puede devolver el control al bot (via comando o después de X tiempo sin actividad)

### Follow-up & Notifications

- [ ] **FU-01**: Si el cliente vio propiedades pero no agendó visita, recibe mensaje de seguimiento automático a las 24-48 horas
- [ ] **FU-02**: Cuando el bot registra un lead o hace handoff, el vendedor asignado recibe resumen completo por WhatsApp con: nombre, teléfono, email, operación, tipo, zona, presupuesto, propiedades vistas con links
- [ ] **FU-03**: Detección de horario real de Bertero (L-V 9-18, Sáb 10-14). Fuera de horario: respuesta automática indicando horario + registro del lead para seguimiento al día siguiente

### Business Flows

- [ ] **BF-01**: Flujo "Tasación" — pide datos de la propiedad del cliente (dirección, tipo, m², antigüedad) y registra lead tipo captación
- [ ] **BF-02**: Flujo "Vender mi propiedad" — pide datos del inmueble, ofrece tasación y registro como lead vendedor
- [ ] **BF-03**: Flujo "Poner en alquiler" — pide datos del inmueble, ofrece información sobre el servicio de administración y registra como lead
- [ ] **BF-04**: El cliente puede reiniciar el flujo de calificación en cualquier momento ("empezar de nuevo", "quiero buscar otra cosa")

### Technical Robustness

- [ ] **TECH-01**: Historial de conversación ampliado de 6 a 16 mensajes por defecto
- [ ] **TECH-02**: Deduplicación de mensajes por mensaje_id — si Whapi reintenta webhook, no se procesa dos veces
- [ ] **TECH-03**: Normalización de teléfono centralizada en función utilitaria única usada por todos los módulos
- [ ] **TECH-04**: Autenticación de webhook de Whapi (validar header o token)
- [ ] **TECH-05**: Autenticación de webhook de GHL (validar origen)
- [ ] **TECH-06**: Rate limiting por usuario (máx N mensajes por minuto antes de llamar a Claude API)
- [ ] **TECH-07**: Cache de propiedades warm-up al iniciar el servidor (pre-cargar desde Supabase)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Tokko API Integration

- **TOKKO-01**: Migrar fuente de propiedades de scraping a GET /api/v1/property/search
- **TOKKO-02**: Registrar leads directamente en Tokko via POST /api/v1/contact
- **TOKKO-03**: Polling de contactos nuevos en Tokko para atención automática de leads de portales
- **TOKKO-04**: Respetar asignación de vendedor de Tokko en vez de round-robin propio

### Shared Inbox

- **INBOX-01**: Bandeja compartida para asesores (YCloud o Chatwoot)
- **INBOX-02**: Coexistencia WhatsApp Business App + API
- **INBOX-03**: Migración del número real de Bertero

### Advanced Features

- **ADV-01**: Llamadas de voz IA (Retell/Vapi) con las mismas herramientas del bot
- **ADV-02**: Alertas proactivas de nuevas propiedades a clientes interesados
- **ADV-03**: Lead scoring automático basado en comportamiento del cliente
- **ADV-04**: Dashboard/métricas del bot (conversaciones, conversión, abandono)
- **ADV-05**: Comparador de propiedades lado a lado
- **ADV-06**: Calculadora de financiamiento/crédito hipotecario

## Out of Scope

| Feature | Reason |
|---------|--------|
| Scraping ZonaProp | Protección Cloudflare, mismos datos que web Bertero via Tokko |
| Scraping La Voz del Interior | Bloqueado, bajo valor incremental |
| Eliminar GHL | Depende de tener API Key Tokko primero |
| Multi-idioma | Córdoba es mercado local, español argentino suficiente por ahora |
| App móvil propia | Innecesario — WhatsApp ES la app |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | — | Pending |
| DATA-02 | — | Pending |
| DATA-03 | — | Pending |
| DATA-04 | — | Pending |
| DATA-05 | — | Pending |
| AUDIO-01 | — | Pending |
| AUDIO-02 | — | Pending |
| IMG-01 | — | Pending |
| IMG-02 | — | Pending |
| HT-01 | — | Pending |
| HT-02 | — | Pending |
| HT-03 | — | Pending |
| HT-04 | — | Pending |
| HT-05 | — | Pending |
| FU-01 | — | Pending |
| FU-02 | — | Pending |
| FU-03 | — | Pending |
| BF-01 | — | Pending |
| BF-02 | — | Pending |
| BF-03 | — | Pending |
| BF-04 | — | Pending |
| TECH-01 | — | Pending |
| TECH-02 | — | Pending |
| TECH-03 | — | Pending |
| TECH-04 | — | Pending |
| TECH-05 | — | Pending |
| TECH-06 | — | Pending |
| TECH-07 | — | Pending |

**Coverage:**
- v1 requirements: 28 total
- Mapped to phases: 0
- Unmapped: 28 ⚠️

---
*Requirements defined: 2026-03-28*
*Last updated: 2026-03-28 after initial definition*
