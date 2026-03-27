# Codebase Concerns

**Analysis Date:** 2026-03-27

---

## Tech Debt

**Historial truncado a 6 mensajes — demasiado bajo para flujos multi-paso:**
- Issue: `obtener_historial()` tiene `limite=6` por defecto (docstring dice 20). El flujo de calificación toma 5-6 turnos solo para calificar (saludo → operación → tipo → ambientes → zona → precio), lo que deja al agente sin contexto temprano de la conversación.
- Files: `agent/memory.py:63`
- Impact: El agente puede olvidar la operación o tipo elegido en el inicio y regresar a preguntas ya respondidas.
- Fix approach: Aumentar el default a al menos 12-16. `brain.py` ya tiene lógica para recortar los mensajes largos internamente (`historial[-16:]`), por lo que el cuello de botella real está en `memory.py`.

**`_round_robin_counter` en memoria de proceso — no persiste entre reinicios:**
- Issue: En `agent/ghl.py:71-92`, el contador round-robin de asignación de vendedores es una variable global en memoria del proceso. Se resetea a 0 con cada reinicio del servidor.
- Files: `agent/ghl.py:71`
- Impact: Desequilibrio de distribución de leads al reiniciar (ej. Railway reinicia el container en cada deploy).
- Fix approach: Persistir el contador en SQLite o simplificar a hash del teléfono para asignación determinística.

**`limpiar_cache_expirado()` en `session.py` nunca se llama:**
- Issue: La función `limpiar_cache_expirado()` existe en `agent/session.py:43` pero no hay ninguna invocación en el codebase. El dict `_cache` en memoria crece sin límite superior.
- Files: `agent/session.py:43`
- Impact: Con tráfico alto, el proceso acumula entradas de sesión viejas en memoria indefinidamente.
- Fix approach: Invocar `limpiar_cache_expirado()` desde el lifespan de FastAPI usando `asyncio.create_task` con un loop periódico, o en cada llamada a `obtener_propiedades()`.

**`email_service.py` es código muerto:**
- Issue: `agent/email_service.py` implementa envío de email via SMTP, pero no es importado en ningún otro módulo del proyecto. La funcionalidad de email se delegó a n8n via webhook.
- Files: `agent/email_service.py`
- Impact: Código mantenible que no se ejecuta; puede confundir a futuros contribuidores.
- Fix approach: Eliminar el archivo o documentar explícitamente que es un fallback no activo.

**`obtener_horario()` siempre retorna `esta_abierto: True`:**
- Issue: En `agent/tools.py:70`, el campo `esta_abierto` es hardcodeado como `True`. El comentario `# TODO: calcular según hora actual y horario` fue eliminado pero la lógica real nunca se implementó.
- Files: `agent/tools.py:65-71`
- Impact: El agente no puede informar correctamente si está fuera de horario. La lógica de "fuera de horario" definida en el system prompt de `config/prompts.yaml` no se aplica automáticamente.
- Fix approach: Implementar parsing del string de horario de `business.yaml` y comparar contra la hora actual en zona horaria Argentina (`America/Argentina/Cordoba`).

**`buscar_en_knowledge()` no está expuesta como tool en `TOOLS_DEFINITION`:**
- Issue: La función `buscar_en_knowledge()` en `agent/tools.py:74` existe pero no aparece en `TOOLS_DEFINITION`. Claude no puede invocarla como herramienta.
- Files: `agent/tools.py:74`
- Impact: La carpeta `/knowledge` existe pero su contenido nunca es consultado en tiempo de ejecución. El conocimiento sobre el negocio solo llega via el system prompt de `prompts.yaml`.
- Fix approach: Agregar `buscar_en_knowledge` al array `TOOLS_DEFINITION` si se quiere búsqueda dinámica, o documentar que es intencional que solo se use el system prompt.

---

## Security Considerations

