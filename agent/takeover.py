# agent/takeover.py — Logica de human takeover: CRUD de estado + comandos del vendedor + timeout
# Generado por AgentKit (Phase 05-01)

"""
Gestiona el ciclo de vida del human takeover:
- CRUD de ConversationState en DB (obtener_estado, set_estado)
- Construccion del mensaje de notificacion al vendedor
- Procesamiento de comandos del vendedor (#bot, #bot-all, #estado)
- Loop de timeout que devuelve conversaciones inactivas al bot
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, update

from agent.memory import async_session, ConversationState
from agent.utils import normalizar_telefono

logger = logging.getLogger("agentkit")


# ── CRUD de estado ─────────────────────────────────────────────────────────────

async def obtener_estado(telefono: str) -> str:
    """
    Retorna el estado de la conversacion: 'bot', 'humano', o 'cerrado'.
    Si no existe fila para ese telefono, retorna 'bot' (estado default).
    """
    async with async_session() as session:
        query = select(ConversationState).where(ConversationState.telefono == telefono)
        result = await session.execute(query)
        row = result.scalar_one_or_none()
        return row.estado if row else "bot"


async def set_estado(telefono: str, estado: str, vendedor: str = "") -> None:
    """
    Upsert del estado de la conversacion.
    Si existe fila para el telefono, actualiza estado + vendedor + updated_at.
    Si no existe, inserta nueva fila.

    Args:
        telefono: Numero de telefono normalizado (clave canonica digits-only)
        estado: Nuevo estado — "bot", "humano", o "cerrado"
        vendedor: Nombre del vendedor asignado (opcional)
    """
    async with async_session() as session:
        query = select(ConversationState).where(ConversationState.telefono == telefono)
        result = await session.execute(query)
        row = result.scalar_one_or_none()

        if row:
            row.estado = estado
            row.vendedor = vendedor
            row.updated_at = datetime.utcnow()
        else:
            session.add(ConversationState(
                telefono=telefono,
                estado=estado,
                vendedor=vendedor,
                updated_at=datetime.utcnow(),
            ))

        await session.commit()
    logger.info(f"Estado conversacion {telefono} -> {estado} (vendedor: {vendedor or 'N/A'})")


# ── Construccion del mensaje de notificacion al vendedor ───────────────────────

def construir_mensaje_vendedor(cliente_telefono: str, resumen: str) -> str:
    """
    Construye el texto WhatsApp para notificar al vendedor cuando un cliente pide takeover.
    Formato con bold de WhatsApp (*texto*).

    Args:
        cliente_telefono: Telefono del cliente (formato Whapi con @s.whatsapp.net, o normalizado)
        resumen: Resumen de la conversacion generado por Claude
    """
    # Extraer solo el numero (sin @s.whatsapp.net si viene con ese sufijo)
    numero_limpio = cliente_telefono.split("@")[0]

    return (
        f"*TAKEOVER \u2014 Cliente solicita asesor*\n\n"
        f"*Cliente:* {numero_limpio}\n\n"
        f"*Resumen:*\n{resumen}\n\n"
        f"---\n"
        f"Para devolver al bot:\n"
        f"#bot {numero_limpio}\n\n"
        f"Para ver estado:\n"
        f"#estado {numero_limpio}"
    )


# ── Procesamiento de comandos del vendedor ────────────────────────────────────

async def procesar_comando_vendedor(texto: str, vendedor_telefono: str, proveedor) -> None:
    """
    Procesa un comando WhatsApp enviado por el vendedor y envía confirmación.

    Comandos soportados:
    - #bot <phone>  : Devuelve la conversacion del cliente al bot
    - #bot-all      : Devuelve TODAS las conversaciones humano al bot
    - #estado <phone>: Reporta el estado actual de una conversacion
    - Cualquier otro mensaje que empiece con #: ignorado silenciosamente

    IMPORTANTE: Solo se llama cuando el mensaje EMPIEZA con "#".
    Mensajes sin "#" del vendedor se ignoran en main.py antes de llegar aquí.

    Args:
        texto: Texto del mensaje del vendedor (ya empieza con "#")
        vendedor_telefono: Telefono del vendedor (formato Whapi, para enviarle la confirmacion)
        proveedor: Instancia del proveedor de WhatsApp (para enviar confirmacion al vendedor)
    """
    texto = texto.strip()

    if texto.lower().startswith("#bot-all"):
        # Devolver TODAS las conversaciones al bot
        devueltas = await devolver_todas_al_bot()
        if devueltas:
            msg = f"✅ *{len(devueltas)} conversacion(es) devuelta(s) al bot:*\n" + "\n".join(f"• {t}" for t in devueltas)
        else:
            msg = "ℹ️ No hay conversaciones en modo humano actualmente."
        await proveedor.enviar_mensaje(vendedor_telefono, msg)
        logger.info(f"Comando #bot-all: {len(devueltas)} conversaciones devueltas al bot")

    elif texto.lower().startswith("#bot "):
        # Devolver una conversacion especifica al bot
        # Formato: #bot <phone> — tolerante a +, @s.whatsapp.net, espacios extra
        partes = texto.split(" ", 1)
        if len(partes) < 2 or not partes[1].strip():
            await proveedor.enviar_mensaje(vendedor_telefono, "❌ Uso: #bot <numero> (ej: #bot 5493517575244)")
            return
        raw_phone = partes[1].strip()
        # Normalizar: quitar +, @s.whatsapp.net, luego normalizar_telefono()
        raw_phone = raw_phone.replace("+", "").split("@")[0]
        telefono_norm = normalizar_telefono(raw_phone)
        if not telefono_norm:
            await proveedor.enviar_mensaje(vendedor_telefono, f"❌ No se pudo parsear el numero: {raw_phone}")
            return
        await set_estado(telefono_norm, "bot")
        await proveedor.enviar_mensaje(
            vendedor_telefono,
            f"✅ Conversacion *{telefono_norm}* devuelta al bot."
        )
        logger.info(f"Comando #bot: conversacion {telefono_norm} devuelta al bot por vendedor")

    elif texto.lower().startswith("#estado "):
        # Reportar estado de una conversacion
        partes = texto.split(" ", 1)
        if len(partes) < 2 or not partes[1].strip():
            await proveedor.enviar_mensaje(vendedor_telefono, "❌ Uso: #estado <numero> (ej: #estado 5493517575244)")
            return
        raw_phone = partes[1].strip()
        raw_phone = raw_phone.replace("+", "").split("@")[0]
        telefono_norm = normalizar_telefono(raw_phone)
        if not telefono_norm:
            await proveedor.enviar_mensaje(vendedor_telefono, f"❌ No se pudo parsear el numero: {raw_phone}")
            return
        estado = await obtener_estado(telefono_norm)
        await proveedor.enviar_mensaje(
            vendedor_telefono,
            f"📊 Conversacion *{telefono_norm}*: estado actual = *{estado}*"
        )
        logger.info(f"Comando #estado: {telefono_norm} = {estado}")

    else:
        # Comando desconocido que empieza con "#" — ignorar silenciosamente
        logger.debug(f"Comando de vendedor no reconocido (ignorado): {texto[:50]}")


# ── Timeout: devolver conversaciones inactivas al bot ─────────────────────────

async def check_and_apply_timeouts(timeout_hours: int = 4) -> list[str]:
    """
    Busca conversaciones en estado 'humano' con updated_at mas viejo que timeout_hours.
    Las devuelve al estado 'bot' y retorna la lista de telefonos afectados.

    Args:
        timeout_hours: Horas de inactividad antes de devolver al bot (default 4)

    Returns:
        Lista de telefonos devueltos al bot
    """
    cutoff = datetime.utcnow() - timedelta(hours=timeout_hours)
    async with async_session() as session:
        query = (
            select(ConversationState)
            .where(ConversationState.estado == "humano")
            .where(ConversationState.updated_at < cutoff)
        )
        result = await session.execute(query)
        stale = result.scalars().all()

        telefonos = []
        for conv in stale:
            conv.estado = "bot"
            conv.updated_at = datetime.utcnow()
            telefonos.append(conv.telefono)
            logger.info(f"Timeout: conversacion {conv.telefono} devuelta al bot (inactividad > {timeout_hours}h)")

        await session.commit()
    return telefonos


async def devolver_todas_al_bot() -> list[str]:
    """
    Devuelve TODAS las conversaciones en estado 'humano' al bot.
    Usado por el comando #bot-all del vendedor.

    Returns:
        Lista de telefonos devueltos al bot
    """
    async with async_session() as session:
        query = select(ConversationState).where(ConversationState.estado == "humano")
        result = await session.execute(query)
        activas = result.scalars().all()

        telefonos = []
        for conv in activas:
            conv.estado = "bot"
            conv.updated_at = datetime.utcnow()
            telefonos.append(conv.telefono)
            logger.info(f"bot-all: conversacion {conv.telefono} devuelta al bot")

        await session.commit()
    return telefonos


async def timeout_loop() -> None:
    """
    Loop infinito que corre cada hora y devuelve al bot las conversaciones
    cuyo tiempo en modo 'humano' supero TAKEOVER_TIMEOUT_HOURS.
    Se inicia como asyncio.create_task() en main.py lifespan().
    """
    timeout_hours = int(os.getenv("TAKEOVER_TIMEOUT_HOURS", "4"))
    while True:
        await asyncio.sleep(3600)  # Verificar cada hora
        try:
            devueltas = await check_and_apply_timeouts(timeout_hours)
            if devueltas:
                logger.info(f"Timeout loop: {len(devueltas)} conversaciones devueltas al bot: {devueltas}")
        except Exception as e:
            logger.error(f"Error en timeout loop: {e}")
