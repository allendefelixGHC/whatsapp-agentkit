# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con cualquier proveedor (Whapi, Meta, Twilio) gracias a la capa de providers.
Soporta mensajes de texto, botones y listas interactivas.
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial
from agent.providers import obtener_proveedor
from agent.takeover import obtener_estado, procesar_comando_vendedor, check_and_apply_timeouts, timeout_loop
from agent.dedup import es_duplicado
from agent.utils import normalizar_telefono
from agent.auth import verificar_firma_ghl
from agent.limiter import verificar_rate_limit, RATE_LIMIT_MESSAGE
from agent.business_hours import esta_en_horario
from agent.tools import cargar_cache_desde_supabase
from agent.scraper import scrape_and_persist
from agent.ghl import (
    buscar_contacto_por_email,
    buscar_contacto_por_telefono,
    buscar_datos_contacto_por_telefono,
    buscar_oportunidad_por_contacto,
    mover_oportunidad,
    obtener_detalles_oportunidad,
)
import httpx as httpx_client

load_dotenv()

# Configuración de logging según entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
logger = logging.getLogger("agentkit")

# Proveedor de WhatsApp (se configura en .env con WHATSAPP_PROVIDER)
proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))

# Secreto de autenticación para el webhook de Whapi (TECH-04)
# Si está vacío, la autenticación Whapi está desactivada (modo degradado)
WHAPI_WEBHOOK_SECRET = os.getenv("WHAPI_WEBHOOK_SECRET", "")

# Modo estricto para webhooks GHL sin firma (TECH-05)
# false (default): permite webhooks sin X-GHL-Signature (ej: automatizaciones internas)
# true: rechaza todos los webhooks GHL que no tengan firma válida
GHL_WEBHOOK_AUTH_STRICT = os.getenv("GHL_WEBHOOK_AUTH_STRICT", "false").lower() == "true"

# Token de autenticación para endpoints de administración (/admin/*)
# Si está vacío, la autenticación está desactivada en endpoints admin (modo dev)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Telefono del vendedor normalizado para deteccion de comandos (HT-05)
# Si está vacío (VENDEDOR_WHATSAPP no configurado), el routing de comandos queda desactivado
_vendedor_raw = os.getenv("VENDEDOR_WHATSAPP", "")
VENDEDOR_PHONE_NORM = normalizar_telefono(_vendedor_raw) if _vendedor_raw else ""

# Deteccion de horario de atencion de Bertero (FU-03)
# Si false, el gate de horario se desactiva completamente (para testing fuera de horario)
BUSINESS_HOURS_ENABLED = os.getenv("BUSINESS_HOURS_ENABLED", "true").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos y carga el cache de propiedades al arrancar el servidor."""
    await inicializar_db()
    logger.info("Base de datos inicializada")
    # Cargar cache de propiedades desde Supabase (TECH-07)
    # Si SUPABASE_URL/KEY no están configurados, el servidor arranca igual (degradación graceful)
    try:
        await cargar_cache_desde_supabase()
        logger.info("Cache de propiedades cargado desde Supabase")
    except Exception as e:
        logger.warning(f"No se pudo cargar cache de propiedades desde Supabase: {e}")
        logger.warning("El bot funcionara sin cache de propiedades hasta el primer refresh")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    vendedor_wa = os.getenv("VENDEDOR_WHATSAPP", "")
    if not vendedor_wa:
        logger.warning("VENDEDOR_WHATSAPP no configurado — human takeover notifications disabled")
    # Human takeover timeout (HT-05): limpiar estados humano expirados al arrancar + loop horario
    # El check de startup atrapa estados stale de antes del restart (Pitfall 3)
    try:
        devueltas = await check_and_apply_timeouts(int(os.getenv("TAKEOVER_TIMEOUT_HOURS", "4")))
        if devueltas:
            logger.info(f"Startup: {len(devueltas)} conversaciones humano expiradas devueltas al bot")
    except Exception as e:
        logger.warning(f"Error checking takeover timeouts at startup: {e}")
    asyncio.create_task(timeout_loop())
    logger.info("Timeout loop de human takeover iniciado")
    yield


app = FastAPI(
    title="AgentKit — WhatsApp AI Agent",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway/monitoreo."""
    return {"status": "ok", "service": "agentkit"}


