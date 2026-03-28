# agent/dedup.py — Deduplicación de mensajes por ID con caché TTL
# Generado por AgentKit

"""
Previene que el bot procese el mismo mensaje dos veces cuando Whapi reintenta
la entrega del webhook (lo cual ocurre cuando el servidor no responde a tiempo).

Implementación: caché en memoria con TTL de 5 minutos.
Un mensaje_id visto dentro de esa ventana de tiempo se considera duplicado.
"""

import logging
from cachetools import TTLCache

logger = logging.getLogger("agentkit")

# Caché de message IDs vistos recientemente
# maxsize=10_000: soporta hasta 10.000 mensajes únicos en memoria (bajo consumo)
# ttl=300: cada ID expira a los 5 minutos (los reintentos de Whapi ocurren en segundos)
_seen: TTLCache = TTLCache(maxsize=10_000, ttl=300)


def es_duplicado(mensaje_id: str) -> bool:
    """
    Verifica si ya procesamos este mensaje_id en los últimos 5 minutos.

    Si el mensaje_id es vacío o nulo, siempre retorna False (no deduplicar).
    Si es el primer avistamiento, lo registra y retorna False.
    Si ya fue visto, retorna True (debe ignorarse).

    Args:
        mensaje_id: ID único del mensaje de WhatsApp

    Returns:
        True si es duplicado (ya procesado recientemente), False si es nuevo.
    """
    if not mensaje_id:
        logger.warning("es_duplicado: recibió mensaje_id vacío — no se puede deduplicar")
        return False

    if mensaje_id in _seen:
        return True

    # Primer avistamiento: registrar y permitir procesamiento
    _seen[mensaje_id] = True
    return False