**El endpoint `/webhook/ghl` no tiene autenticación:**
- Risk: Cualquier actor externo puede llamar a `POST /webhook/ghl` con datos fabricados y mover oportunidades en el CRM o hacer que se envíen mensajes de WhatsApp a cualquier teléfono.
- Files: `agent/main.py:141-304`
- Current mitigation: Ninguna. El endpoint acepta cualquier payload JSON.
- Recommendations: Agregar validación de IP de origen (GHL publica sus IPs) o un token secreto en un header customizado (`X-GHL-Webhook-Secret`) verificado antes de procesar.

**El endpoint `/webhook` principal tampoco valida el origen de Whapi:**
- Risk: Cualquiera puede POST a `/webhook` con mensajes fabricados, inyectando conversaciones o datos falsos al agente.
- Files: `agent/main.py:76-138`, `agent/providers/whapi.py:30-130`
- Current mitigation: Ninguna verificación de firma o token para el webhook de Whapi.
- Recommendations: Whapi soporta un `channel_id` de verificación. Validar el header `X-WHAPI-TOKEN` en el webhook handler.

**GHL IDs de pipeline, stages y custom fields hardcodeados en código fuente:**
- Risk: Los IDs internos del CRM (`PIPELINE_ID`, `STAGES`, `CF_*`) están hardcodeados en `agent/ghl.py`. Si el CRM cambia, hay que editar y redesplegar código. También quedan expuestos en el repositorio git.
- Files: `agent/ghl.py:24-49`
- Current mitigation: Los IDs por sí solos no son credenciales de acceso, pero revelan la estructura interna del CRM.
- Recommendations: Mover estos valores a variables de entorno o a un archivo de config separado que no se commitee.

**Contexto interno inyectado en el mensaje de usuario puede filtrarse:**
- Risk: En `agent/main.py:107-116`, se construye un bloque `[CONTEXTO INTERNO - NO MOSTRAR AL CLIENTE]` que se pasa al modelo junto al mensaje del usuario. Si Claude no respeta la instrucción, puede reproducir el teléfono u otros datos internos al cliente.
- Files: `agent/main.py:107-116`
- Current mitigation: El prompt instruye a Claude a no mostrar el bloque. Es una convención frágil.
- Recommendations: Pasar el contexto interno via el campo `system` en lugar del campo `user` cuando sea posible, o usar un prefijo que Claude no pueda reproducir por diseño.

---

## Performance Bottlenecks

**`obtener_detalle_propiedad()` hace hasta 4 requests HTTP en cadena:**
- Problem: Para obtener el detalle de una propiedad, la función primero busca el slug en hasta 4 páginas de listado (requests secuenciales), luego hace un 5to request al detalle. Latencia total: 2-8 segundos en cada llamada.
- Files: `agent/tools.py:293-335`
- Cause: La URL de detalle requiere el slug completo (no solo el ID), pero el ID viene del listado. No hay endpoint de detalle por ID.
- Improvement path: Guardar el mapa `{id: link_completo}` durante `buscar_propiedades()` para que `obtener_detalle_propiedad()` pueda ir directamente sin re-escanear el listado.

**`buscar_propiedades()` descarga 4 páginas de HTML de scraping en cada cache miss:**
- Problem: El cache TTL es 10 minutos. Al expirar, el próximo mensaje de cualquier usuario dispara 4 requests HTTP a `inmobiliariabertero.com.ar` en serie antes de poder responder.
- Files: `agent/tools.py:120-136`
- Cause: No hay warm-up del cache al arrancar el servidor. El primer usuario después de cada 10 minutos experimenta latencia alta.
- Improvement path: Pre-cargar el cache durante el `lifespan` de FastAPI al iniciar, y refrescar en background con `asyncio.create_task`.

**El agente hace 2 llamadas a la API de Claude por cada mensaje que use una herramienta:**
- Problem: El flujo en `brain.py` siempre requiere una segunda llamada a Claude después de ejecutar cualquier herramienta de datos. Con modelo `claude-haiku-4-5`, esto es rápido, pero duplica costos y latencia para operaciones comunes como búsqueda de propiedades.
- Files: `agent/brain.py:270-354`
- Cause: Diseño de tool_use loop que siempre hace follow-up. Es el comportamiento estándar de Anthropic tool_use.
- Improvement path: Para herramientas puramente interactivas (`enviar_botones`, `enviar_lista`), retornar sin segunda llamada (ya está implementado para el caso de respuesta interactiva en la primera llamada, pero no para la segunda).

