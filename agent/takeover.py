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
        devueltas = await check_and_apply_timeouts(timeout_hours)
        if devueltas:
            logger.info(f"Timeout loop: {len(devueltas)} conversaciones devueltas al bot: {devueltas}")
