# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas para Inmobiliaria Bertero.
Funciones de FAQ, búsqueda de propiedades en tiempo real, agendamiento de citas y calificación de leads.
"""

import os
import re
import yaml
import logging
import httpx
from datetime import datetime

from agent.session import guardar_propiedades, obtener_propiedades
from agent.providers.base import Respuesta, SeccionLista, FilaLista

logger = logging.getLogger("agentkit")

BASE_URL = "https://www.inmobiliariabertero.com.ar"

# Cache de propiedades — se refresca cada 10 minutos
_propiedades_cache = []
_propiedades_cache_time = 0
CACHE_TTL = 600  # 10 minutos

# Mapeo de tipos de propiedad a IDs de Tokko Broker
TIPOS_PROPIEDAD = {
    "departamento": "2",
    "depto": "2",
    "dpto": "2",
    "casa": "3",
    "terreno": "1",
    "lote": "1",
    "local": "7",
    "galpon": "9",
    "galpón": "9",
    "oficina": "5",
    "cochera": "10",
    "ph": "13",
}

# Mapeo de operaciones
OPERACIONES = {
    "venta": "1",
    "compra": "1",
    "comprar": "1",
    "alquiler": "2",
    "alquilar": "2",
    "renta": "2",
}


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio."""
    info = cargar_info_negocio()
    return {
        "horario": info.get("negocio", {}).get("horario", "No disponible"),
        "esta_abierto": True,
    }


def buscar_en_knowledge(consulta: str) -> str:
    """Busca información relevante en los archivos de /knowledge."""
    resultados = []
    knowledge_dir = "knowledge"
    if not os.path.exists(knowledge_dir):
        return "No hay archivos de conocimiento disponibles."
    for archivo in os.listdir(knowledge_dir):
        ruta = os.path.join(knowledge_dir, archivo)
        if archivo.startswith(".") or not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                if consulta.lower() in contenido.lower():
                    resultados.append(f"[{archivo}]: {contenido[:500]}")
        except (UnicodeDecodeError, IOError):
            continue
    if resultados:
        return "\n---\n".join(resultados)
    return "No encontré información específica sobre eso en mis archivos."


