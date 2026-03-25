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


def asignar_vendedor(zona: str) -> str:
    """Asigna un vendedor según la zona del cliente."""
    global _round_robin_counter
    zona_lower = zona.lower().strip()
    for key, vendedor in VENDEDORES_POR_ZONA.items():
        if key in zona_lower:
            return vendedor
    # Round-robin si no hay zona específica
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
) -> dict:
    """
    Crea o actualiza un contacto en GHL (upsert por teléfono).
    Retorna los datos del contacto creado/actualizado.
    """
    if not GHL_API_KEY:
        logger.warning("GHL_API_KEY no configurada")
        return {"error": "GHL no configurado"}

    # Limpiar teléfono (remover @s.whatsapp.net si viene del webhook)
    tel_limpio = telefono.replace("@s.whatsapp.net", "").replace("@c.us", "").replace("+", "")
    # Solo dígitos para validación
    digits_only = "".join(c for c in tel_limpio if c.isdigit())
    if len(digits_only) < 8:
        logger.warning(f"Teléfono inválido para GHL: {telefono}")
        return {"error": "Teléfono inválido", "id": "", "vendedor": asignar_vendedor(zona) if zona else VENDEDOR_DEFAULT}
    tel_limpio = digits_only
    # Fix teléfono argentino: WhatsApp envía 5493517575244 (con 9 móvil)
    # pero GHL necesita +543517575244 (sin el 9 móvil)
    if tel_limpio.startswith("549") and len(tel_limpio) == 13:
        tel_limpio = "54" + tel_limpio[3:]
        logger.info(f"Teléfono argentino normalizado: 549... → +{tel_limpio}")
    tel_limpio = f"+{tel_limpio}"

    # Asignar vendedor
    vendedor = asignar_vendedor(zona) if zona else VENDEDOR_DEFAULT

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
                logger.error(f"Error GHL oportunidad: {r.status_code} — {r.text}")
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


def obtener_link_booking(nombre: str = "", email: str = "") -> str:
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
    # Nota: NO pasamos phone — GHL widget no lo maneja bien
    query = urlencode(params)
    return f"{BOOKING_LINK}?{query}"
