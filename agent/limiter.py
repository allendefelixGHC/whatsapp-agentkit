# agent/limiter.py — Rate limiting por teléfono con TTLCache
# Generado por AgentKit — Plan 01-02

"""
Módulo de rate limiting para mensajes de WhatsApp.

Usa TTLCache (misma librería que dedup.py) para mantener un contador de mensajes
por número de teléfono en una ventana deslizante de 60 segundos.

Si un teléfono supera el límite, el bot NO llama a Claude API y responde
con un mensaje amigable indicando que espere.

Diseño intencional:
- En memoria (no DB) — aceptable para Phase 1 / instancia única
- Resetea al reiniciar — documentado como trade-off conocido
- Configurable via RATE_LIMIT_PER_MINUTE en .env
"""

import os
import logging
from cachetools import TTLCache

logger = logging.getLogger("agentkit")

# Límite de mensajes por teléfono por minuto — configurable via .env
# Default: 15/min (2-5x el uso normal de WhatsApp en una conversación activa)
_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "15"))

# Contador por teléfono: TTL de 60 segundos, máximo 10.000 números simultáneos
# El TTL crea una ventana deslizante de 60s (el contador expira y se reinicia)
_counters: TTLCache = TTLCache(maxsize=10_000, ttl=60)

# Mensaje de rate limit que se envía al usuario por WhatsApp
RATE_LIMIT_MESSAGE = (
    "Estás enviando muchos mensajes seguidos. "
    "Por favor espera un momento antes de continuar."
)


def verificar_rate_limit(telefono: str) -> bool:
    """
    Verifica si el teléfono está dentro del límite de mensajes por minuto.

    Args:
        telefono: Número de teléfono normalizado (clave canónica, sin @s.whatsapp.net)

    Returns:
        True si está dentro del límite (puede procesar el mensaje).
        False si excedió el límite (NO llamar a Claude API — enviar RATE_LIMIT_MESSAGE).
    """
    count = _counters.get(telefono, 0)
    if count >= _RATE_LIMIT:
        return False
    _counters[telefono] = count + 1
    return True
