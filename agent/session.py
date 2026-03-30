# agent/session.py — Cache de sesión por conversación
# Generado por AgentKit

"""
Almacena estado efímero por conversación (teléfono).
Usa un dict en memoria — se pierde al reiniciar el servidor,
lo cual está bien porque son datos de sesión temporales.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger("agentkit")

# Cache: {telefono: {"propiedades": [...], "timestamp": datetime}}
_cache: dict[str, dict] = {}

# Tiempo de expiración del cache (2 horas)
_TTL = timedelta(hours=2)


def guardar_propiedades(telefono: str, propiedades: list[dict], filtros: dict | None = None):
    """Guarda las últimas propiedades mostradas y los filtros usados."""
    if telefono not in _cache:
        _cache[telefono] = {"timestamp": datetime.utcnow()}
    _cache[telefono]["propiedades"] = propiedades
    _cache[telefono]["timestamp"] = datetime.utcnow()
    if filtros:
        _cache[telefono]["filtros"] = filtros
    logger.debug(f"Cache: {len(propiedades)} propiedades guardadas para {telefono}")


def obtener_propiedades(telefono: str) -> list[dict]:
    """Recupera las últimas propiedades mostradas a un cliente."""
    datos = _cache.get(telefono)
    if not datos:
        return []
    # Verificar expiración
    if datetime.utcnow() - datos["timestamp"] > _TTL:
        del _cache[telefono]
        return []
    return datos["propiedades"]


def obtener_filtros(telefono: str) -> dict:
    """Recupera los filtros de la última búsqueda del cliente."""
    datos = _cache.get(telefono)
    if not datos:
        return {}
    if datetime.utcnow() - datos["timestamp"] > _TTL:
        return {}
    return datos.get("filtros", {})


def limpiar_cache_expirado():
    """Limpia entradas expiradas del cache."""
    ahora = datetime.utcnow()
    expirados = [tel for tel, datos in _cache.items() if ahora - datos["timestamp"] > _TTL]
    for tel in expirados:
        del _cache[tel]
