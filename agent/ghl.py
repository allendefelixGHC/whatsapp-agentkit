# agent/ghl.py — Integración con GoHighLevel CRM
# Generado por AgentKit

"""
Módulo de integración con GHL para Inmobiliaria Bertero.
Crea contactos, oportunidades y gestiona el pipeline de ventas.
"""

import os
import logging
import httpx
from dotenv import load_dotenv
from agent.utils import normalizar_telefono

load_dotenv()
logger = logging.getLogger("agentkit")

# Configuración de GHL
GHL_API_KEY = os.getenv("GHL_API_KEY")
GHL_API_BASE = "https://services.leadconnectorhq.com"
GHL_LOCATION_ID = os.getenv("GHL_LOCATION_ID", "TdZdFVt3WVzL6OoSX7iQ")
GHL_API_VERSION = "2021-07-28"

# IDs del pipeline y stages
PIPELINE_ID = "mld8sxsQ9YaNUEOxcw6M"
STAGES = {
    "lead_nuevo": "78344936-26bd-4b57-a090-d5fa7cef5c3e",
    "contactado_bot": "1b665c90-54d6-41ce-a9f6-54b9ea976a8a",
    "visita_agendada": "7b20fa68-352a-4829-908b-7ba487abbb1a",
    "visita_realizada": "f79c0368-725d-489f-b8b7-c2362ce01b84",
    "negociacion": "c6f1e6f0-eb1c-4b72-bc24-8272e9d1fcab",
    "cerrado_ganado": "507eeb81-f288-4c0a-af1c-0fd934f857f9",
    "cerrado_perdido": "f4a7c81c-6404-4e82-bfd0-dab8c3a7f886",
}

# ID del calendario
CALENDAR_ID = "lHxMCC26XkVuh8bSVCYz"
BOOKING_LINK = "https://api.leadconnectorhq.com/widget/booking/lHxMCC26XkVuh8bSVCYz"

# IDs de custom fields - Contacto
CF_OPERACION = "D784SzGzZd1wxrZSZeX0"
CF_TIPO_PROPIEDAD = "UFKay7cNDrv061NiWImd"
CF_ZONA = "gjYjeEXCvmX3qU2syjHn"
CF_VENDEDOR = "rz1m4u9s0cqZwnkwsH4z"

# IDs de custom fields - Oportunidad
CF_OPP_PROPIEDAD_ID = "KW70Fjj5Mk7gaaNzS2Ts"
CF_OPP_PROPIEDAD_LINK = "tNzOLBsK2wpOZ53H2ixX"
CF_OPP_PROPIEDAD_DIR = "dsdegtTSgPKHAw4xWafV"
CF_OPP_RESUMEN = "zUyMgEll105WZd6nEI0V"

# Asignación de vendedores por zona
VENDEDORES_POR_ZONA = {
    "centro": "Abhay Bertero",
    "nueva cordoba": "Abhay Bertero",
    "nueva córdoba": "Abhay Bertero",
    "guemes": "Abhay Bertero",
    "güemes": "Abhay Bertero",
    "alberdi": "Martin Lopez",
    "alta cordoba": "Martin Lopez",
    "alta córdoba": "Martin Lopez",
    "bajo palermo": "Martin Lopez",
    "villa carlos paz": "Martin Lopez",
    "unquillo": "Martin Lopez",
    "rio ceballos": "Martin Lopez",
    "río ceballos": "Martin Lopez",
    "sierras": "Martin Lopez",
}
VENDEDOR_DEFAULT = "Abhay Bertero"

# Contador round-robin para zonas sin vendedor asignado
_round_robin_counter = 0


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
    }


def asignar_vendedor(zona: str, productor: str = "") -> str:
    """
    Asigna un vendedor. Prioridad:
    1. productor de la propiedad (si existe en Supabase)
    2. zona del cliente (mapeo hardcoded)
    3. round-robin como fallback
    """
    global _round_robin_counter
    # Prioridad 1: productor de la propiedad seleccionada
    if productor and productor.strip():
        logger.info(f"Vendedor asignado por productor de propiedad: {productor.strip()}")
        return productor.strip()
    # Prioridad 2: zona del cliente
    zona_lower = zona.lower().strip()
    for key, vendedor in VENDEDORES_POR_ZONA.items():
        if key in zona_lower:
            return vendedor
    # Prioridad 3: round-robin
    vendedores = ["Abhay Bertero", "Martin Lopez"]
    vendedor = vendedores[_round_robin_counter % len(vendedores)]
    _round_robin_counter += 1
    return vendedor


