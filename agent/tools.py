# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas para Inmobiliaria Bertero.
Funciones de FAQ, búsqueda de propiedades en tiempo real, agendamiento de citas y calificación de leads.
"""

import os
import re
import time
import yaml
import logging
import httpx
from datetime import datetime

from agent.session import guardar_propiedades, obtener_propiedades
from agent.providers.base import Respuesta, SeccionLista, FilaLista
from agent.supabase_client import obtener_todas_propiedades

logger = logging.getLogger("agentkit")

BASE_URL = "https://www.inmobiliariabertero.com.ar"

# Cache de propiedades — se carga desde Supabase al iniciar el servidor (TECH-07)
# y se recarga después de cada /admin/refresh-properties
_propiedades_cache: list[dict] = []
_propiedades_cache_time: float = 0

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


async def cargar_cache_desde_supabase() -> None:
    """
    Carga todas las propiedades desde Supabase al cache en memoria.
    Llamado por main.py lifespan al iniciar el servidor (TECH-07) y después de
    /admin/refresh-properties.
    """
    global _propiedades_cache, _propiedades_cache_time
    propiedades = await obtener_todas_propiedades()
    _propiedades_cache = propiedades
    _propiedades_cache_time = time.time()
    logger.info(f"Cache cargado desde Supabase: {len(propiedades)} propiedades")


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
    Busca propiedades en el cache en memoria (cargado desde Supabase al iniciar).
    Usa pagina=2, pagina=3, etc. para ver más resultados.
    Si el cache está vacío (Supabase no configurado), cae en scraping en vivo como fallback.
    """
    try:
        global _propiedades_cache, _propiedades_cache_time

        # Leer desde cache en memoria (cargado desde Supabase)
        if _propiedades_cache:
            todas = list(_propiedades_cache)
            logger.info(f"Propiedades desde cache Supabase: {len(todas)}")
        else:
            # Fallback: scraping en vivo si Supabase no está configurado
            logger.warning("Cache Supabase vacío — fallback a scraping en vivo")
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
            _propiedades_cache_time = time.time()
            logger.info(f"Fallback: {len(todas)} propiedades scrapeadas y cacheadas")

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

        # Filtrar por ambientes (valor exacto — estándar ZonaProp/Argenprop/ML Argentina)
        # "3 ambientes" = solo 3, no 4 ni 5. Consistente con cómo buscan los argentinos.
        if ambientes:
            try:
                amb_val = int(ambientes)
                todas = [p for p in todas if (p.get("ambientes") or 0) == amb_val]
            except ValueError:
                pass  # Si no es número, ignorar filtro

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

        # ── Auto-relajación de filtros cuando no hay resultados ──────────────
        # Reglas: NUNCA cruzar tipo ni operación. Prioridad: mantener ambientes > mantener precio.
        # 1. Quitar zona (mantener tipo + ambientes + operación + precio)
        # 2. Relajar precio ±50% manteniendo ambientes (tipo + ambientes + operación)
        # 3. Quitar precio manteniendo ambientes (tipo + ambientes + operación)
        # 4. Quitar ambientes (tipo + operación + precio)
        # 5. Quitar todo menos tipo + operación
        # 6. SIN_RESULTADOS
        filtro_relajado = ""
        if not todas:
            todas_backup = list(_propiedades_cache) if _propiedades_cache else []

            def _filtrar_base(props):
                result = list(props)
                if tipo:
                    tipo_lower = tipo.lower().strip()
                    tipo_map = {"depto": "departamento", "dpto": "departamento", "lote": "terreno", "galpón": "galpon"}
                    tipo_buscar = tipo_map.get(tipo_lower, tipo_lower)
                    result = [p for p in result if tipo_buscar in p["tipo"].lower()]
                if operacion:
                    op_lower = operacion.lower().strip()
                    op_map = {"compra": "venta", "comprar": "venta", "alquilar": "alquiler", "renta": "alquiler"}
                    op_buscar = op_map.get(op_lower, op_lower)
                    result = [p for p in result if op_buscar in p["operacion"].lower()]
                return result

            def _filtrar_precio(props, p_min, p_max):
                return [p for p in props if p.get("precio_num", 0) > 0
                        and (not p_min or p["precio_num"] >= p_min)
                        and (not p_max or p["precio_num"] <= p_max)]

            def _filtrar_ambientes(props, amb):
                if not amb:
                    return props
                try:
                    return [p for p in props if (p.get("ambientes") or 0) == int(amb)]
                except ValueError:
                    return props

            tipo_texto = tipo or "propiedades"
            zona_texto = zona or "esa zona"
            amb_texto = f" de {ambientes} ambientes" if ambientes else ""

            # Intento 1: quitar zona, mantener tipo + ambientes + operación + precio
            if zona and zona.lower() not in ("todas", "todas las zonas", "cualquiera"):
                relajadas = _filtrar_base(todas_backup)
                relajadas = _filtrar_ambientes(relajadas, ambientes)
                if precio_min_num or precio_max_num:
                    relajadas = _filtrar_precio(relajadas, precio_min_num, precio_max_num)
                if relajadas:
                    todas = relajadas
                    filtro_relajado = f"No encontré {tipo_texto}{amb_texto} en {zona}, pero hay opciones en otras zonas:\n\n"

            # Intento 2: relajar precio ±50%, MANTENER ambientes
            if not todas and ambientes and (precio_min_num or precio_max_num):
                relajadas = _filtrar_base(todas_backup)
                relajadas = _filtrar_ambientes(relajadas, ambientes)
                expanded_min = int(precio_min_num * 0.5) if precio_min_num else 0
                expanded_max = int(precio_max_num * 1.5) if precio_max_num else 0
                relajadas = _filtrar_precio(relajadas, expanded_min, expanded_max)
                if relajadas:
                    todas = relajadas
                    filtro_relajado = f"No encontré {tipo_texto}{amb_texto} en ese rango exacto, pero hay opciones en precios cercanos:\n\n"

            # Intento 3: quitar precio, MANTENER ambientes
            if not todas and ambientes and (precio_min_num or precio_max_num):
                relajadas = _filtrar_base(todas_backup)
                relajadas = _filtrar_ambientes(relajadas, ambientes)
                if relajadas:
                    todas = relajadas
                    filtro_relajado = f"No encontré {tipo_texto}{amb_texto} en tu presupuesto, pero hay {len(relajadas)} en otros rangos de precio:\n\n"

            # Intento 4: quitar ambientes, mantener tipo + operación + precio
            if not todas and ambientes:
                relajadas = _filtrar_base(todas_backup)
                if precio_min_num or precio_max_num:
                    relajadas = _filtrar_precio(relajadas, precio_min_num, precio_max_num)
                if relajadas:
                    todas = relajadas
                    filtro_relajado = f"No encontré {tipo_texto}{amb_texto} en ese rango, pero hay {tipo_texto} con otros ambientes:\n\n"

            # Intento 5: quitar todo menos tipo + operación
            if not todas:
                relajadas = _filtrar_base(todas_backup)
                if relajadas:
                    todas = relajadas
                    filtro_relajado = f"No encontré con esos filtros exactos, pero tenemos {len(relajadas)} {tipo_texto} en {operacion or 'nuestro catálogo'}:\n\n"

            # Si no hay NADA del mismo tipo+operación → SIN_RESULTADOS
            if not todas:
                op_texto = operacion or "esa operación"
                return (
                    f"SIN_RESULTADOS_OPERACION: No tenemos {tipo_texto} en {op_texto} disponibles en este momento"
                    f"{f' en {zona_texto}' if zona else ''}.\n"
                    f"[INSTRUCCIÓN INTERNA: Ofrecer al cliente DOS opciones con enviar_botones: "
                    f"1) 'Agendar llamada'(id:btn_agendar_llamada) para hablar con un asesor que pueda ayudarlo, "
                    f"2) 'Recibir novedades'(id:btn_recibir_novedades) para que le avisemos cuando tengamos "
                    f"{tipo_texto} en {op_texto}{f' en {zona_texto}' if zona else ''}. "
                    f"NUNCA mostrar propiedades de otra operación ni de otro tipo.]"
                )

        total_encontradas = len(todas)

        # Paginación
        inicio = (pagina - 1) * limite
        fin = inicio + limite
        pagina_actual = todas[inicio:fin]

        if not pagina_actual and pagina > 1:
            return f"No hay más propiedades para mostrar. Ya te mostré las {total_encontradas} disponibles."

        # Formatear resultado — incluir aviso si se relajaron filtros
        resultado = filtro_relajado if filtro_relajado else ""
        resultado += f"Encontré {total_encontradas} propiedad(es) en total"
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
        else:
            resultado += f"[TODAS_MOSTRADAS: Son todas las propiedades disponibles con estos filtros. NO hay más. NO ofrecer 'ver más'. NO inventar propiedades adicionales.]\n"

        # Guardar propiedades mostradas en cache de sesión para lista de visitas
        if telefono:
            # Acumular: si es página 2+, sumar a las anteriores
            props_previas = obtener_propiedades(telefono) if pagina > 1 else []
            props_nuevas = props_previas + pagina_actual
            guardar_propiedades(telefono, props_nuevas)
        else:
            # Sin teléfono, guardar con key genérica (fallback)
            guardar_propiedades("_last", pagina_actual)

        # Programar follow-up (FU-01): cliente vio propiedades, si no agenda en 24h se le escribe
        if telefono and pagina_actual:
            try:
                from agent.followup import programar_followup
                props_para_followup = [{"direccion": p.get("direccion", ""), "link": p.get("link", "")} for p in pagina_actual[:5]]
                await programar_followup(telefono, props_para_followup)
            except Exception as e:
                logger.error(f"Error programando follow-up para {telefono}: {e}")

        return resultado

    except httpx.TimeoutException:
        logger.error("Timeout buscando propiedades")
        return "La búsqueda tardó demasiado. Podés ver las propiedades en: www.inmobiliariabertero.com.ar/Propiedades"
    except Exception as e:
        logger.error(f"Error en búsqueda de propiedades: {e}")
        return "Hubo un error buscando propiedades. Revisá nuestra web: www.inmobiliariabertero.com.ar/Propiedades"


