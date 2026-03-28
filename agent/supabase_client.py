# agent/supabase_client.py — Cliente Supabase singleton + helpers de consulta
# Generado por AgentKit — Phase 02-01

"""
Módulo de acceso a Supabase para la tabla propiedades.
Expone un cliente singleton y helpers tipados para queries y upserts.

Todas las funciones son async y deben llamarse con await desde endpoints FastAPI.
El cliente sync de supabase-py funciona correctamente en contexto async via httpx transport.
"""

import os
import logging
from supabase import create_client, Client

logger = logging.getLogger("agentkit")

# Singleton — se inicializa una sola vez al primer get_supabase()
_client: Client | None = None


def get_supabase() -> Client:
    """Retorna el cliente Supabase singleton. Se inicializa en el primer llamado."""
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
        logger.info("Cliente Supabase inicializado")
    return _client


async def buscar_propiedades_db(
    tipo: str = "",
    operacion: str = "",
    zona: str = "",
    precio_min: int = 0,
    precio_max: int = 0,
    ambientes: int = 0,
    limite: int = 5,
    offset: int = 0,
) -> list[dict]:
    """
    Consulta la tabla propiedades con filtros encadenados.

    Args:
        tipo: Tipo de propiedad (ilike match, ej: "departamento")
        operacion: Tipo de operación exacta (ej: "venta", "alquiler")
        zona: Zona/barrio (ilike match)
        precio_min: Precio mínimo en USD (0 = sin filtro)
        precio_max: Precio máximo en USD (0 = sin filtro)
        ambientes: Número exacto de ambientes (0 = sin filtro)
        limite: Cantidad máxima de resultados
        offset: Desplazamiento para paginación

    Returns:
        Lista de dicts con los campos de la tabla propiedades
    """
    sb = get_supabase()
    query = sb.table("propiedades").select("*")

    if tipo:
        query = query.ilike("tipo", f"%{tipo}%")
    if operacion:
        query = query.eq("operacion", operacion)
    if zona:
        query = query.ilike("zona", f"%{zona}%")
    if precio_min:
        query = query.gte("precio_num", precio_min)
    if precio_max:
        query = query.lte("precio_num", precio_max)
    if ambientes:
        query = query.eq("ambientes", ambientes)

    query = query.range(offset, offset + limite - 1)
    response = await query.execute()
    return response.data or []


async def upsert_propiedades(propiedades: list[dict]) -> int:
    """
    Bulk upsert — inserta o actualiza por propiedad_id.

    Args:
        propiedades: Lista de dicts con los campos de la tabla propiedades.
                     Cada dict DEBE incluir propiedad_id.

    Returns:
        Cantidad de registros procesados
    """
    if not propiedades:
        return 0
    sb = get_supabase()
    response = await sb.table("propiedades").upsert(
        propiedades,
        on_conflict="propiedad_id",
    ).execute()
    count = len(response.data or [])
    logger.info(f"Upsert completado: {count} propiedades")
    return count


async def obtener_todas_propiedades() -> list[dict]:
    """
    Retorna todas las propiedades de la tabla ordenadas por scraped_at desc.
    Usado para warm-up de cache al iniciar el servidor.

    Returns:
        Lista completa de propiedades
    """
    sb = get_supabase()
    response = await sb.table("propiedades").select("*").order(
        "scraped_at", desc=True
    ).execute()
    return response.data or []


async def marcar_removidas(ids_activos: list[str]) -> int:
    """
    Elimina propiedades que ya no están en el sitio web de Bertero.
    Se llama después de cada ciclo de scraping con la lista de IDs activos.

    Args:
        ids_activos: Lista de propiedad_id que siguen activos en el sitio

    Returns:
        Cantidad de registros eliminados
    """
    if not ids_activos:
        logger.warning("marcar_removidas: lista de IDs activos vacía, no se elimina nada por seguridad")
        return 0
    sb = get_supabase()
    response = await sb.table("propiedades").delete().not_.in_(
        "propiedad_id", ids_activos
    ).execute()
    count = len(response.data or [])
    if count:
        logger.info(f"Propiedades removidas del sitio eliminadas de Supabase: {count}")
    return count