async def buscar_propiedades(
    tipo: str = "",
    zona: str = "",
    operacion: str = "",
    precio_min: str = "",
    precio_max: str = "",
    ambientes: str = "",
    limite: int = 5,
    pagina: int = 1,
    telefono: str = "",
) -> str:
    """
    Busca propiedades en tiempo real desde la web de Inmobiliaria Bertero.
    La web no filtra server-side, así que descargamos todo y filtramos acá.
    Usa pagina=2, pagina=3, etc. para ver más resultados.
    """
    try:
        global _propiedades_cache, _propiedades_cache_time
        import time

        # Usar cache si está fresco (menos de 10 minutos)
        ahora = time.time()
        if _propiedades_cache and (ahora - _propiedades_cache_time) < CACHE_TTL:
            todas = list(_propiedades_cache)
            logger.info(f"Propiedades desde cache: {len(todas)}")
        else:
            # Descargar todas las páginas de propiedades
            todas = []
            async with httpx.AsyncClient(timeout=15.0) as client:
                for page in range(1, 5):  # Hasta 4 páginas (80 propiedades)
                    r = await client.get(f"{BASE_URL}/Propiedades", params={"p": str(page)})
                    if r.status_code != 200:
                        break
                    nuevas = _parsear_listado(r.text)
                    if not nuevas:
                        break
                    todas.extend(nuevas)

            _propiedades_cache = list(todas)
            _propiedades_cache_time = ahora
            logger.info(f"Total propiedades parseadas y cacheadas: {len(todas)}")

        # Filtrar por tipo
        if tipo:
            tipo_lower = tipo.lower().strip()
            # Mapear sinónimos
            tipo_map = {"depto": "departamento", "dpto": "departamento", "lote": "terreno", "galpón": "galpon"}
            tipo_buscar = tipo_map.get(tipo_lower, tipo_lower)
            todas = [p for p in todas if tipo_buscar in p["tipo"].lower()]

        # Filtrar por operación
        if operacion:
            op_lower = operacion.lower().strip()
            op_map = {"compra": "venta", "comprar": "venta", "alquilar": "alquiler", "renta": "alquiler"}
            op_buscar = op_map.get(op_lower, op_lower)
            todas = [p for p in todas if op_buscar in p["operacion"].lower()]

        # Filtrar por zona
        if zona and zona.lower() not in ("todas", "todas las zonas", "cualquiera"):
            zona_lower = zona.lower().strip()
            todas = [p for p in todas if zona_lower in p["zona"].lower()]

        # Filtrar por precio
        precio_min_num = int(precio_min) if precio_min and precio_min.isdigit() else 0
        precio_max_num = int(precio_max) if precio_max and precio_max.isdigit() else 0
        if precio_min_num or precio_max_num:
            filtradas = []
            for p in todas:
                precio_num = p.get("precio_num", 0)
                if precio_num <= 0:
                    continue  # Omitir si no tiene precio
                if precio_min_num and precio_num < precio_min_num:
                    continue
                if precio_max_num and precio_num > precio_max_num:
                    continue
                filtradas.append(p)
            todas = filtradas

        if not todas:
            filtros = []
            if tipo:
                filtros.append(f"tipo: {tipo}")
            if zona and zona.lower() not in ("todas", "todas las zonas"):
                filtros.append(f"zona: {zona}")
            if precio_max_num:
                filtros.append(f"hasta USD {precio_max_num:,}")
            filtros_str = ", ".join(filtros) if filtros else "los filtros seleccionados"
            return (
                f"No encontré propiedades con {filtros_str}.\n\n"
                f"Sugerencias:\n"
                f"- Probá ampliando la zona o el presupuesto\n"
                f"- Revisá todas las opciones en: www.inmobiliariabertero.com.ar/Propiedades\n"
                f"- O contactanos para que un asesor te ayude a encontrar lo que buscás"
            )

        total_encontradas = len(todas)

        # Paginación
        inicio = (pagina - 1) * limite
        fin = inicio + limite
        pagina_actual = todas[inicio:fin]

        if not pagina_actual and pagina > 1:
            return f"No hay más propiedades para mostrar. Ya te mostré las {total_encontradas} disponibles."

        # Formatear resultado
        resultado = f"Encontré {total_encontradas} propiedad(es) en total"
        if total_encontradas > limite:
            resultado += f" (mostrando {inicio + 1}-{min(fin, total_encontradas)})"
        resultado += ":\n\n"

        for i, prop in enumerate(pagina_actual, inicio + 1):
            resultado += f"{i}. {prop['tipo']} en {prop['operacion']} — {prop['zona']}\n"
            if prop['precio']:
                resultado += f"   Precio: {prop['precio']}\n"
            if prop['direccion']:
                resultado += f"   Dirección: {prop['direccion']}\n"
            sup = prop.get('superficie', '')
            if sup and not sup.startswith("0"):
                resultado += f"   Superficie: {sup}\n"
            resultado += f"   Ver detalle: {BASE_URL}{prop['link']}\n\n"

        if fin < total_encontradas:
            resultado += f"Hay {total_encontradas - fin} propiedades más. Pedime 'ver más' para la siguiente página.\n"

        # Guardar propiedades mostradas en cache de sesión para lista de visitas
        if telefono:
            # Acumular: si es página 2+, sumar a las anteriores
            props_previas = obtener_propiedades(telefono) if pagina > 1 else []
            props_nuevas = props_previas + pagina_actual
            guardar_propiedades(telefono, props_nuevas)
        else:
            # Sin teléfono, guardar con key genérica (fallback)
            guardar_propiedades("_last", pagina_actual)

        return resultado

    except httpx.TimeoutException:
        logger.error("Timeout buscando propiedades")
        return "La búsqueda tardó demasiado. Podés ver las propiedades en: www.inmobiliariabertero.com.ar/Propiedades"
    except Exception as e:
        logger.error(f"Error en búsqueda de propiedades: {e}")
        return "Hubo un error buscando propiedades. Revisá nuestra web: www.inmobiliariabertero.com.ar/Propiedades"


