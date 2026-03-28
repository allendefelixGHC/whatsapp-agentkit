# Soporte Bertero v2 — Bot WhatsApp Inmobiliaria

## What This Is

Evolución integral del bot de WhatsApp de Inmobiliaria Bertero (Córdoba, Argentina). El bot actual califica leads, busca propiedades via scraping y registra oportunidades en GHL. Esta versión migra la fuente de datos a Supabase, agrega capacidades faltantes (audios, human takeover, seguimiento post-consulta, flujos completos para todas las operaciones) y resuelve problemas técnicos que impiden escalar a producción real.

## Core Value

El bot debe atender al cliente como lo haría el mejor asesor de Bertero: rápido, con información precisa, sin perder ningún lead, y sabiendo cuándo ceder el control a un humano.

## Requirements

### Validated

- ✓ Flujo de calificación estructurado con listas interactivas (operación → tipo → ambientes → zona → presupuesto → búsqueda) — existing
- ✓ Búsqueda de propiedades en tiempo real con auto-relajación de filtros — existing
- ✓ Registro de leads en CRM (GHL) con contacto + oportunidad — existing
- ✓ Link de booking pre-poblado con nombre, email, teléfono — existing
- ✓ Manejo de "sin resultados" honesto (nunca cruza operaciones) — existing
- ✓ Asignación de vendedor por zona — existing
- ✓ Soporte de imágenes via Claude Vision — existing
- ✓ Confirmación por WhatsApp post-agendamiento con fecha, Zoom link y contexto — existing
- ✓ Notificación email al vendedor y cliente via n8n — existing
- ✓ Manejo de links de portales inmobiliarios (ZonaProp, etc.) — existing
- ✓ Proveedor WhatsApp agnóstico (capa providers/) — existing

### Active

**Datos y propiedades:**
- [ ] Scraping profundo web Bertero (listado + detalle) → Supabase
- [ ] Bot consulta Supabase en vez de scraping en vivo (respuesta <1s)
- [ ] n8n refresca datos de propiedades cada hora
- [ ] Precio real desde página de detalle (fix bug precios inconsistentes)
- [ ] Datos enriquecidos: dormitorios, baños, superficie cubierta/total, antigüedad, expensas, descripción, fotos

**Nuevas capacidades del bot:**
- [ ] Transcripción de audios de WhatsApp (cultura argentina de voice notes)
- [ ] Imágenes inteligentes — extraer info de la foto y buscar propiedad automáticamente sin preguntar
- [ ] Human takeover — estado bot/humano por conversación, bot se pausa cuando humano toma control
- [ ] Notificación real-time al vendedor cuando el bot hace handoff o entra lead caliente
- [ ] Seguimiento post-consulta automatizado (24-48hs después)
- [ ] Flujos completos para tasación, vender y poner en alquiler (hoy no llevan a nada útil)
- [ ] Detección de horario real (fuera de horario: respuesta automática + registro para el día siguiente)
- [ ] "Empezar de nuevo" / reiniciar flujo de calificación
- [ ] Resumen completo al vendedor con contexto de lo que buscó el cliente

**Robustez técnica:**
- [ ] Historial de conversación más largo (hoy 6 mensajes, debería ser 12-16)
- [ ] Deduplicación de mensajes (evitar respuestas dobles por webhook retry)
- [ ] Normalización de teléfono centralizada (evitar duplicación contactos)
- [ ] Autenticación de webhooks (validar origen de Whapi y GHL)
- [ ] Rate limiting por usuario (protección contra spam/abuso)
- [ ] Cache warm-up al iniciar servidor

### Out of Scope

- Migración a API de Tokko Broker — pendiente de API Key del cliente, se hará como fase futura
- Registro de leads en Tokko (POST /contact) — misma dependencia de API Key
- Polling de leads nuevos desde Tokko — misma dependencia
- Scraping de ZonaProp — protección Cloudflare, mismos datos que web Bertero
- Scraping de La Voz del Interior — bloqueado, bajo valor incremental por ahora
- Bandeja compartida (YCloud/Chatwoot) — decisión pendiente con el cliente, el bot es agnóstico
- Migración/coexistencia del número real de Bertero — decisión pendiente
- Eliminar GHL — se evalúa cuando se tenga acceso a API Tokko
- Llamadas de voz IA (Retell/Vapi) — fase futura, alto valor pero alta complejidad
- Dashboard/métricas del bot — fase futura
- Alertas de nuevas propiedades a clientes interesados — fase futura
- Comparador de propiedades — fase futura
- Calculadora de financiamiento — fase futura
- Multi-idioma — fase futura
- Lead scoring — fase futura, se puede hacer básico con Airtable