---

## Fragile Areas

**HTML scraping de `inmobiliariabertero.com.ar` — completamente frágil:**
- Files: `agent/tools.py:338-479`
- Why fragile: Toda la lógica de listado y detalle de propiedades usa regex sobre HTML. Cualquier cambio en el HTML del sitio (nuevo template, cambio de estructura de slugs, CDN que cambia URLs) rompe la búsqueda silenciosamente. Los patrones regex como `r'href="(/p/(\d+)-([^"]+))"'` dependen del formato exacto de URL actual.
- Safe modification: No modificar los regex de parseo sin primero verificar contra el HTML actual del sitio. Agregar logs del HTML parseado en modo DEBUG para detectar regresiones.
- Test coverage: No hay tests que validen el parseo de HTML real. Los tests en `test_flows.py` usan respuestas de Claude, no verifican el scraping directamente.

**Lógica de normalización de teléfono argentino duplicada en dos lugares:**
- Files: `agent/ghl.py:122-124`, `agent/main.py:249-251`
- Why fragile: La transformación `549XXXXXXXXXX → 54XXXXXXXXXX` (para GHL) y `54XXXXXXXXXX → 549XXXXXXXXXX` (para WhatsApp) se implementan independientemente en dos módulos. Una lógica asume el formato de WhatsApp, la otra el de GHL. Si el formato de entrada cambia (ej. Whapi cambia cómo envía el número), puede romperse solo en un lugar.
- Safe modification: Centralizar en una función `normalizar_telefono(tel, destino="whatsapp"|"ghl")` en un módulo utilitario.

**`_config_cache` en `brain.py` es global y no se invalida:**
- Files: `agent/brain.py:39-52`
- Why fragile: El system prompt se cachea en memoria al primer uso y nunca se refresca. Si se edita `config/prompts.yaml` en producción, el cambio no se aplica hasta reiniciar el servidor.
- Safe modification: Aceptable para producción normal, pero documentar este comportamiento. Si se necesita hot-reload, agregar un endpoint `/admin/reload-config` protegido.

**Parsing de fecha ISO 8601 de GHL con `.replace("Z", "+00:00")` es frágil:**
- Files: `agent/main.py:231`
- Why fragile: GHL puede enviar fechas en varios formatos (`2026-03-26T14:30:00Z`, `2026-03-26T14:30:00+00:00`, `2026-03-26T14:30:00`). El código maneja solo algunos. Si el formato cambia, el `try/except` silencia el error y usa el valor raw, lo cual puede mostrar ISO en el mensaje de WhatsApp al cliente.
- Safe modification: Usar `dateutil.parser.parse()` (más robusto) o al menos probar los 3 formatos conocidos explícitamente.

---

## Scaling Limits

**SQLite en producción Railway — no es escalable:**
- Current capacity: SQLite funciona bien hasta ~100-500 conversaciones activas simultáneas.
- Limit: SQLite no soporta escrituras concurrentes. Con múltiples workers Uvicorn o dos instancias Railway, ocurrirán errores `database is locked`.
- Scaling path: Migrar a PostgreSQL (Railway ofrece uno incluido). El código ya tiene soporte en `memory.py:22-23` para `postgresql+asyncpg://`, solo requiere configurar `DATABASE_URL`.

**`_propiedades_cache` y `_cache` de sesión son in-process — no se comparten entre instancias:**
- Current capacity: Funciona bien con 1 instancia.
- Limit: Si Railway escala a 2+ instancias, cada una tiene su propio cache. Un usuario puede recibir respuestas inconsistentes según qué instancia procesa su request.
- Scaling path: Para el cache de propiedades, agregar Redis o simplemente reducir el TTL. Para el cache de sesión (`session.py`), migrar a una tabla SQLite/PostgreSQL o Redis.

---

## Dependencies at Risk