async def obtener_detalle_propiedad(propiedad_id: str) -> str:
    """
    Obtiene el detalle completo de una propiedad específica.

    Args:
        propiedad_id: ID de la propiedad (ej: "7778974")

    Returns:
        Texto formateado con los detalles de la propiedad
    """
    try:
        # Primero buscar el link completo en el listado
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # Buscar en el listado para obtener el slug completo
            r = await client.get(f"{BASE_URL}/Propiedades", params={"q": "", "p": "1"})
            html = r.text

            # Buscar el link que contiene el ID
            pattern = rf'href="(/p/{propiedad_id}[^"]*)"'
            match = re.search(pattern, html)

            if not match:
                # Probar buscando en más páginas
                for page in range(2, 5):
                    r = await client.get(f"{BASE_URL}/Propiedades", params={"q": "", "p": str(page)})
                    match = re.search(pattern, r.text)
                    if match:
                        break

            if not match:
                return f"No encontré la propiedad con ID {propiedad_id}."

            link = match.group(1)
            r = await client.get(f"{BASE_URL}{link}")

            if r.status_code != 200:
                return f"No pude obtener los detalles de la propiedad. Podés verla en: {BASE_URL}{link}"

            return _parsear_detalle(r.text, link)

    except Exception as e:
        logger.error(f"Error obteniendo detalle de propiedad {propiedad_id}: {e}")
        return "Hubo un error al consultar los detalles. Revisá la web: www.inmobiliariabertero.com.ar/Propiedades"


def _parsear_listado(html: str) -> list[dict]:
    """
    Parsea el HTML del listado de propiedades.
    Extrae tipo, operación, zona y dirección del slug del link.
    Extrae precio y superficie del HTML entre propiedades.
    """
    propiedades = []

    # Encontrar todos los links de propiedades con regex posicional
    links = list(re.finditer(r'href="(/p/(\d+)-([^"]+))"', html))

    seen_ids = set()
    for i, match in enumerate(links):
        pid = match.group(2)
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        link = match.group(1)
        slug = match.group(3)

        # Extraer tipo, operación, zona del slug: Tipo-en-Operacion-en-Zona-Direccion
        partes = slug.split("-en-")
        tipo = partes[0].replace("-", " ") if len(partes) > 0 else ""
        operacion = partes[1].replace("-", " ") if len(partes) > 1 else ""
        resto = partes[2] if len(partes) > 2 else ""

        # La zona es la primera parte antes de la dirección
        # Ej: "Nueva-Cordoba-Ituzaingo--al-400" → zona="Nueva Cordoba"
        # Ej: "Centro-Humberto-Primo-al-800" → zona="Centro"
        zona = ""
        direccion = ""
        if resto:
            # Buscar patrón de dirección (calle + número)
            dir_match = re.search(r'(.+?)[-,]?\s*(?:al\s*\d|esquina|\d{2,})', resto, re.IGNORECASE)
            if dir_match:
                zona_parte = dir_match.group(1).rstrip("-").replace("-", " ").strip()
                zona = zona_parte
                direccion = resto.replace("-", " ").replace("  ", " ").strip()
            else:
                zona = resto.replace("-", " ").strip()

        # Buscar precio en el bloque HTML ANTES de este link
        precio = ""
        precio_num = 0
        start = links[i - 1].end() if i > 0 else 0
        bloque = html[start:match.start()]
        precios = re.findall(r'(USD|U\$S)\s*([\d.,]+)', bloque)
        if precios:
            moneda, valor = precios[-1]  # Último precio del bloque
            precio = f"USD {valor}"
            # Parsear número para filtrado
            try:
                precio_num = int(valor.replace(".", "").replace(",", ""))
            except ValueError:
                pass

        # Buscar superficie en el bloque
        superficie = ""
        sup_matches = re.findall(r'(\d+(?:[.,]\d+)?)\s*m[²2]', bloque)
        if sup_matches:
            superficie = f"{sup_matches[-1]} m²"

        propiedades.append({
            "id": pid,
            "link": link,
            "tipo": tipo,
            "operacion": operacion,
            "zona": zona,
            "direccion": direccion,
            "precio": precio,
            "precio_num": precio_num,
            "superficie": superficie,
        })

    return propiedades


