# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con cualquier proveedor (Whapi, Meta, Twilio) gracias a la capa de providers.
Soporta mensajes de texto, botones y listas interactivas.
"""

import os
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial
from agent.providers import obtener_proveedor
from agent.dedup import es_duplicado
from agent.utils import normalizar_telefono
from agent.ghl import (
    buscar_contacto_por_email,
    buscar_contacto_por_telefono,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
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
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            if msg.es_propio or (not msg.texto and not msg.imagen_url):
                continue

            # Deduplicar: ignorar reintentos del webhook con el mismo mensaje_id
            if es_duplicado(msg.mensaje_id):
                logger.debug(f"Mensaje duplicado ignorado: {msg.mensaje_id}")
                continue

            # Normalizar teléfono para operaciones de memoria (DB key canónica)
            # IMPORTANTE: msg.telefono original (con @s.whatsapp.net) se usa para enviar por Whapi
            telefono_normalizado = normalizar_telefono(msg.telefono)

            # Log con contexto de interacción
            if msg.imagen_url:
                logger.info(f"Imagen de {msg.telefono}: {msg.texto} (url: {msg.imagen_url[:80]})")
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
            if es_cliente_nuevo:
                contexto += "\n[CLIENTE NUEVO: es su primer mensaje. Presentate como Lucía, mencioná que sos asistente virtual de Bertero, y enviale la lista interactiva de opciones.]"
            else:
                contexto += "\n[CLIENTE RECURRENTE: ya ha conversado antes. REGLAS ESTRICTAS: 1) NUNCA presentarte como Lucía ni decir 'Soy Lucía' ni 'asistente virtual de Bertero' — el cliente ya te conoce. 2) Saludalo directamente y enviale la lista interactiva de opciones (paso 1 del flujo) para que elija qué necesita. 3) Si ya dijo qué busca en este mensaje, avanzá directo al siguiente paso del flujo sin re-presentarte.]"
            if msg.lista_id:
                contexto += f"\n[El cliente seleccionó de una lista interactiva. ID seleccionado: {msg.lista_id}]"
            elif msg.boton_id:
                contexto += f"\n[El cliente hizo clic en un botón. ID del botón: {msg.boton_id}]"
            contexto += f"\n{msg.texto}"
            respuesta = await generar_respuesta(contexto, historial, imagen_url=msg.imagen_url, imagen_mime=msg.imagen_mime)

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
        body = await request.json()
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

        # Link de Zoom/Meet — GHL lo genera al crear la cita
        # Buscar en todos los campos posibles donde GHL puede poner el link
        zoom_candidates = [
            body.get("address", ""),
            body.get("meetingUrl", ""),
            body.get("meeting_location", ""),
            calendar.get("meetingUrl", ""),
            calendar.get("address", ""),
            calendar.get("meeting_location", ""),
        ]
        # Si location es dict, buscar dentro; si es string, usarlo directo
        location = body.get("location", "")
        if isinstance(location, dict):
            zoom_candidates.append(location.get("meetingUrl", ""))
            zoom_candidates.append(location.get("address", ""))
        elif isinstance(location, str):
            zoom_candidates.append(location)

        # Encontrar el primer candidato que sea un link de videoconferencia
        zoom_link = ""
        for candidate in zoom_candidates:
            if candidate and any(domain in candidate.lower() for domain in ["zoom.us", "meet.google", "teams.microsoft"]):
                zoom_link = candidate
                break

        # Log completo del body para debug (ver qué campos manda GHL)
        logger.info(f"GHL webhook FULL BODY: {json.dumps(body, default=str)}")
        logger.info(f"GHL webhook — contact_id: {contact_id}, email: {email}, phone: {phone}, status: {appointment_status}, fecha_cita: {fecha_cita}, zoom_link: {zoom_link}")

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
                    if zoom_link:
                        mensaje += f"📹 *Link de la reunión:*\n{zoom_link}\n\n"
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
                        "zoom_link": zoom_link,
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