async def crear_o_actualizar_contacto(
    telefono: str,
    nombre: str = "",
    email: str = "",
    operacion: str = "",
    tipo_propiedad: str = "",
    zona: str = "",
    productor: str = "",
) -> dict:
    """
    Crea o actualiza un contacto en GHL (upsert por teléfono).
    Retorna los datos del contacto creado/actualizado.
    """
    if not GHL_API_KEY:
        logger.warning("GHL_API_KEY no configurada")
        return {"error": "GHL no configurado"}

    # Normalizar a forma canónica interna (ej: "5493517575244")
    digits_only = normalizar_telefono(telefono)
    if len(digits_only) < 8:
        logger.warning(f"Teléfono inválido para GHL: {telefono}")
        return {"error": "Teléfono inválido", "id": "", "vendedor": asignar_vendedor(zona) if zona else VENDEDOR_DEFAULT}
    # GHL necesita +543517575244 (sin el 9 móvil AR)
    # normalizar_telefono retorna 5493517575244 (con 9) → remover el 9 para GHL
    tel_ghl = digits_only
    if tel_ghl.startswith("549") and len(tel_ghl) == 13:
        tel_ghl = "54" + tel_ghl[3:]
        logger.info(f"Teléfono normalizado para GHL: {digits_only} → +{tel_ghl}")
    tel_limpio = f"+{tel_ghl}"

    # Asignar vendedor (prioridad: productor de propiedad > zona > round-robin)
    vendedor = asignar_vendedor(zona, productor=productor) if (zona or productor) else VENDEDOR_DEFAULT

    # Separar nombre en first/last
    partes_nombre = nombre.strip().split(" ", 1) if nombre else ["", ""]
    first_name = partes_nombre[0]
    last_name = partes_nombre[1] if len(partes_nombre) > 1 else ""

    payload = {
        "locationId": GHL_LOCATION_ID,
        "phone": tel_limpio,
        "source": "WhatsApp Bot - AgentKit",
        "tags": ["bot-whatsapp", "inmobiliaria-bertero"],
        "customFields": [
            {"id": CF_VENDEDOR, "value": vendedor},
        ],
    }

    if first_name:
        payload["firstName"] = first_name
    if last_name:
        payload["lastName"] = last_name
    if email:
        payload["email"] = email
    if operacion:
        payload["customFields"].append({"id": CF_OPERACION, "value": operacion})
        payload["tags"].append(operacion.lower())
    if tipo_propiedad:
        payload["customFields"].append({"id": CF_TIPO_PROPIEDAD, "value": tipo_propiedad})
    if zona:
        payload["customFields"].append({"id": CF_ZONA, "value": zona})
        payload["tags"].append(zona.lower().replace(" ", "-"))

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Usar upsert para no duplicar
            r = await client.post(
                f"{GHL_API_BASE}/contacts/upsert",
                json=payload,
                headers=_headers(),
            )
            if r.status_code in (200, 201):
                data = r.json()
                contact = data.get("contact", {})
                logger.info(f"Contacto GHL creado/actualizado: {contact.get('id')} — {nombre} ({tel_limpio})")
                return {
                    "id": contact.get("id", ""),
                    "nombre": nombre,
                    "telefono": tel_limpio,
                    "vendedor": vendedor,
                    "es_nuevo": data.get("new", True),
                }
            else:
                logger.error(f"Error GHL contacto: {r.status_code} — {r.text}")
                return {"error": f"Error {r.status_code}"}
    except Exception as e:
        logger.error(f"Error creando contacto GHL: {e}")
        return {"error": str(e)}