**Dependencias sin versiones fijadas (solo límites inferiores):**
- Risk: `requirements.txt` usa `>=` para todas las dependencias. Un `pip install` en 6 meses puede instalar versiones con breaking changes.
- Files: `requirements.txt`
- Impact: Build reproduccibility comprometida. `anthropic>=0.40.0` puede instalar `0.50.0` con API diferente.
- Migration plan: Generar un `requirements.lock` con `pip freeze > requirements.lock` y usarlo en el Dockerfile.

**Scraping sin dependencia oficial de API Tokko Broker:**
- Risk: La web de Inmobiliaria Bertero usa Tokko Broker como CMS. Tokko Broker tiene una API REST oficial, pero el código hace scraping HTML en lugar de usar la API.
- Impact: Si Tokko cambia el template HTML o agrega protección anti-bot (Cloudflare), el scraping falla completamente.
- Migration plan: Investigar si Bertero tiene acceso a la API de Tokko Broker (`api.tokkoBroker.com`). Migrar `buscar_propiedades()` a llamadas REST con autenticación.

---

## Missing Critical Features

**No hay deduplicación de mensajes — el mismo webhook puede procesarse dos veces:**
- Problem: Si Whapi reintenta el webhook (timeout, error 5xx), el mismo mensaje del cliente se procesa dos veces: el agente responde dos veces y guarda el mensaje dos veces en memoria.
- Blocks: Confiabilidad en producción con clientes activos.
- Recommended fix: Guardar `mensaje_id` en DB al recibirlo y verificar antes de procesar. Si ya existe, retornar `{"status": "ok"}` sin procesar.

**No hay límite de rate por usuario — posible abuso:**
- Problem: Un usuario puede enviar mensajes rápidamente y generar decenas de llamadas a la API de Anthropic y GHL en segundos.
- Blocks: Control de costos y protección contra spam.
- Recommended fix: Implementar un simple rate limit en memoria (máx N mensajes por usuario por minuto) antes de llamar a `generar_respuesta()`.

**No hay gestión de conversaciones muy largas:**
- Problem: El historial en SQLite crece indefinidamente por usuario. No hay archivado, compresión ni límite total de mensajes almacenados.
- Blocks: A largo plazo, las queries se hacen lentas y el almacenamiento crece sin control.
- Recommended fix: Agregar un `DELETE` de mensajes con más de X días en el lifespan o con un job periódico.

---

## Test Coverage Gaps

**Tests no verifican el scraping de propiedades real:**
- What's not tested: `_parsear_listado()`, `_parsear_detalle()`, `buscar_propiedades()` con respuestas HTTP reales.
- Files: `agent/tools.py:338-479`, `tests/test_flows.py`
- Risk: Si cambia el HTML del sitio, los tests de flujo siguen pasando (Claude responde con error genérico) pero el scraping está roto.
- Priority: High

**Tests no verifican la integración con GHL:**
- What's not tested: `crear_o_actualizar_contacto()`, `crear_oportunidad()`, `mover_oportunidad()` no tienen tests unitarios ni mocks.
- Files: `agent/ghl.py`, `tests/`
- Risk: Cambios en la API de GHL o en los IDs de custom fields rompen el registro silenciosamente (el error se logea pero el agente confirma al cliente que fue registrado).
- Priority: High

**Tests de flujo usan historial real de SQLite — pueden interferir entre runs:**
- What's not tested: Aislamiento entre runs del test suite. Los tests usan timestamps en el teléfono para separar sesiones, pero si el DB tiene datos residuales de runs anteriores, puede haber contaminación.
- Files: `tests/test_flows.py:165, 179, 192`
- Risk: Tests flaky en CI si el DB no se limpia entre ejecuciones.
- Priority: Medium

**No hay tests del webhook handler de GHL (`/webhook/ghl`):**
- What's not tested: Toda la lógica de parseo de payload de GHL, normalización de teléfono, movimiento de oportunidades y envío de confirmaciones.
- Files: `agent/main.py:141-304`
- Risk: Regresiones en el flujo crítico de post-agendamiento sin detección automática.
- Priority: High

---

*Concerns audit: 2026-03-27*