## Context

### Ecosistema real de Bertero

Bertero opera con **Tokko Broker** como su CRM principal. Tokko está sincronizado con ZonaProp y la web de Bertero. La Voz del Interior NO está sincronizada con Tokko. Las consultas llegan por 3 canales: portales web (Tokko), La Voz (manual), carteles en la calle (WhatsApp/llamada directa).

Los asesores hoy trabajan dentro de Tokko para ver consultas asignadas, pero responden a los clientes desde sus WhatsApp personales. No hay centralización de conversaciones ni seguimiento automatizado. Si un asesor está ocupado o se enferma, el lead espera.

### Estado actual del bot

El bot corre sobre Whapi con un número de test de Propulsar. Usa Claude Haiku para generar respuestas con tool_use. Scrapea la web de Bertero con regex sobre HTML (frágil, precios inconsistentes). Registra leads en GHL (CRM de Propulsar, invisible para Bertero). Tiene flujo de calificación completo para compra/alquiler pero no para tasación/venta/poner en alquiler.

### Documentación de referencia

- Documento de Bertero (28/03/2026): muestra flujo de consultas en Tokko, asignación de asesores, portales, y pain points
- Análisis de codebase (27/03/2026): 7 documentos en `.planning/codebase/` con arquitectura, stack, concerns, integrations
- Análisis de mejoras (25/03/2026): 9 mejoras funcionales identificadas (algunas ya implementadas)
- Conversación con Claude AI: análisis de integración con ecosistema Tokko, coexistencia WhatsApp, YCloud vs Chatwoot

### Decisiones pendientes con Bertero

1. **API Key de Tokko** — sin ella no se puede migrar scraping ni registrar leads directo en Tokko
2. **Plataforma de bandeja compartida** — YCloud (coexistencia, $129/mes 10 users) vs Chatwoot (self-hosted, gratis) vs otras
3. **Número de WhatsApp** — migración/coexistencia del número real vs seguir con test
4. **Cantidad de asesores** — define el plan de la plataforma elegida
5. **GHL** — mantener como complemento o eliminar cuando se tenga Tokko API

## Constraints

- **Sin API Key Tokko**: Las fases que dependen de Tokko API se difieren. Scraping de la web de Bertero sigue siendo la fuente hasta tener la key.
- **Número de test**: Todo el desarrollo se hace sobre Whapi con número de Propulsar. El bot es agnóstico del proveedor.
- **Supabase**: Se usa como base de datos de propiedades. Free tier suficiente (500MB, 50K rows).
- **n8n**: Automatizaciones (refresco propiedades, seguimiento, notificaciones) se ejecutan en n8n. Requiere VPS.
- **Modelo IA**: Claude Haiku para respuestas (costo bajo), con opción de escalar a Sonnet para casos complejos.
- **Idioma**: Todo en español argentino (vos). El bot se llama Lucía.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Supabase como fuente de propiedades | Scraping en vivo es lento (5-8s) y frágil. Supabase da respuesta <1s y datos más ricos | — Pending |
| Scraping profundo web Bertero (no ZonaProp/La Voz) | Web de Bertero no bloquea, tiene todas las propiedades. ZonaProp tiene Cloudflare. La Voz aporta poco valor incremental | — Pending |
| Mantener GHL por ahora | No tenemos API Key de Tokko aún. GHL sigue funcionando para registro de leads | — Pending |
| No incluir bandeja compartida en este scope | Decisión depende de Bertero (YCloud vs Chatwoot). El bot es agnóstico | — Pending |
| Human takeover como estado en DB | Simple flag por conversación (bot/humano/cerrado). No depende de la plataforma de inbox | — Pending |
| n8n para refresco de propiedades | Separar scraping pesado del bot. n8n maneja retries, scheduling y carga a Supabase | — Pending |

---
*Last updated: 2026-03-28 after deep questioning and ecosystem analysis*