async def crear_oportunidad(
    contact_id: str,
    nombre_contacto: str,
    operacion: str = "Comprar",
    propiedad_id: str = "",
    propiedad_link: str = "",
    propiedad_direccion: str = "",
    resumen: str = "",
    valor: float = 0,
) -> dict:
    """
    Crea una oportunidad en el pipeline de Inmobiliaria.
    """
    if not GHL_API_KEY:
        logger.warning("GHL_API_KEY no configurada")
        return {"error": "GHL no configurado"}

    nombre_opp = f"{operacion} — {nombre_contacto}"
    if propiedad_direccion:
        nombre_opp += f" — {propiedad_direccion}"

    payload = {
        "locationId": GHL_LOCATION_ID,
        "pipelineId": PIPELINE_ID,
        "pipelineStageId": STAGES["lead_nuevo"],
        "contactId": contact_id,
        "name": nombre_opp,
        "status": "open",
        "monetaryValue": valor,
        "customFields": [],
    }

    if propiedad_id:
        payload["customFields"].append({"id": CF_OPP_PROPIEDAD_ID, "value": propiedad_id})
    if propiedad_link:
        payload["customFields"].append({"id": CF_OPP_PROPIEDAD_LINK, "value": propiedad_link})
    if propiedad_direccion:
        payload["customFields"].append({"id": CF_OPP_PROPIEDAD_DIR, "value": propiedad_direccion})
    if resumen:
        payload["customFields"].append({"id": CF_OPP_RESUMEN, "value": resumen})

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{GHL_API_BASE}/opportunities/",
                json=payload,
                headers=_headers(),
            )
            if r.status_code in (200, 201):
                opp = r.json().get("opportunity", {})
                logger.info(f"Oportunidad GHL creada: {opp.get('id')} — {nombre_opp}")
                return {
                    "id": opp.get("id", ""),
                    "nombre": nombre_opp,
                    "pipeline": "Inmobiliaria - Ventas",
                    "stage": "Lead nuevo",
                }
            else:
                # Oportunidad duplicada no es un error real — el contacto ya existe en el pipeline
                error_body = r.text
                if "duplicate" in error_body.lower():
                    logger.info(f"Oportunidad GHL ya existe para contacto — no es error, es duplicado")
                    return {"duplicada": True, "nombre": nombre_opp}
                logger.error(f"Error GHL oportunidad: {r.status_code} — {error_body}")
                return {"error": f"Error {r.status_code}"}
    except Exception as e:
        logger.error(f"Error creando oportunidad GHL: {e}")
        return {"error": str(e)}


async def mover_oportunidad(oportunidad_id: str, stage: str) -> bool:
    """Mueve una oportunidad a un stage diferente del pipeline."""
    if not GHL_API_KEY or stage not in STAGES:
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.put(
                f"{GHL_API_BASE}/opportunities/{oportunidad_id}",
                json={"pipelineStageId": STAGES[stage]},
                headers=_headers(),
            )
            if r.status_code == 200:
                logger.info(f"Oportunidad {oportunidad_id} movida a: {stage}")
                return True
            else:
                logger.error(f"Error moviendo oportunidad: {r.status_code}")
                return False
    except Exception as e:
        logger.error(f"Error moviendo oportunidad GHL: {e}")
        return False


async def buscar_oportunidad_por_contacto(contact_id: str) -> str | None:
    """Busca la oportunidad más reciente de un contacto en el pipeline. Retorna el ID o None."""
    if not GHL_API_KEY or not contact_id:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{GHL_API_BASE}/opportunities/search",
                params={
                    "location_id": GHL_LOCATION_ID,
                    "pipeline_id": PIPELINE_ID,
                    "contact_id": contact_id,
                    "status": "open",
                    "limit": 1,
                    "order": "added_asc",
                },
                headers=_headers(),
            )
            if r.status_code == 200:
                opps = r.json().get("opportunities", [])
                if opps:
                    opp_id = opps[0]["id"]
                    logger.info(f"Oportunidad encontrada para contacto {contact_id}: {opp_id}")
                    return opp_id
            logger.warning(f"No se encontró oportunidad para contacto {contact_id}")
            return None
    except Exception as e:
        logger.error(f"Error buscando oportunidad: {e}")
        return None