async def obtener_detalle_propiedad(propiedad_id: str) -> str:
    """
    Obtiene el detalle completo de una propiedad desde el cache en memoria (cargado desde Supabase).
    Si la propiedad no está en cache, retorna un mensaje con el link directo a Bertero.

    Args:
        propiedad_id: ID de la propiedad (ej: "7778974")

    Returns:
        Texto formateado con los detalles de la propiedad
    """
    try:
        # Buscar en el cache en memoria (fuente: Supabase)
        prop = None
        for p in _propiedades_cache:
            # El cache Supabase usa "propiedad_id" como clave; el cache legacy usa "id"
            pid = p.get("propiedad_id") or p.get("id", "")
            if str(pid) == str(propiedad_id):
                prop = p
                break

        if not prop:
            link = f"/p/{propiedad_id}"
            return (
                f"No encontré la propiedad {propiedad_id} en el catálogo actual. "
                f"Podés verla en: {BASE_URL}{link}"
            )

        # Formatear datos del cache en el mismo formato que _parsear_detalle producía
        resultado = ""

        # Título: tipo + operación + zona
        tipo = prop.get("tipo", "Propiedad")
        operacion = prop.get("operacion", "")
        zona = prop.get("zona", "")
        titulo_parts = [x for x in [tipo, operacion, zona] if x]
        resultado += " en ".join(titulo_parts) + "\n\n"

        # Precio
        precio = prop.get("precio", "")
        if precio:
            resultado += f"Precio: {precio}\n"

        # Dirección
        direccion = prop.get("direccion", "")
        if direccion:
            resultado += f"Dirección: {direccion}\n"

        # Características
        specs = []
        ambientes_val = prop.get("ambientes")
        if ambientes_val:
            specs.append(f"Ambientes: {ambientes_val}")
        dormitorios = prop.get("dormitorios")
        if dormitorios:
            specs.append(f"Dormitorios: {dormitorios}")
        banos = prop.get("banos")
        if banos:
            specs.append(f"Baños: {banos}")
        sup_cubierta = prop.get("sup_cubierta")
        if sup_cubierta:
            specs.append(f"Sup. cubierta: {sup_cubierta} m²")
        sup_total = prop.get("sup_total")
        if sup_total:
            specs.append(f"Sup. total: {sup_total} m²")
        antiguedad = prop.get("antiguedad")
        if antiguedad:
            specs.append(f"Antigüedad: {antiguedad} años")
        expensas = prop.get("expensas")
        if expensas:
            specs.append(f"Expensas: ${expensas}")

        if specs:
            resultado += "\n".join(specs) + "\n"

        # Descripción
        descripcion = prop.get("descripcion", "")
        if descripcion and len(descripcion) > 10:
            resultado += f"\nDescripción: {descripcion[:500]}\n"

        # Link
        link = prop.get("link", f"/p/{propiedad_id}")
        resultado += f"\nVer fotos y más detalles: {BASE_URL}{link}\n"

        return resultado

    except Exception as e:
        logger.error(f"Error obteniendo detalle de propiedad {propiedad_id}: {e}")
        return "Hubo un error al consultar los detalles. Revisá la web: www.inmobiliariabertero.com.ar/Propiedades"


