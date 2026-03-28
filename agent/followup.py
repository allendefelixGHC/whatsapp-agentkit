# agent/followup.py — Seguimiento automatico post-consulta (FU-01)
# Programar, cancelar y procesar follow-ups de clientes que vieron propiedades

"""
Follow-up automatico: clientes que vieron propiedades pero no agendaron reciben
un mensaje de seguimiento 24 horas despues (configurable via FOLLOWUP_DELAY_HOURS).

Ciclo de vida:
    buscar_propiedades() -> programar_followup() -> status=pending
    registrar_lead_ghl() -> cancelar_followup()  -> status=cancelled
    solicitar_humano()   -> cancelar_followup()  -> status=cancelled
    /admin/process-followups -> procesar_followups_pendientes() -> status=sent
"""

import os
import json
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from agent.memory import async_session, FollowUpSchedule

logger = logging.getLogger("agentkit")

FOLLOWUP_DELAY_HOURS = int(os.getenv("FOLLOWUP_DELAY_HOURS", "24"))

FOLLOWUP_MESSAGE = (
    "Hola! Soy Lucia de Bertero Inmobiliaria.\n\n"
    "Hace un tiempo te mostramos algunas propiedades. Pudiste verlas? Te intereso alguna?\n\n"
    "Si queres agendar una visita o tenes alguna consulta, estamos disponibles."
)


async def programar_followup(telefono: str, propiedades: list[dict]) -> None:
    """
    Programa (o reprograma) un follow-up para el telefono dado.

    Patron upsert: si ya existe un follow-up pending para este telefono,
    actualiza la fecha y las propiedades. Si no existe, crea uno nuevo.
    Esto garantiza que multiples busquedas del mismo cliente = un solo follow-up.

    Args:
        telefono: Numero de telefono normalizado (clave canonica DB).
        propiedades: Lista de dicts con las propiedades mostradas al cliente.
                     Se guardan hasta 5 (direccion + link) para contexto.
    """
    ahora = datetime.utcnow()
    nueva_fecha = ahora + timedelta(hours=FOLLOWUP_DELAY_HOURS)
    props_json = json.dumps(
        [{"direccion": p.get("direccion", ""), "link": p.get("link", "")} for p in propiedades[:5]],
        ensure_ascii=False,
    )

    async with async_session() as session:
        # Buscar follow-up pending existente para este telefono
        query = (
            select(FollowUpSchedule)
            .where(FollowUpSchedule.telefono == telefono)
            .where(FollowUpSchedule.status == "pending")
        )
        result = await session.execute(query)
        existente = result.scalar_one_or_none()

        if existente:
            # Upsert: actualizar fecha y propiedades (reiniciar el contador)
            existente.scheduled_at = nueva_fecha
            existente.propiedades_json = props_json
            existente.updated_at = ahora
            logger.info(f"Follow-up reprogramado para {telefono}: {nueva_fecha.isoformat()}")
        else:
            # Insertar nuevo registro pending
            nuevo = FollowUpSchedule(
                telefono=telefono,
                status="pending",
                propiedades_json=props_json,
                scheduled_at=nueva_fecha,
                created_at=ahora,
                updated_at=ahora,
            )
            session.add(nuevo)
            logger.info(f"Follow-up programado para {telefono}: {nueva_fecha.isoformat()}")

        await session.commit()


async def cancelar_followup(telefono: str) -> None:
    """
    Cancela todos los follow-ups pending para el telefono dado.

    Llamar cuando el cliente agenda (registrar_lead_ghl) o solicita humano
    (solicitar_humano) — no hay razon para hacer seguimiento automatico.

    Operacion idempotente: si no hay pending, es no-op.

    Args:
        telefono: Numero de telefono normalizado (clave canonica DB).
    """
    ahora = datetime.utcnow()

    async with async_session() as session:
        query = (
            select(FollowUpSchedule)
            .where(FollowUpSchedule.telefono == telefono)
            .where(FollowUpSchedule.status == "pending")
        )
        result = await session.execute(query)
        pendientes = result.scalars().all()

        if not pendientes:
            logger.debug(f"cancelar_followup: no hay pending para {telefono} — no-op")
            return

        for fup in pendientes:
            fup.status = "cancelled"
            fup.updated_at = ahora

        await session.commit()
        logger.info(f"Follow-up(s) cancelados para {telefono}: {len(pendientes)} registro(s)")


async def procesar_followups_pendientes() -> dict:
    """
    Procesa todos los follow-ups pendientes cuyo scheduled_at ya paso.

    Para cada follow-up due:
    1. Verifica que el cliente NO este en estado 'humano' (vendedor atendiendolo).
       Si esta en humano, SKIP — no enviar, no cancelar.
    2. Envia FOLLOWUP_MESSAGE por WhatsApp.
    3. Marca el follow-up como 'sent'.

    Returns:
        dict con estadisticas: {"processed": N, "sent": M, "skipped_humano": K}
    """
    # Lazy imports para evitar importaciones circulares
    from agent.takeover import obtener_estado
    from agent.providers import obtener_proveedor

    ahora = datetime.utcnow()
    stats = {"processed": 0, "sent": 0, "skipped_humano": 0}

    async with async_session() as session:
        query = (
            select(FollowUpSchedule)
            .where(FollowUpSchedule.status == "pending")
            .where(FollowUpSchedule.scheduled_at <= ahora)
        )
        result = await session.execute(query)
        pendientes = result.scalars().all()

    if not pendientes:
        logger.info("procesar_followups_pendientes: no hay follow-ups due")
        return stats

    proveedor = obtener_proveedor()

    for fup in pendientes:
        stats["processed"] += 1
        try:
            # Verificar estado de la conversacion
            estado = await obtener_estado(fup.telefono)
            if estado == "humano":
                # Vendedor esta atendiendo — no interrumpir con follow-up automatico
                logger.info(f"Follow-up skipped (humano) para {fup.telefono}")
                stats["skipped_humano"] += 1
                continue

            # Enviar mensaje de seguimiento
            # Whapi requiere @s.whatsapp.net — el telefono en DB es digits-only (canonical)
            telefono_whapi = fup.telefono + "@s.whatsapp.net"
            enviado = await proveedor.enviar_mensaje(telefono_whapi, FOLLOWUP_MESSAGE)

            if enviado:
                # Marcar como enviado (nueva session para cada commit individual)
                async with async_session() as session2:
                    result2 = await session2.execute(
                        select(FollowUpSchedule).where(FollowUpSchedule.id == fup.id)
                    )
                    fup_db = result2.scalar_one_or_none()
                    if fup_db:
                        fup_db.status = "sent"
                        fup_db.updated_at = datetime.utcnow()
                        await session2.commit()
                stats["sent"] += 1
                logger.info(f"Follow-up enviado a {fup.telefono} (id={fup.id})")
            else:
                logger.warning(f"Follow-up no enviado a {fup.telefono} — proveedor retorno False")

        except Exception as e:
            logger.error(f"Error procesando follow-up id={fup.id} para {fup.telefono}: {e}")
            # Continuar con los demas — un error no bloquea el batch

    logger.info(f"procesar_followups_pendientes stats: {stats}")
    return stats
