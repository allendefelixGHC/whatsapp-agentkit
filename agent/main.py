# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con cualquier proveedor (Whapi, Meta, Twilio) gracias a la capa de providers.
Soporta mensajes de texto, botones y listas interactivas.
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial
from agent.providers import obtener_proveedor
from agent.ghl import (
    buscar_contacto_por_email,
    buscar_contacto_por_telefono,
    buscar_oportunidad_por_contacto,
    mover_oportunidad,
)
from agent.email_service import enviar_confirmacion_cliente, enviar_notificacion_vendedor

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
            if msg.es_propio or not msg.texto:
                continue

            # Log con contexto de interacción
            if msg.boton_id:
                logger.info(f"Botón de {msg.telefono}: {msg.texto} (id: {msg.boton_id})")
            elif msg.lista_id:
                logger.info(f"Lista de {msg.telefono}: {msg.texto} (id: {msg.lista_id})")
            else:
                logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            # Enviar indicador de "escribiendo..." mientras se genera la respuesta
            await proveedor.enviar_indicador_tipeo(msg.telefono)

            # Obtener historial y generar respuesta
            # Pasamos el teléfono y contexto de interacción (botón/lista) para que Claude sepa qué pasó
            historial = await obtener_historial(msg.telefono)
            es_cliente_nuevo = len(historial) == 0
            contexto = f"[CONTEXTO INTERNO - NO MOSTRAR AL CLIENTE: teléfono del cliente es {msg.telefono}]"
            if es_cliente_nuevo:
                contexto += "\n[CLIENTE NUEVO: es su primer mensaje. Presentate como Lucía y dale una bienvenida cálida.]"
            else:
                contexto += "\n[CLIENTE RECURRENTE: ya ha conversado antes. Saludalo por su nombre si lo conocés del historial, sin repetir la presentación completa.]"
            if msg.lista_id:
                contexto += f"\n[El cliente seleccionó de una lista interactiva. ID seleccionado: {msg.lista_id}]"
            elif msg.boton_id:
                contexto += f"\n[El cliente hizo clic en un botón. ID del botón: {msg.boton_id}]"
            contexto += f"\n{msg.texto}"
            respuesta = await generar_respuesta(contexto, historial)

            # Guardar en memoria (siempre como texto para el historial)
            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta.texto)

            # Enviar respuesta según tipo (texto, botones o lista)
            await proveedor.enviar_respuesta(msg.telefono, respuesta)

            logger.info(f"Respuesta [{respuesta.tipo}] a {msg.telefono}: {respuesta.texto[:100]}...")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
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
        logger.info(f"Webhook GHL recibido: {body.get('type', 'unknown')}")

        # GHL envía datos del contacto y la cita
        # Extraer datos del contacto — puede venir en distintos formatos
        contact_id = body.get("contact_id") or body.get("contactId") or ""
        email = body.get("email") or body.get("contact", {}).get("email") or ""
        phone = body.get("phone") or body.get("contact", {}).get("phone") or ""
        first_name = body.get("first_name") or body.get("contact", {}).get("firstName") or ""
        appointment_status = body.get("appointment_status") or body.get("status") or ""

        logger.info(f"GHL webhook — contact_id: {contact_id}, email: {email}, phone: {phone}, status: {appointment_status}")

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

        # Mover oportunidad a "Visita agendada"
        movida = await mover_oportunidad(opp_id, "visita_agendada")
        logger.info(f"GHL webhook — oportunidad {opp_id} movida a visita_agendada: {movida}")

        # Enviar notificaciones si la oportunidad se movió
        nombre = first_name or "cliente"
        if movida:
            # 1. WhatsApp de confirmación al cliente
            if phone:
                tel_whapi = phone.replace("+", "") + "@s.whatsapp.net"
                mensaje = (
                    f"✅ *¡Tu visita fue confirmada, {nombre}!*\n\n"
                    f"Un asesor de Bertero va a estar esperándote. "
                    f"Si necesitás reprogramar o tenés alguna consulta, escribinos por acá. 😊"
                )
                await proveedor.enviar_mensaje(tel_whapi, mensaje)
                logger.info(f"WhatsApp de confirmación enviado a {phone}")

            # 2. Email de confirmación al cliente
            if email:
                enviar_confirmacion_cliente(email, nombre)

            # 3. Email de notificación al vendedor
            enviar_notificacion_vendedor(nombre, email or "N/A", phone or "N/A")

        return {"status": "ok", "action": "opportunity_moved", "opportunity_id": opp_id}

    except Exception as e:
        logger.error(f"Error en webhook GHL: {e}")
        return {"status": "error", "detail": str(e)}
