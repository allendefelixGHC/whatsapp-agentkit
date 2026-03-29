---
status: testing
phase: 06-follow-up-notifications
source: [06-01-SUMMARY.md, 06-02-SUMMARY.md, 06-03-SUMMARY.md]
started: 2026-03-28T19:00:00Z
updated: 2026-03-29T11:00:00Z
---

## Current Test

number: 1
name: After-Hours — Bot 24/7
awaiting: user response

## Tests

### 1. After-Hours — Bot 24/7
expected: Fuera de horario (hoy domingo), el bot responde normalmente con todo el flujo (propiedades, precios, visitas). Si el cliente pide "hablar con asesor", NO hace takeover sino que notifica por email+WhatsApp y confirma que lo van a contactar.
result: [pending]

### 2. Filtro de ambientes exacto
expected: Buscar "departamento 3 ambientes" retorna SOLO propiedades con exactamente 3 ambientes. No 2 ni 4.
result: [pending]

### 3. Relajacion de filtros coherente
expected: Si no hay deptos de 3 ambientes en 50-100k, el bot relaja precio primero (muestra deptos de 3 amb en precios cercanos), NO muestra casas ni deptos de otros ambientes como primera opcion.
result: [pending]

### 4. "Ver mas" solo con paginacion real
expected: Si hay 4 o menos resultados, NO aparece boton "Ver mas". Solo aparece si hay mas propiedades por mostrar.
result: [pending]

### 5. Solicitar asesor — Email + WhatsApp
expected: Al pedir "hablar con asesor", el bot pide nombre (si no lo sabe), luego envia email a hola@propulsar.ai y WhatsApp al bot, y confirma al cliente sin booking link.
result: [pending]

### 6. Datos CRM — No re-pedir nombre
expected: Si el cliente ya esta registrado en GHL (ya dio nombre/email antes), el bot NO vuelve a pedir esos datos al solicitar asesor. Los usa directo.
result: [pending]

### 7. Follow-up scheduled after property search
expected: Cuando un cliente busca propiedades, se programa automaticamente un follow-up a 24h. Verificable en /admin/process-followups.
result: [pending]

### 8. Follow-up cancelled on lead or handoff
expected: Cuando un cliente se registra como lead o pide hablar con asesor, cualquier follow-up pendiente se cancela.
result: [pending]

### 9. Process follow-ups endpoint
expected: POST /admin/process-followups procesa follow-ups vencidos y envia WhatsApp de re-engagement.
result: [pending]

## Summary

total: 9
passed: 0
issues: 0
pending: 9
skipped: 0

## Gaps

[none yet]
