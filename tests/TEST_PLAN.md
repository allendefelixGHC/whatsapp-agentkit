# Plan de Tests — Bot WhatsApp Inmobiliaria Bertero

## Como usar este documento

**Tests manuales**: Recorrer cada caso marcando [x] cuando pase.
**Tests automatizados**: Correr `python tests/test_flows.py` — simula todas las conversaciones.

Antes de cada demo, correr los tests automatizados + revisar manualmente los casos marcados con (MANUAL).

---

## 1. CLIENTE NUEVO — Primer mensaje

| # | Caso | Entrada | Resultado esperado |
|---|------|---------|-------------------|
| 1.1 | Saludo simple | "Hola" | Se presenta como Lucia + muestra lista de opciones (operacion) |
| 1.2 | Saludo con contexto | "Hola, busco depto en alquiler" | Se presenta + avanza directo (no repite lista si ya dio info) |
| 1.3 | Mensaje sin sentido | "asdfg" | Responde con fallback amable |

## 2. CLIENTE RECURRENTE — Ya conversó antes

| # | Caso | Entrada | Resultado esperado |
|---|------|---------|-------------------|
| 2.1 | Vuelve a escribir | "Hola" | NO se presenta como Lucia, va directo a lista de opciones |
| 2.2 | Continua busqueda | "Quiero ver mas propiedades" | Retoma contexto anterior |

## 3. FLUJO COMPRAR — Camino completo

| # | Paso | Accion | Resultado esperado |
|---|------|--------|-------------------|
| 3.1 | Operacion | Seleccionar "Comprar" | Muestra lista de tipos de propiedad |
| 3.2a | Tipo: Casa | Seleccionar "Casa" | Muestra lista de AMBIENTES (no zona) |
| 3.2b | Tipo: Depto | Seleccionar "Departamento" | Muestra lista de AMBIENTES (no zona) |
| 3.2c | Tipo: Terreno | Seleccionar "Terreno" | Salta directo a ZONA (sin ambientes) |
| 3.2d | Tipo: Local | Seleccionar "Local comercial" | Salta directo a ZONA |
| 3.2e | Tipo: Sin preferencia | Seleccionar "Sin preferencia" | Salta directo a ZONA |
| 3.3 | Ambientes (si aplica) | Seleccionar "2 ambientes" | Muestra lista de ZONAS |
| 3.4a | Zona normal | Seleccionar "Nueva Cordoba" | Muestra lista de PRESUPUESTO (USD) |
| 3.4b | Zona: Todas | Seleccionar "Todas las zonas" | Muestra lista de PRESUPUESTO |
| 3.4c | Zona: Otra | Seleccionar "Otra zona" | Pregunta zona en TEXTO (no lista) |
| 3.4d | Zona custom | Escribir "Siete Soles" | Acepta sin cuestionar, avanza a presupuesto |
| 3.5a | Precio normal | Seleccionar "50-100k" | Ejecuta busqueda |
| 3.5b | Precio: Sin limite | Seleccionar "Sin limite" | Ejecuta busqueda sin filtro precio |
| 3.5c | Precio: Custom | Seleccionar "Ingresar monto" | Pregunta monto en TEXTO (no lista) |
| 3.5d | Monto custom | Escribir "75000" | Acepta y ejecuta busqueda |
| 3.6 | Resultados | (depende de datos) | Muestra propiedades + botones Ver mas/Agendar/Hablar |

## 4. FLUJO ALQUILAR — Diferencias con comprar

| # | Paso | Accion | Resultado esperado |
|---|------|--------|-------------------|
| 4.1 | Operacion | Seleccionar "Alquilar" | Muestra lista de tipos |
| 4.2 | Tipo | Seleccionar "Departamento" | Muestra ambientes |
| 4.3 | Ambientes | Seleccionar "1 ambiente" | Muestra zonas |
| 4.4 | Zona | Seleccionar "Centro" | Muestra presupuesto con ARS + USD + opciones |
| 4.5a | Precio ARS | Seleccionar "200-400k" | Ejecuta busqueda |
| 4.5b | Precio USD | Seleccionar "USD 500-1000" | Ejecuta busqueda |

## 5. RESULTADOS DE BUSQUEDA

| # | Caso | Condicion | Resultado esperado |
|---|------|-----------|-------------------|
| 5.1 | Con resultados | Hay propiedades que coinciden | Muestra max 5 + botones (Ver mas, Agendar visita, Hablar) |
| 5.2 | Con resultados relajados | No hay en zona exacta | "No encontre en [zona], pero mira estas opciones..." |
| 5.3 | Sin resultados (misma op) | SIN_RESULTADOS_OPERACION | Botones: "Agendar llamada" + "Recibir novedades". NO muestra propiedades de otra operacion |
| 5.4 | Paginacion | Click "Ver mas" | Muestra siguientes 5 propiedades |
| 5.5 | Detalle propiedad | "Contame mas de la primera" | Usa obtener_detalle_propiedad, muestra info completa |

## 6. AGENDAR VISITA (con propiedad elegida)

| # | Paso | Accion | Resultado esperado |
|---|------|--------|-------------------|
| 6.1 | Click agendar | btn_agendar_visita | Muestra lista de propiedades vistas |
| 6.2 | Elegir propiedad | Seleccionar de lista | Pide nombre + email |
| 6.3 | Dar datos | "Juan Garcia, juan@mail.com" | Registra en GHL + muestra booking link |
| 6.4 | Link valido | (verificar) | Link es de leadconnectorhq, NO Calendly |
| 6.5 | Sin busqueda previa | Click agendar sin haber buscado | "No tengo propiedades recientes, busquemos primero" |