def _parsear_detalle(html: str, link: str) -> str:
    """Parsea el HTML de detalle de una propiedad y retorna texto formateado."""
    resultado = ""

    # Título
    titulo_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    titulo = titulo_match.group(1).strip() if titulo_match else "Propiedad"
    resultado += f"{titulo}\n\n"

    # Precio
    precio_match = re.search(r'(USD|U\$S)\s*[\d.,]+', html)
    if precio_match:
        resultado += f"Precio: {precio_match.group(0)}\n"

    # Dirección
    dir_match = re.search(r'class="[^"]*address[^"]*"[^>]*>([^<]+)', html)
    if dir_match:
        resultado += f"Dirección: {dir_match.group(1).strip()}\n"

    # Características principales — buscar en la sección de features
    specs = []
    # Ambientes
    amb = re.search(r'(\d+)\s*ambiente', html, re.IGNORECASE)
    if amb:
        specs.append(f"Ambientes: {amb.group(1)}")
    # Dormitorios
    dorm = re.search(r'(\d+)\s*dormitorio', html, re.IGNORECASE)
    if dorm:
        specs.append(f"Dormitorios: {dorm.group(1)}")
    # Baños
    banos = re.search(r'(\d+)\s*ba[ñn]o', html, re.IGNORECASE)
    if banos:
        specs.append(f"Baños: {banos.group(1)}")
    # Superficie cubierta
    sup_cub = re.search(r'[Ss]up(?:erficie)?\.?\s*[Cc]ub(?:ierta)?\.?\s*:?\s*(\d+(?:\.\d+)?)\s*m', html)
    if sup_cub:
        specs.append(f"Sup. cubierta: {sup_cub.group(1)} m²")
    # Superficie total
    sup_tot = re.search(r'[Ss]up(?:erficie)?\.?\s*[Tt]ot(?:al)?\.?\s*:?\s*(\d+(?:\.\d+)?)\s*m', html)
    if sup_tot:
        specs.append(f"Sup. total: {sup_tot.group(1)} m²")
    # Antigüedad
    ant = re.search(r'[Aa]ntig[üu]edad\s*:?\s*(\d+)\s*a[ñn]o', html)
    if ant:
        specs.append(f"Antigüedad: {ant.group(1)} años")
    # Expensas
    exp = re.search(r'[Ee]xpensas\s*:?\s*\$?\s*([\d.,]+)', html)
    if exp:
        specs.append(f"Expensas: ${exp.group(1)}")

    if specs:
        resultado += "\n".join(specs) + "\n"

    # Descripción — buscar el bloque de descripción
    desc_match = re.search(r'class="[^"]*description[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    if desc_match:
        desc = re.sub(r'<[^>]+>', ' ', desc_match.group(1))
        desc = re.sub(r'\s+', ' ', desc).strip()
        if desc and len(desc) > 10:
            resultado += f"\nDescripción: {desc[:500]}\n"

    resultado += f"\nVer fotos y más detalles: {BASE_URL}{link}\n"

    return resultado


async def registrar_lead_ghl(
    telefono: str,
    nombre: str,
    email: str = "",
    operacion: str = "",
    tipo_propiedad: str = "",
    zona: str = "",
    propiedad_id: str = "",
    propiedad_link: str = "",
    propiedad_direccion: str = "",
    resumen: str = "",
) -> str:
    """
    Registra un lead en GHL: crea contacto + oportunidad en el pipeline.
    Retorna confirmación con datos del lead, vendedor asignado y link de booking pre-llenado.
    """
    from agent.ghl import crear_o_actualizar_contacto, crear_oportunidad, obtener_link_booking

    # 1. Crear/actualizar contacto
    contacto = await crear_o_actualizar_contacto(
        telefono=telefono,
        nombre=nombre,
        email=email,
        operacion=operacion,
        tipo_propiedad=tipo_propiedad,
        zona=zona,
    )

    booking_link = obtener_link_booking(nombre=nombre, email=email, telefono=telefono)

    if contacto.get("error") and not contacto.get("id"):
        vendedor = contacto.get("vendedor", "un asesor")
        return (
            f"No pude registrar el lead en el CRM pero el vendedor asignado es {vendedor}.\n"
            f"Link de booking para agendar visita: {booking_link}\n"
        )

    # 2. Crear oportunidad
    oportunidad = await crear_oportunidad(
        contact_id=contacto["id"],
        nombre_contacto=nombre,
        operacion=operacion,
        propiedad_id=propiedad_id,
        propiedad_link=propiedad_link,
        propiedad_direccion=propiedad_direccion,
        resumen=resumen,
    )

    resultado = f"Lead registrado exitosamente en el CRM.\n"
    resultado += f"Nombre: {nombre}\n"
    if email:
        resultado += f"Email: {email}\n"
    resultado += f"Vendedor asignado: {contacto.get('vendedor', 'No asignado')}\n"
    if oportunidad.get("id"):
        resultado += f"Oportunidad creada: {oportunidad.get('nombre', '')}\n"
    resultado += f"Link de booking para agendar visita (pre-llenado con nombre y email): {booking_link}\n"

    return resultado


async def obtener_link_agendar() -> str:
    """Retorna el link de booking para que el cliente agende una visita."""
    from agent.ghl import obtener_link_booking
    return f"Link para agendar visita: {obtener_link_booking()}"


def _abreviar_zona(zona: str) -> str:
    """Abrevia nombres de zona para que quepan en 24 chars de título de WhatsApp."""
    # Remover palabras redundantes
    zona = zona.replace("De Las ", "de las ").replace("Del ", "del ")
    # Abreviaciones comunes
    abreviaciones = {
        "Quebrada De Las Rosa": "Qda. de las Rosas",
        "Quebrada de las Rosa": "Qda. de las Rosas",
        "General Pueyrredon": "Gral. Pueyrredón",
        "General Pueyrredón": "Gral. Pueyrredón",
        "Chateau Carreras Chateau Carreras": "Chateau Carreras",
        "Villa Carlos Paz": "V. Carlos Paz",
        "Rio Ceballos Belisario Roldán": "Río Ceballos",
        "Rio Ceballos": "Río Ceballos",
        "Alta Cordoba": "Alta Córdoba",
        "Nueva Cordoba": "Nueva Córdoba",
        "Maipú Sección 2": "Maipú Secc. 2",
        "Bajo Palermo": "Bajo Palermo",
        "Yacanto Yacanto, San Javier": "Yacanto, San Javier",
        "Yacanto, San Javier": "Yacanto, S. Javier",
    }
    for largo, corto in abreviaciones.items():
        if largo.lower() in zona.lower():
            return corto
    # Si tiene coma, tomar solo la primera parte
    if "," in zona:
        zona = zona.split(",")[0].strip()
    # Remover duplicados (ej: "Alberdi Mendoza 271" → "Alberdi")
    palabras = zona.split()
    if len(palabras) > 2:
        # Intentar quedarse con las 2 primeras palabras
        zona_corta = " ".join(palabras[:2])
        if len(zona_corta) <= 20:  # Dejar espacio para "N. "
            return zona_corta
    return zona


def obtener_propiedades_para_visita(telefono: str) -> Respuesta:
    """
    Retorna una lista interactiva con las propiedades mostradas al cliente
    para que elija cuál quiere visitar.
    """
    propiedades = obtener_propiedades(telefono)
    if not propiedades:
        return Respuesta(
            tipo="texto",
            texto="No tengo propiedades recientes para mostrarte. ¿Querés que busquemos propiedades primero?",
        )

    # Armar filas de lista (máximo 10 — límite de WhatsApp)
    filas = []
    for i, prop in enumerate(propiedades[:10], 1):
        # Titulo: número + zona/dirección optimizada para 24 chars
        zona = prop.get('zona', '').strip()
        zona = _abreviar_zona(zona)
        titulo = f"{i}. {zona}" if zona else f"{i}. Prop. {prop.get('id', '')}"
        # Si aún no cabe, recortar sin "..."
        if len(titulo) > 24:
            titulo = titulo[:24]

        # Descripción: tipo + precio + dirección + superficie (máx 72 chars)
        desc_parts = []
        desc_parts.append(prop.get('tipo', 'Propiedad'))
        if prop.get("precio"):
            desc_parts.append(prop["precio"])
        if prop.get("direccion"):
            # Solo la parte de la dirección sin repetir la zona
            dir_limpia = prop["direccion"].replace(zona, "").strip().strip(",").strip()
            if dir_limpia:
                desc_parts.append(dir_limpia)
        sup = prop.get("superficie", "")
        if sup and not sup.startswith("0"):
            desc_parts.append(sup)
        descripcion = " | ".join(desc_parts)
        if len(descripcion) > 72:
            descripcion = descripcion[:69] + "..."

        filas.append(FilaLista(
            id=f"visita_prop_{prop.get('id', '')}",
            titulo=titulo,
            descripcion=descripcion,
        ))

    return Respuesta(
        tipo="lista",
        texto="¿A cuál de estas propiedades te gustaría agendar una visita?",
        texto_boton_lista="Ver propiedades",
        secciones=[SeccionLista(titulo="Propiedades", filas=filas)],
    )


# Definición de herramientas para Claude tool_use
TOOLS_DEFINITION = [
    {
        "name": "buscar_propiedades",
        "description": "Busca propiedades disponibles en tiempo real en la web de Inmobiliaria Bertero. Usa esta herramienta SIEMPRE que un cliente pregunte por propiedades, precios, o quiera ver opciones disponibles. Cuando el cliente pide 'ver más opciones', llamá esta herramienta de nuevo con los MISMOS filtros pero pagina=2 (o 3, 4, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {
                    "type": "string",
                    "description": "Tipo de propiedad: departamento, casa, terreno, local, galpon, oficina, cochera, ph",
                },
                "zona": {
                    "type": "string",
                    "description": "Zona, barrio o localidad. Ej: Nueva Cordoba, Centro, Alberdi, Villa Carlos Paz",
                },
                "operacion": {
                    "type": "string",
                    "description": "Tipo de operación: venta o alquiler",
                },
                "precio_max": {
                    "type": "string",
                    "description": "Precio máximo en USD (solo el número, ej: 100000)",
                },
                "precio_min": {
                    "type": "string",
                    "description": "Precio mínimo en USD (solo el número, ej: 50000)",
                },
                "ambientes": {
                    "type": "string",
                    "description": "Cantidad de ambientes (1-6)",
                },
                "pagina": {
                    "type": "integer",
                    "description": "Página de resultados (default 1). Usá 2, 3, etc. para ver más opciones con los mismos filtros.",
                },
                "telefono": {
                    "type": "string",
                    "description": "Teléfono del cliente (viene del contexto interno). SIEMPRE pasalo para guardar los resultados de la búsqueda.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "obtener_detalle_propiedad",
        "description": "Obtiene información detallada de una propiedad específica por su ID. Usa esta herramienta cuando el cliente quiera más detalles de una propiedad en particular.",
        "input_schema": {
            "type": "object",
            "properties": {
                "propiedad_id": {
                    "type": "string",
                    "description": "ID numérico de la propiedad (ej: 7778974)",
                },
            },
            "required": ["propiedad_id"],
        },
    },
    {
        "name": "registrar_lead_ghl",
        "description": """Registra un lead en el CRM (GoHighLevel): crea el contacto y la oportunidad en el pipeline de ventas.
Usá esta herramienta cuando:
- El cliente da su nombre, email y muestra interés concreto en una propiedad
- El cliente quiere agendar una visita
- El cliente pide hablar con un asesor
IMPORTANTE: Necesitás nombre + email del cliente para registrarlo. El teléfono viene del webhook.
El link de booking se pre-llena con nombre y email para que el cliente no los reingrese.
SIEMPRE incluí propiedad_id, propiedad_link, propiedad_direccion y resumen si el cliente eligió una propiedad. Estos datos se usan en los emails de confirmación.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {
                    "type": "string",
                    "description": "Teléfono del cliente (viene del contexto interno del chat de WhatsApp)",
                },
                "nombre": {
                    "type": "string",
                    "description": "Nombre completo del cliente",
                },
                "email": {
                    "type": "string",
                    "description": "Email del cliente (pedirlo junto con el nombre)",
                },
                "operacion": {
                    "type": "string",
                    "description": "Qué busca: Comprar, Alquilar, Vender, Poner en alquiler",
                },
                "tipo_propiedad": {
                    "type": "string",
                    "description": "Tipo: Casa, Departamento, Terreno, Local, Galpon, Oficina",
                },
                "zona": {
                    "type": "string",
                    "description": "Zona de interés: Nueva Cordoba, Centro, Alberdi, etc.",
                },
                "propiedad_id": {
                    "type": "string",
                    "description": "ID numérico de la propiedad (ej: 7791415). OBLIGATORIO si el cliente eligió una propiedad.",
                },
                "propiedad_link": {
                    "type": "string",
                    "description": "URL completa de la propiedad en inmobiliariabertero.com.ar. OBLIGATORIO si el cliente eligió una propiedad.",
                },
                "propiedad_direccion": {
                    "type": "string",
                    "description": "Dirección de la propiedad (ej: Eufrazio Loza al 1000, Barrio Pueyrredón). OBLIGATORIO si el cliente eligió una propiedad.",
                },
                "resumen": {
                    "type": "string",
                    "description": "Resumen breve: qué busca, precio, propiedad elegida. OBLIGATORIO. Ej: 'El cliente busca comprar una casa en Barrio Pueyrredón, USD 85.000. Quiere agendar una visita.'",
                },
            },
            "required": ["telefono", "nombre"],
        },
    },
    {
        "name": "obtener_link_agendar",
        "description": "Obtiene el link de booking para que el cliente agende una visita a una propiedad. Usá esta herramienta cuando el cliente quiera agendar una visita y ya esté registrado como lead.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "obtener_propiedades_para_visita",
        "description": """Muestra al cliente una lista interactiva con las propiedades que vio en la búsqueda para que elija cuál quiere visitar.
Usá esta herramienta SIEMPRE que:
- El cliente haga clic en "Agendar visita" después de una búsqueda
- El cliente diga que quiere visitar una propiedad pero no especifique cuál
La lista se arma con las propiedades de la última búsqueda del cliente.
IMPORTANTE: Pasá el teléfono del cliente (viene del contexto interno).""",
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {
                    "type": "string",
                    "description": "Teléfono del cliente (viene del contexto interno del chat)",
                },
            },
            "required": ["telefono"],
        },
    },
]