@app.post("/admin/refresh-properties")
async def admin_refresh_properties(request: Request):
    """Dispara scraping completo de Bertero + upsert a Supabase + recarga de cache.
    Llamado por n8n Schedule Trigger cada hora (plan 02-03)."""
    # Auth: requerir header X-Admin-Token si ADMIN_TOKEN está configurado
    if ADMIN_TOKEN:
        token = request.headers.get("X-Admin-Token", "")
        if token != ADMIN_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # 1. Scrapear Bertero + persistir en Supabase
        stats = await scrape_and_persist()

        # 2. Recargar cache en memoria desde Supabase
        await cargar_cache_desde_supabase()

        logger.info(f"Refresh de propiedades completado: {stats}")
        return {"status": "ok", "stats": stats}
    except Exception as e:
        logger.error(f"Error en refresh de propiedades: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/process-followups")
async def admin_process_followups(request: Request):
    """Procesa follow-ups pendientes cuyo scheduled_at ya paso.
    Llamado por n8n Schedule Trigger cada hora (plan 06-03)."""
    # Auth: requerir header X-Admin-Token si ADMIN_TOKEN esta configurado
    if ADMIN_TOKEN:
        token = request.headers.get("X-Admin-Token", "")
        if token != ADMIN_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        from agent.followup import procesar_followups_pendientes
        stats = await procesar_followups_pendientes()
        logger.info(f"Follow-ups procesados: {stats}")
        return {"status": "ok", "stats": stats}
    except Exception as e:
        logger.error(f"Error procesando follow-ups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificación GET del webhook (requerido por Meta Cloud API, no-op para otros)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


@app.post("/webhook")
async def webhook_handler(request: Request):
    """
    Recibe mensajes de WhatsApp via el proveedor configurado.
    Procesa el mensaje, genera respuesta con Claude y la envía de vuelta.
    Soporta respuestas de texto, botones y listas.
    """
    try:
        # Autenticación Whapi (TECH-04): verificar X-Whapi-Token si el secreto está configurado
        if WHAPI_WEBHOOK_SECRET:
            token = request.headers.get("X-Whapi-Token", "")
            if token != WHAPI_WEBHOOK_SECRET:
                logger.warning("Webhook Whapi rechazado — token inválido")
                raise HTTPException(status_code=401, detail="Unauthorized")

        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            if msg.es_propio or (not msg.texto and not msg.imagen_url and not msg.audio_url):
                continue

            # Deduplicar: ignorar reintentos del webhook con el mismo mensaje_id
            if es_duplicado(msg.mensaje_id):
                logger.debug(f"Mensaje duplicado ignorado: {msg.mensaje_id}")
                continue

            # Normalizar teléfono para operaciones de memoria (DB key canónica)
            # IMPORTANTE: msg.telefono original (con @s.whatsapp.net) se usa para enviar por Whapi
            telefono_normalizado = normalizar_telefono(msg.telefono)

            # Vendor command routing (HT-05): mensajes del vendedor son comandos, no mensajes de cliente
            # Va ANTES del rate limit — el vendedor no esta sujeto a rate limiting
            if VENDEDOR_PHONE_NORM and telefono_normalizado == VENDEDOR_PHONE_NORM:
                if msg.texto and msg.texto.strip().startswith("#"):
                    await procesar_comando_vendedor(msg.texto, msg.telefono, proveedor)
                # Tanto si es comando como si no, NUNCA procesar mensajes del vendedor como cliente
                # NUNCA guardar mensajes del vendedor en historial de conversaciones
                continue

            # Rate limiting (TECH-06): verificar límite de mensajes por teléfono por minuto
            # Usar teléfono normalizado como clave (conteo consistente sin importar el formato)
            # Usar msg.telefono original para enviar (Whapi necesita @s.whatsapp.net)
            if not verificar_rate_limit(telefono_normalizado):
                logger.warning(f"Rate limit excedido para {telefono_normalizado}")
                await proveedor.enviar_mensaje(msg.telefono, RATE_LIMIT_MESSAGE)
                continue  # No llamar a Claude API

            # Detectar si estamos fuera de horario (contexto para el prompt, NO bloqueo)
            fuera_de_horario = BUSINESS_HOURS_ENABLED and not esta_en_horario()

            # Human takeover gate (HT-04): si la conversacion esta en modo "humano",
            # el bot NO responde — silencio total, sin guardar en historial
            estado_conv = await obtener_estado(telefono_normalizado)
            if estado_conv == "humano":
                logger.info(f"Conversacion {telefono_normalizado} en modo HUMANO — bot en pausa")
                continue  # Saltar completamente — no llamar a Claude, no responder, no guardar

            # Log con contexto de interacción
            if msg.imagen_url:
                logger.info(f"Imagen de {msg.telefono}: {msg.texto} (url: {msg.imagen_url[:80]})")
            elif msg.audio_url:
                logger.info(f"Audio de {msg.telefono}: {msg.texto} (url: {msg.audio_url[:80]})")
            elif msg.boton_id:
                logger.info(f"Botón de {msg.telefono}: {msg.texto} (id: {msg.boton_id})")
            elif msg.lista_id:
                logger.info(f"Lista de {msg.telefono}: {msg.texto} (id: {msg.lista_id})")
            else:
                logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            # Enviar indicador de "escribiendo..." mientras se genera la respuesta
            await proveedor.enviar_indicador_tipeo(msg.telefono)

            # Obtener historial y generar respuesta
            # Pasamos el teléfono y contexto de interacción (botón/lista) para que Claude sepa qué pasó
            historial = await obtener_historial(telefono_normalizado)
            es_cliente_nuevo = len(historial) == 0
            contexto = f"[CONTEXTO INTERNO - NO MOSTRAR AL CLIENTE: teléfono del cliente es {msg.telefono}]"
            if fuera_de_horario:
                contexto += "\n[FUERA DE HORARIO: Estamos fuera del horario de atencion. No hay asesores disponibles para llamadas ni consultas en vivo. Seguir atendiendo al cliente con TODA la funcionalidad (propiedades, precios, visitas, calificacion). Si pide hablar con un humano o agendar llamada, NO hacer takeover — en su lugar registrar como lead y agendar callback para el proximo dia habil.]"
            # Buscar datos del cliente en GHL (CRM) para no volver a pedir nombre/email
            datos_crm = None
            try:
                datos_crm = await buscar_datos_contacto_por_telefono(telefono_normalizado)
            except Exception as e:
                logger.debug(f"Error buscando datos CRM para {telefono_normalizado}: {e}")
            if datos_crm and datos_crm.get("nombre"):
                contexto += f"\n[DATOS CRM: El cliente ya está registrado. Nombre: {datos_crm['nombre']}"
                if datos_crm.get("email"):
                    contexto += f", Email: {datos_crm['email']}"
                contexto += ". NO volver a pedir estos datos — usarlos directamente.]"

            # Detectar estado del flujo basado en el último mensaje del bot ANTES de decidir contexto cliente
            flujo_activo = None
            if historial:
                ultimo_bot = next((m for m in reversed(historial) if m["role"] == "assistant"), None)
                if ultimo_bot:
                    ultimo_texto = ultimo_bot["content"]
                    if "inmobiliariabertero.com.ar/p/" in ultimo_texto:
                        flujo_activo = "propiedades_mostradas"
                    elif "Agendar visita" in ultimo_texto or "btn_agendar" in ultimo_texto:
                        flujo_activo = "agendar_visita"
                    elif "¿qué tipo de propiedad" in ultimo_texto.lower() or "¿cuántos ambientes" in ultimo_texto.lower() or "¿en qué zona" in ultimo_texto.lower() or "presupuesto" in ultimo_texto.lower():
                        flujo_activo = "calificacion"
                    elif "nombre" in ultimo_texto.lower() and ("email" in ultimo_texto.lower() or "correo" in ultimo_texto.lower()):
                        flujo_activo = "registro_lead"
                    elif "detalle" in ultimo_texto.lower() or "fotos" in ultimo_texto.lower() or "características" in ultimo_texto.lower():
                        flujo_activo = "detalle_propiedad"

            if es_cliente_nuevo:
                contexto += "\n[CLIENTE NUEVO: es su primer mensaje. Presentate como Lucía, mencioná que sos asistente virtual de Bertero, y enviale la lista interactiva de opciones.]"
            elif flujo_activo:
                # Hay un flujo en curso — NO pedir menú principal
                contexto += "\n[CLIENTE RECURRENTE: ya ha conversado antes. NUNCA presentarte como Lucía ni re-presentarte. IMPORTANTE: Hay un flujo en curso — continuar donde quedó, NO enviar menú principal.]"
            else:
                contexto += "\n[CLIENTE RECURRENTE: ya ha conversado antes. REGLAS ESTRICTAS: 1) NUNCA presentarte como Lucía ni decir 'Soy Lucía' ni 'asistente virtual de Bertero' — el cliente ya te conoce. 2) Saludalo directamente y enviale la lista interactiva de opciones (paso 1 del flujo) para que elija qué necesita. 3) Si ya dijo qué busca en este mensaje, avanzá directo al siguiente paso del flujo sin re-presentarte.]"

            # Inyectar estado del flujo específico para guiar a Claude
            if flujo_activo == "propiedades_mostradas":
                contexto += "\n[ESTADO FLUJO: El bot ACABA de mostrar propiedades al cliente. Si el cliente responde con una afirmación (sí, dale, bueno, claro, ok) está diciendo que quiere ver detalles de alguna. Mostrar enviar_lista con las propiedades para que elija. NUNCA volver al menú principal.]"
            elif flujo_activo == "agendar_visita":
                contexto += "\n[ESTADO FLUJO: El bot ofreció agendar visita o hablar con asesor. Continuar ese flujo.]"
            elif flujo_activo == "calificacion":
                contexto += "\n[ESTADO FLUJO: El bot está en medio del flujo de calificación (tipo/zona/ambientes/precio). Continuar con la siguiente pregunta del flujo. NUNCA volver al menú principal.]"
            elif flujo_activo == "registro_lead":
                contexto += "\n[ESTADO FLUJO: El bot está pidiendo datos de contacto al cliente. Continuar ese flujo.]"
            elif flujo_activo == "detalle_propiedad":
                contexto += "\n[ESTADO FLUJO: El bot acaba de mostrar detalle de una propiedad. Ofrecer las opciones post-detalle (agendar visita, ver otra, hablar con asesor). NUNCA volver al menú principal.]"

            if msg.lista_id:
                contexto += f"\n[El cliente seleccionó de una lista interactiva. ID seleccionado: {msg.lista_id}]"
            elif msg.boton_id:
                contexto += f"\n[El cliente hizo clic en un botón. ID del botón: {msg.boton_id}]"
            contexto += f"\n{msg.texto}"
            respuesta = await generar_respuesta(
                contexto,
                historial,
                imagen_url=msg.imagen_url,
                imagen_mime=msg.imagen_mime,
                audio_url=msg.audio_url,
                audio_mime=msg.audio_mime,
            )

            # Guardar en memoria — incluir contexto de botón/lista para no perder info
            # Usar telefono_normalizado como clave canónica en DB
            texto_guardar = msg.texto
            if msg.lista_id:
                texto_guardar = f"[Seleccionó de lista: {msg.lista_id}] {msg.texto}"
            elif msg.boton_id:
                texto_guardar = f"[Botón: {msg.boton_id}] {msg.texto}"
            await guardar_mensaje(telefono_normalizado, "user", texto_guardar)
            await guardar_mensaje(telefono_normalizado, "assistant", respuesta.texto)

            # Enviar respuesta según tipo (texto, botones o lista)
            await proveedor.enviar_respuesta(msg.telefono, respuesta)

            logger.info(f"Respuesta [{respuesta.tipo}] a {msg.telefono}: {respuesta.texto[:100]}...")

        return {"status": "ok"}

    except Exception as e:
        import traceback
        logger.error(f"Error en webhook: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/ghl")
async def ghl_webhook_handler(request: Request):
    """
    Recibe webhooks de GHL (cita agendada/confirmada).
    Busca la oportunidad del contacto y la mueve a 'Visita agendada'.
    Opcionalmente envía confirmación por WhatsApp.
    """
    try:
        # CRÍTICO: leer raw_body PRIMERO para poder verificar firma Ed25519 (TECH-05)
        # Después de request.body(), NO llamar request.json() — usar json.loads(raw_body)
        raw_body = await request.body()

        # Autenticación GHL (TECH-05): verificar X-GHL-Signature (Ed25519)
        sig = request.headers.get("X-GHL-Signature", "")
        if sig:
            # Header presente: verificar firma — rechazar si es inválida
            if not verificar_firma_ghl(raw_body, sig):
                logger.warning("Webhook GHL rechazado — firma Ed25519 inválida")
                raise HTTPException(status_code=401, detail="Unauthorized")
        elif GHL_WEBHOOK_AUTH_STRICT:
            # Header ausente y modo estricto activado: rechazar
            logger.warning("Webhook GHL rechazado — sin X-GHL-Signature en modo estricto")
            raise HTTPException(status_code=401, detail="Unauthorized")
        else:
            # Header ausente, modo permisivo (default): dejar pasar con advertencia
            logger.debug("Webhook GHL sin X-GHL-Signature — modo permisivo, procesando igual")

        body = json.loads(raw_body)
        logger.info(f"Webhook GHL recibido: {json.dumps(body, default=str)[:2000]}")

        # GHL envía datos del contacto y la cita
        # Extraer datos del contacto — puede venir en distintos formatos
        contact_id = body.get("contact_id") or body.get("contactId") or ""
        email = body.get("email") or body.get("contact", {}).get("email") or ""
        phone = body.get("phone") or body.get("contact", {}).get("phone") or ""
        first_name = body.get("first_name") or body.get("contact", {}).get("firstName") or ""
        appointment_status = body.get("appointment_status") or body.get("status") or body.get("calendar", {}).get("appoinmentStatus", "") or ""
        # Fecha/hora de la cita — GHL la pone en calendar.startTime
        calendar = body.get("calendar", {})
        fecha_cita = (
            body.get("date_time")
            or body.get("start_time")
            or calendar.get("startTime", "")
            or body.get("selectedTimezone", {}).get("startTime", "")
            or ""
        )

        # Log completo del body para debug (ver qué campos manda GHL)
        logger.info(f"GHL webhook FULL BODY: {json.dumps(body, default=str)}")
        logger.info(f"GHL webhook — contact_id: {contact_id}, email: {email}, phone: {phone}, status: {appointment_status}, fecha_cita: {fecha_cita}")

        # Buscar contacto si no tenemos el ID directo
        if not contact_id:
            if email:
                contact_id = await buscar_contacto_por_email(email)
            if not contact_id and phone:
                contact_id = await buscar_contacto_por_telefono(phone)

        if not contact_id:
            logger.warning("GHL webhook: no se pudo identificar el contacto")
            return {"status": "ok", "action": "contact_not_found"}

        # Buscar oportunidad del contacto
        opp_id = await buscar_oportunidad_por_contacto(contact_id)
        if not opp_id:
            logger.warning(f"GHL webhook: no hay oportunidad para contacto {contact_id}")
            return {"status": "ok", "action": "opportunity_not_found"}

        # Obtener detalles de la propiedad antes de mover
        detalles = await obtener_detalles_oportunidad(opp_id)
        propiedad_dir = detalles.get("propiedad_direccion", "")
        propiedad_link = detalles.get("propiedad_link", "")
        propiedad_resumen = detalles.get("propiedad_resumen", "")
        logger.info(f"GHL webhook — propiedad: dir={propiedad_dir}, link={propiedad_link[:50] if propiedad_link else 'N/A'}")

        # Mover oportunidad a "Visita agendada"
        movida = await mover_oportunidad(opp_id, "visita_agendada")
        logger.info(f"GHL webhook — oportunidad {opp_id} movida a visita_agendada: {movida}")

        # Formatear fecha/hora de la cita para las notificaciones
        fecha_formateada = ""
        if fecha_cita:
            try:
                # GHL manda ISO 8601: "2026-03-26T14:30:00+00:00" o "2026-03-26T14:30:00"
                dt = datetime.fromisoformat(fecha_cita.replace("Z", "+00:00"))
                dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
                fecha_formateada = f"{dias[dt.weekday()]} {dt.day} de {meses[dt.month - 1]} a las {dt.strftime('%H:%M')} hs"
            except (ValueError, IndexError) as e:
                logger.warning(f"No se pudo parsear fecha_cita '{fecha_cita}': {e}")
                fecha_formateada = fecha_cita  # Usar el valor raw como fallback

        # Enviar notificaciones si la oportunidad se movió
        nombre = first_name or "cliente"
        if movida:
            # 1. WhatsApp de confirmación al cliente
            if phone:
                try:
                    # normalizar_telefono() convierte cualquier formato al canónico (ej: 5493517575244)
                    # Luego agregar @s.whatsapp.net para envío por Whapi
                    tel_whapi = normalizar_telefono(phone) + "@s.whatsapp.net"
                    # Personalizar mensaje según si hay propiedad o es consulta general
                    if propiedad_dir:
                        mensaje = f"✅ *¡Tu visita fue confirmada, {nombre}!*\n\n"
                    else:
                        mensaje = f"✅ *¡Tu llamada fue confirmada, {nombre}!*\n\n"
                    if fecha_formateada:
                        mensaje += f"📅 *{fecha_formateada}*\n\n"
                    if propiedad_dir:
                        mensaje += (
                            f"Un asesor de Bertero va a estar esperándote. "
                            f"Si necesitás reprogramar o tenés alguna consulta, escribinos por acá. 😊"
                        )
                    else:
                        mensaje += (
                            f"Un asesor de Bertero va a conversar con vos sobre tu búsqueda. "
                            f"Si necesitás reprogramar o tenés alguna consulta, escribinos por acá. 😊"
                        )
                    await proveedor.enviar_mensaje(tel_whapi, mensaje)
                    logger.info(f"WhatsApp de confirmación enviado a {phone}")
                except Exception as e:
                    import traceback
                    logger.error(f"Error enviando WhatsApp de confirmación a {phone}: {e}\n{traceback.format_exc()}")

            # 2 y 3. Emails via n8n (cliente + vendedor)
            try:
                n8n_url = os.getenv("N8N_EMAIL_WEBHOOK", "https://n8n-n8n.bacu5y.easypanel.host/webhook/agentkit-send-emails")
                async with httpx_client.AsyncClient(timeout=15.0) as client:
                    r = await client.post(n8n_url, json={
                        "nombre": nombre,
                        "email_cliente": email or "",
                        "email_vendedor": os.getenv("VENDEDOR_EMAIL", "hola@propulsar.ai"),
                        "telefono": phone or "",
                        "propiedad_direccion": propiedad_dir,
                        "propiedad_link": propiedad_link,
                        "propiedad_resumen": propiedad_resumen,
                        "fecha_cita": fecha_cita,
                        "fecha_formateada": fecha_formateada,
                        "zoom_link": "",
                        "tipo_cita": "visita" if propiedad_dir else "consulta",
                    })
                    logger.info(f"n8n emails enviados: {r.status_code}")
            except Exception as e:
                import traceback
                logger.error(f"Error enviando emails via n8n: {e}\n{traceback.format_exc()}")

        return {"status": "ok", "action": "opportunity_moved", "opportunity_id": opp_id}

    except Exception as e:
        import traceback
        logger.error(f"Error en webhook GHL: {e}\n{traceback.format_exc()}")
        return {"status": "error", "detail": str(e)}