async def obtener_detalles_oportunidad(oportunidad_id: str) -> dict:
    """Obtiene los detalles de una oportunidad (nombre, dirección, link, resumen)."""
    if not GHL_API_KEY or not oportunidad_id:
        return {}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{GHL_API_BASE}/opportunities/{oportunidad_id}",
                headers=_headers(),
            )
            if r.status_code == 200:
                opp = r.json().get("opportunity", {})
                nombre_opp = opp.get("name", "")
                custom = {cf["id"]: cf.get("fieldValue", cf.get("fieldValueString", cf.get("value", ""))) for cf in opp.get("customFields", [])}

                # Leer de custom fields primero
                direccion = custom.get(CF_OPP_PROPIEDAD_DIR, "")
                link = custom.get(CF_OPP_PROPIEDAD_LINK, "")
                resumen = custom.get(CF_OPP_RESUMEN, "")

                # Si custom fields están vacíos, extraer del nombre de la oportunidad
                # Formato: "Operacion — Nombre — Dirección"
                if not direccion and " — " in nombre_opp:
                    partes = nombre_opp.split(" — ")
                    if len(partes) >= 3:
                        direccion = partes[2].strip()

                if not resumen and nombre_opp:
                    resumen = nombre_opp

                # Reconstruir link desde propiedad_id si el link está vacío
                propiedad_id = custom.get(CF_OPP_PROPIEDAD_ID, "")
                if not link and propiedad_id:
                    link = f"https://www.inmobiliariabertero.com.ar/p/{propiedad_id}"

                logger.info(f"Detalles oportunidad {oportunidad_id}: dir={direccion}, link={link[:50] if link else 'N/A'}")
                return {
                    "nombre_opp": nombre_opp,
                    "propiedad_direccion": direccion,
                    "propiedad_link": link,
                    "propiedad_resumen": resumen,
                }
            return {}
    except Exception as e:
        logger.error(f"Error obteniendo detalles oportunidad: {e}")
        return {}


async def buscar_contacto_por_email(email: str) -> str | None:
    """Busca un contacto por email. Retorna el contactId o None."""
    if not GHL_API_KEY or not email:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{GHL_API_BASE}/contacts/",
                params={
                    "locationId": GHL_LOCATION_ID,
                    "query": email,
                    "limit": 1,
                },
                headers=_headers(),
            )
            if r.status_code == 200:
                contacts = r.json().get("contacts", [])
                if contacts:
                    return contacts[0]["id"]
            return None
    except Exception as e:
        logger.error(f"Error buscando contacto por email: {e}")
        return None


async def buscar_contacto_por_telefono(telefono: str) -> str | None:
    """Busca un contacto por teléfono. Retorna el contactId o None."""
    datos = await buscar_datos_contacto_por_telefono(telefono)
    return datos.get("id") if datos else None


async def buscar_datos_contacto_por_telefono(telefono: str) -> dict | None:
    """Busca un contacto por teléfono. Retorna dict con id, nombre, email o None."""
    if not GHL_API_KEY or not telefono:
        return None

    # Normalizar a formato GHL (+543...) para la búsqueda
    tel_norm = normalizar_telefono(telefono)
    if tel_norm.startswith("549") and len(tel_norm) == 13:
        tel_norm = "54" + tel_norm[3:]
    tel_query = f"+{tel_norm}" if tel_norm else telefono

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{GHL_API_BASE}/contacts/",
                params={
                    "locationId": GHL_LOCATION_ID,
                    "query": tel_query,
                    "limit": 1,
                },
                headers=_headers(),
            )
            if r.status_code == 200:
                contacts = r.json().get("contacts", [])
                if contacts:
                    c = contacts[0]
                    nombre = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
                    return {
                        "id": c.get("id", ""),
                        "nombre": nombre,
                        "email": c.get("email", ""),
                    }
            return None
    except Exception as e:
        logger.error(f"Error buscando contacto por teléfono: {e}")
        return None


def obtener_link_booking(nombre: str = "", email: str = "", telefono: str = "") -> str:
    """Retorna el link de booking pre-llenado con datos del cliente."""
    from urllib.parse import urlencode
    params = {"locale": "es"}
    if nombre:
        # GHL widget usa first_name y last_name (con guión bajo)
        partes = nombre.strip().split(" ", 1)
        params["first_name"] = partes[0]
        if len(partes) > 1:
            params["last_name"] = partes[1]
    if email:
        params["email"] = email
    if telefono:
        # Limpiar el teléfono: solo dígitos, sin prefijo whatsapp
        tel = telefono.replace("whatsapp:", "").replace("+", "").replace(" ", "").replace("-", "")
        params["phone"] = f"+{tel}"
    query = urlencode(params)
    return f"{BOOKING_LINK}?{query}"