## 7. AGENDAR LLAMADA (sin propiedad / hablar con asesor)

| # | Paso | Accion | Resultado esperado |
|---|------|--------|-------------------|
| 7.1 | Click hablar | btn_agendar_llamada | Pide nombre + email en UN mensaje |
| 7.2 | Dar datos | "Felix, felix@mail.com" | Registra en GHL + muestra booking link |
| 7.3 | Solo nombre | "Felix" | Pide email tambien |
| 7.4 | Error CRM | (simular fallo) | Muestra booking link fallback hardcoded |

## 8. RECIBIR NOVEDADES

| # | Paso | Accion | Resultado esperado |
|---|------|--------|-------------------|
| 8.1 | Click novedades | btn_recibir_novedades | Pide email |
| 8.2 | Dar email | "juan@mail.com" | Registra lead + confirma "Te vamos a avisar" |

## 9. LINKS DE PORTALES EXTERNOS

| # | Caso | Entrada | Resultado esperado |
|---|------|---------|-------------------|
| 9.1 | Link Zonaprop | (pegar link zonaprop.com.ar) | Pregunta "Es de Bertero?" con botones Si/No |
| 9.2 | Es de Bertero | Click "Si, es de Bertero" | Pide nombre + email → booking link |
| 9.3 | No es Bertero | Click "No / No se" | Ofrece buscar en catalogo o hablar con asesor |
| 9.4 | Link Fotocasa (extranjero) | (pegar link fotocasa.es) | Pregunta "Es de Bertero?" con botones |
| 9.5 | Link preview | Mensaje tipo link_preview de Whapi | Bot lo procesa (no lo ignora) |
| 9.6 | Link sin texto | Solo el URL pegado | Bot lo detecta y responde |

## 10. FOTOS / IMAGENES

| # | Caso | Entrada | Resultado esperado |
|---|------|---------|-------------------|
| 10.1 | Foto cartel Bertero | Foto con cartel "BERTERO VENDE" | Reconoce Bertero + pide direccion/zona |
| 10.2 | Foto cartel otra inmob | Foto con otro cartel | "Parece de otra inmobiliaria" + ofrece buscar |
| 10.3 | Foto propiedad sin cartel | Foto de una casa | Pregunta que necesita saber |
| 10.4 | Foto no relacionada | Foto random | "No logro identificar, contame mas" |
| 10.5 | Foto + caption | Foto + "Esta es la propiedad" | Analiza foto + usa caption como contexto |
| 10.6 (MANUAL) | Foto baja calidad | Foto borrosa | Maneja graciosamente |

## 11. CONFIRMACION POST-BOOKING (webhook GHL)

| # | Caso | Condicion | Resultado esperado |
|---|------|-----------|-------------------|
| 11.1 | Visita con propiedad | propiedad_dir no vacio | WhatsApp: "Tu visita fue confirmada" + fecha + zoom |
| 11.2 | Llamada sin propiedad | propiedad_dir vacio | WhatsApp: "Tu llamada fue confirmada" + fecha + zoom |
| 11.3 | Email cliente visita | tipo_cita=visita | Email con seccion propiedad + fecha + zoom |
| 11.4 | Email cliente consulta | tipo_cita=consulta | Email sin propiedad, solo fecha + zoom |
| 11.5 | Email vendedor | (siempre) | Email al vendedor con datos del cliente |
| 11.6 | Contacto no encontrado | contact_id vacio + email/phone invalido | Log warning, no crash |
| 11.7 | Oportunidad no encontrada | No hay opp para el contacto | Log warning, no crash |
| 11.8 (MANUAL) | WhatsApp timeout | Whapi lento | No bloquea emails (try/except independiente) |

## 12. EDGE CASES

| # | Caso | Entrada | Resultado esperado |
|---|------|---------|-------------------|
| 12.1 | Info completa de entrada | "Busco depto 2 amb en Nueva Cordoba hasta 100k" | Salta calificacion, busca directo |
| 12.2 | Cambio de opinion | En medio del flujo: "mejor alquiler" | Se adapta, no se traba |
| 12.3 | Mensaje muy largo | 2000+ caracteres | No crashea, procesa normalmente |
| 12.4 | Emojis en mensaje | "Hola 😊 busco 🏡" | Responde normalmente |
| 12.5 | Multiples mensajes rapidos | 3 mensajes seguidos | Procesa todos sin duplicar |
| 12.6 | Tasacion | Seleccionar "Tasacion" | Conecta con asesor (no busqueda) |
| 12.7 | Vender propiedad | Seleccionar "Vender" | Flujo de contacto con asesor |
| 12.8 | Info general | Seleccionar "Info general" | Responde FAQ, no inicia calificacion |
| 12.9 | Tipo exacto | Cliente dijo "casa", bot no dice "departamento" | Usa siempre el tipo que eligio |
| 12.10 | Link inventado | Bot no genera Calendly ni Google Calendar | Solo links de herramientas o hardcoded |

## 13. ERRORES Y RECUPERACION

| # | Caso | Condicion | Resultado esperado |
|---|------|-----------|-------------------|
| 13.1 | API Claude falla | Timeout o error | Muestra mensaje de error + telefono |
| 13.2 | Busqueda falla | Timeout en scraping | "La busqueda tardo, visita la web" |
| 13.3 | GHL falla | Error creando contacto | Muestra booking link fallback |
| 13.4 | Webhook GHL error | Error en notificaciones | Loguea traceback, no crashea |