# Legacy — usado como referencia y por fallback de scraping en vivo; scraper.py maneja el scraping persistente
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


# Legacy — usado como referencia; scraper.py maneja el scraping de detalle ahora
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


async def _notificar_error_crm(
    error: str, nombre: str, email: str, telefono: str,
    operacion: str = "", tipo_propiedad: str = "", zona: str = "", resumen: str = "",
):
    """Envía email al admin cuando falla el registro en GHL para que lo haga manualmente."""
    try:
        n8n_url = os.getenv("N8N_ERROR_WEBHOOK", os.getenv("N8N_EMAIL_WEBHOOK", ""))
        admin_email = os.getenv("ADMIN_EMAIL", os.getenv("VENDEDOR_EMAIL", "hola@propulsar.ai"))
        if not n8n_url:
            logger.warning("N8N_EMAIL_WEBHOOK no configurado — no se puede notificar error CRM")
            return

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(n8n_url, json={
                "nombre": nombre,
                "email_cliente": email,
                "email_vendedor": admin_email,
                "telefono": telefono,
                "propiedad_direccion": "",
                "propiedad_link": "",
                "propiedad_resumen": f"ERROR CRM — Registrar manualmente\n\nError: {error}\nOperación: {operacion}\nTipo: {tipo_propiedad}\nZona: {zona}\nResumen: {resumen}",
                "fecha_cita": "",
                "fecha_formateada": "",
                "zoom_link": "",
                "tipo_cita": "consulta",
            })
            logger.info(f"Notificación error CRM enviada al admin: {r.status_code}")
    except Exception as e:
        logger.error(f"Error enviando notificación de error CRM: {e}")


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
        # Notificar al admin por email para registro manual
        await _notificar_error_crm(
            error=contacto.get("error", "Error desconocido"),
            nombre=nombre, email=email, telefono=telefono,
            operacion=operacion, tipo_propiedad=tipo_propiedad, zona=zona,
            resumen=resumen,
        )
        return (
            f"IMPORTANTE: El CRM tuvo un error pero ya se notificó al equipo para registrarlo manualmente.\n"
            f"Vendedor asignado: {vendedor}.\n"
            f"Confirmá al cliente que sus datos fueron recibidos y que lo van a contactar.\n"
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
    elif oportunidad.get("duplicada"):
        resultado += f"El contacto ya tiene una oportunidad abierta en el CRM (no se creó duplicada).\n"
    # Diferenciar texto según si hay propiedad específica o es consulta general
    if propiedad_id or propiedad_link:
        resultado += f"Link de booking para agendar visita (pre-llenado con nombre y email): {booking_link}\n"
    else:
        resultado += f"Link de booking para agendar llamada con un asesor (pre-llenado con nombre y email): {booking_link}\n"

    # Notificar al vendedor por WhatsApp (FU-02)
    vendedor_phone_raw = os.getenv("VENDEDOR_WHATSAPP", "")
    if vendedor_phone_raw:
        try:
            from agent.takeover import construir_mensaje_lead
            from agent.providers import obtener_proveedor
            from agent.utils import normalizar_telefono as _norm

            msg_lead = construir_mensaje_lead(
                telefono=telefono,
                nombre=nombre,
                email=email,
                operacion=operacion,
                tipo_propiedad=tipo_propiedad,
                zona=zona,
                resumen=resumen,
                propiedad_direccion=propiedad_direccion,
                propiedad_link=propiedad_link,
            )
            prv = obtener_proveedor()
            vendedor_wa = _norm(vendedor_phone_raw) + "@s.whatsapp.net"
            await prv.enviar_mensaje(vendedor_wa, msg_lead)
            logger.info(f"Notificacion de lead enviada al vendedor para {telefono}")
        except Exception as e:
            logger.error(f"Error enviando notificacion de lead al vendedor: {e}")
    else:
        logger.warning("VENDEDOR_WHATSAPP no configurado — notificacion de lead al vendedor omitida")

    # Cancelar follow-up pendiente (FU-01): el cliente agendo, no necesita follow-up automatico
    try:
        from agent.followup import cancelar_followup
        await cancelar_followup(telefono)
    except Exception as e:
        logger.error(f"Error cancelando follow-up para {telefono}: {e}")

    return resultado


async def solicitar_asesor(
    telefono: str,
    nombre: str = "",
    email: str = "",
    operacion: str = "",
    resumen: str = "",
    propiedad_direccion: str = "",
    propiedad_link: str = "",
) -> str:
    """
    Notifica a un asesor por email y WhatsApp cuando el cliente quiere hablar.
    También registra el lead en GHL para tracking. NO agenda visita ni devuelve booking link.
    """
    from agent.email_service import enviar_notificacion_asesor
    from agent.providers import obtener_proveedor
    from agent.utils import normalizar_telefono

    nombre = nombre or "Cliente WhatsApp"
    telefono_norm = normalizar_telefono(telefono) if telefono else ""

    # 1. Registrar en GHL (tracking CRM)
    try:
        await registrar_lead_ghl(
            telefono=telefono,
            nombre=nombre,
            email=email,
            operacion=operacion or "consulta",
            resumen=resumen or "Cliente solicitó hablar con un asesor",
            propiedad_direccion=propiedad_direccion,
            propiedad_link=propiedad_link,
        )
        logger.info(f"Lead registrado en GHL para solicitud de asesor: {telefono_norm}")
    except Exception as e:
        logger.error(f"Error registrando lead GHL en solicitar_asesor: {e}")

    # 2. Enviar email al asesor/admin
    email_enviado = False
    try:
        email_enviado = enviar_notificacion_asesor(
            nombre_cliente=nombre,
            telefono_cliente=telefono_norm,
            email_cliente=email,
            operacion=operacion,
            resumen=resumen,
            propiedad_direccion=propiedad_direccion,
            propiedad_link=propiedad_link,
        )
    except Exception as e:
        logger.error(f"Error enviando email de solicitud asesor: {e}")

    # 3. Enviar WhatsApp al admin (bot se envía a sí mismo como notificación)
    whatsapp_enviado = False
    bot_phone = os.getenv("BOT_PHONE", "")
    if bot_phone:
        try:
            prv = obtener_proveedor()
            bot_wa = normalizar_telefono(bot_phone) + "@s.whatsapp.net"
            msg_wa = (
                f"📞 SOLICITUD DE ASESOR\n\n"
                f"👤 {nombre}\n"
                f"📱 {telefono_norm}\n"
            )
            if email:
                msg_wa += f"📧 {email}\n"
            if operacion:
                msg_wa += f"🏷️ {operacion}\n"
            if propiedad_direccion:
                msg_wa += f"🏠 {propiedad_direccion}\n"
            if propiedad_link:
                msg_wa += f"🔗 https://www.inmobiliariabertero.com.ar{propiedad_link}\n"
            if resumen:
                msg_wa += f"\n📝 {resumen}\n"
            msg_wa += f"\n⚡ Contactar al cliente a la brevedad."

            await prv.enviar_mensaje(bot_wa, msg_wa)
            whatsapp_enviado = True
            logger.info(f"Notificación WhatsApp de asesor enviada para {telefono_norm}")
        except Exception as e:
            logger.error(f"Error enviando WhatsApp de solicitud asesor: {e}")
    else:
        logger.warning("BOT_PHONE no configurado — notificación WhatsApp de asesor omitida")

    # 4. Resultado para Claude
    resultado = "Solicitud de asesor procesada.\n"
    resultado += f"Email al asesor: {'enviado' if email_enviado else 'no enviado (SMTP no configurado)'}\n"
    resultado += f"WhatsApp al admin: {'enviado' if whatsapp_enviado else 'no enviado (BOT_PHONE no configurado)'}\n"
    resultado += f"CRM: Lead registrado.\n"
    resultado += "[INSTRUCCIÓN: Confirmar al cliente que un asesor fue notificado y lo va a contactar pronto. NO compartir booking link — el asesor se comunicará directamente.]"

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


async def solicitar_humano(telefono: str, resumen: str) -> str:
    """
    Pausa el bot y notifica al vendedor asignado por WhatsApp.
    Llamar cuando el cliente pide hablar con una persona.
    """
    from agent.takeover import obtener_estado, set_estado, construir_mensaje_vendedor
    from agent.utils import normalizar_telefono
    from agent.providers import obtener_proveedor

    # Idempotency guard: si ya esta en humano, no re-notificar (Pitfall 6)
    estado_actual = await obtener_estado(telefono)
    if estado_actual == "humano":
        return "Ya en estado humano. Vendedor ya fue notificado previamente."

    # 1. Cambiar estado a "humano"
    await set_estado(telefono, "humano")

    # 2. Enviar WhatsApp al vendedor
    vendedor_phone_raw = os.getenv("VENDEDOR_WHATSAPP", "")
    if vendedor_phone_raw:
        prv = obtener_proveedor()
        msg = construir_mensaje_vendedor(telefono, resumen)
        vendedor_wa = normalizar_telefono(vendedor_phone_raw) + "@s.whatsapp.net"
        try:
            await prv.enviar_mensaje(vendedor_wa, msg)
            logger.info(f"Takeover notificacion enviada a {vendedor_phone_raw}")
        except Exception as e:
            logger.error(f"Error enviando notificacion takeover a vendedor: {e}")
    else:
        logger.warning("VENDEDOR_WHATSAPP no configurado — notificacion WhatsApp omitida")

    # Cancelar follow-up pendiente (FU-01): handoff a humano, no necesita follow-up automatico
    try:
        from agent.followup import cancelar_followup
        await cancelar_followup(telefono)
    except Exception as e:
        logger.error(f"Error cancelando follow-up para {telefono}: {e}")

    return (
        "Estado cambiado a 'humano'. Vendedor notificado por WhatsApp. "
        "Confirmar al cliente que lo va a atender un asesor en breve."
    )


async def reiniciar_conversacion(telefono: str) -> str:
    """
    Borra el historial de conversación completo y limpia el cache de sesión.
    Llamar SOLO cuando el cliente pide explícitamente empezar de nuevo.
    """
    from agent.memory import limpiar_historial
    from agent.session import _cache

    # Limpiar historial en base de datos
    await limpiar_historial(telefono)

    # Limpiar cache de sesión (propiedades guardadas para agendar visita)
    if telefono in _cache:
        del _cache[telefono]

    logger.info(f"Conversación reiniciada para {telefono}")
    return "Historial limpiado exitosamente. El cliente puede empezar desde cero. Enviar la lista de calificación inicial inmediatamente."


# Definición de herramientas para Claude tool_use
TOOLS_DEFINITION = [
    {
        "name": "buscar_propiedades",
        "description": "Busca propiedades en tiempo real. SIEMPRE usar cuando pregunten por propiedades. Para 'ver más', mismos filtros + pagina=2,3,etc.",
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
                    "description": "Cantidad exacta de ambientes (1-6). Filtro exacto: '3' muestra solo 3 ambientes.",
                },
                "pagina": {
                    "type": "integer",
                    "description": "Página de resultados (default 1). Usá 2, 3, etc. para ver más opciones con los mismos filtros.",
                },
                "telefono": {
                    "type": "string",
                    "description": "Teléfono del cliente (del contexto). SIEMPRE pasarlo.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "obtener_detalle_propiedad",
        "description": "Obtiene detalle completo de una propiedad por ID.",
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
        "description": "Registra lead en CRM: crea contacto + oportunidad. Necesita nombre+email. Incluir propiedad_id/link/direccion/resumen si hay propiedad elegida.",
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {"type": "string", "description": "Teléfono del cliente (del contexto)"},
                "nombre": {"type": "string", "description": "Nombre completo del cliente"},
                "email": {"type": "string", "description": "Email del cliente"},
                "operacion": {"type": "string", "description": "Comprar, Alquilar, Vender, Poner en alquiler"},
                "tipo_propiedad": {"type": "string", "description": "Casa, Departamento, Terreno, Local, Galpon, Oficina"},
                "zona": {"type": "string", "description": "Zona de interés"},
                "propiedad_id": {"type": "string", "description": "ID de la propiedad elegida"},
                "propiedad_link": {"type": "string", "description": "URL de la propiedad"},
                "propiedad_direccion": {"type": "string", "description": "Dirección de la propiedad"},
                "resumen": {"type": "string", "description": "Resumen breve: qué busca, precio, propiedad elegida"},
            },
            "required": ["telefono", "nombre"],
        },
    },
    {
        "name": "obtener_link_agendar",
        "description": "Obtiene link de booking para agendar visita.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "obtener_propiedades_para_visita",
        "description": "Lista interactiva con propiedades de la última búsqueda para elegir cuál visitar. Usar cuando quiere agendar visita.",
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {"type": "string", "description": "Teléfono del cliente (del contexto)"},
            },
            "required": ["telefono"],
        },
    },
    {
        "name": "reiniciar_conversacion",
        "description": (
            "Borra el historial de conversación completo para reiniciar el flujo de calificación "
            "desde cero. Llamar SOLO cuando el cliente pida explícitamente empezar de nuevo "
            "(ej: 'empezar de nuevo', 'empezar desde cero', 'olvidate de todo', 'me equivoqué quiero cambiar todo'). "
            "NO llamar para 'quiero buscar otra cosa' o 'ver algo diferente' — esos solo necesitan "
            "volver al paso correspondiente del flujo sin borrar historial. "
            "El teléfono del cliente está en el contexto interno del mensaje."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {
                    "type": "string",
                    "description": "Teléfono del cliente (del contexto interno)"
                }
            },
            "required": ["telefono"]
        }
    },
    {
        "name": "solicitar_humano",
        "description": (
            "Pausa el bot y notifica al vendedor asignado por WhatsApp. "
            "Llamar SOLO cuando el cliente diga explicitamente que quiere hablar con una persona: "
            "'quiero hablar con alguien', 'me pasas con una persona', 'hablar con un asesor', "
            "'necesito ayuda de alguien', 'con alguien real', 'con el equipo', 'hablar con un humano'. "
            "NO llamar cuando el cliente solo tiene dudas o preguntas que vos podes responder. "
            "El resumen debe incluir: nombre si se sabe, que busca (tipo, zona, presupuesto), "
            "propiedades que vio, y cualquier detalle relevante de la conversacion."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {
                    "type": "string",
                    "description": "Telefono del cliente del contexto interno (formato canonico sin @s.whatsapp.net)"
                },
                "resumen": {
                    "type": "string",
                    "description": "Resumen completo: nombre, que busca, zona, presupuesto, propiedades vistas con links"
                }
            },
            "required": ["telefono", "resumen"]
        }
    },
    {
        "name": "solicitar_asesor",
        "description": (
            "Notifica a un asesor por email y WhatsApp para que contacte al cliente. "
            "Usar cuando el cliente quiere 'hablar con un asesor', 'que me llamen', "
            "'hablar con alguien del equipo'. Registra en CRM + envía email + WhatsApp. "
            "NO devuelve booking link — el asesor contactará al cliente directamente. "
            "Pedir nombre antes de llamar. Email es opcional."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {
                    "type": "string",
                    "description": "Teléfono del cliente (del contexto interno)"
                },
                "nombre": {
                    "type": "string",
                    "description": "Nombre del cliente"
                },
                "email": {
                    "type": "string",
                    "description": "Email del cliente (opcional)"
                },
                "operacion": {
                    "type": "string",
                    "description": "Tipo de operación: venta, alquiler, tasacion, etc."
                },
                "resumen": {
                    "type": "string",
                    "description": "Resumen de lo que busca: tipo, zona, presupuesto, propiedades vistas"
                },
                "propiedad_direccion": {
                    "type": "string",
                    "description": "Dirección de la propiedad de interés (si hay)"
                },
                "propiedad_link": {
                    "type": "string",
                    "description": "Link relativo de la propiedad (ej: /p/7007502-...)"
                },
            },
            "required": ["telefono", "nombre"]
        }
    },
]
