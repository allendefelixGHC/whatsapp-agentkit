# agent/scraper.py — Deep scraper para Inmobiliaria Bertero
# Generado por AgentKit — Phase 02-01

"""
Scraper de dos etapas:
  1. Páginas de listado (/Propiedades?p=N) — extrae stub de cada propiedad
  2. Página de detalle (/p/ID-slug) — extrae datos completos incluyendo precio authoritative

Los datos se persisten en Supabase via upsert_propiedades y las propiedades
que ya no existen en el sitio se eliminan via marcar_removidas.

Usar asyncio.sleep(0.5) entre páginas de detalle para evitar rate limiting.
"""

import re
import asyncio
import logging
import httpx
from datetime import datetime, timezone

from agent.supabase_client import upsert_propiedades, marcar_removidas

BASE_URL = "https://www.inmobiliariabertero.com.ar"
logger = logging.getLogger("agentkit")


async def scrape_and_persist() -> dict:
    """
    Entry point principal del scraper.

    Flujo:
      1. Scrape todas las páginas de listado (hasta 4) para obtener stubs
      2. Para cada stub, scrape la página de detalle para datos completos
      3. Upsert batch a Supabase
      4. Eliminar propiedades que ya no están en el sitio

    Returns:
        dict con "total", "nuevas", "removidas"
    """
    logger.info("Iniciando scrape completo de Bertero")

    # Etapa 1: obtener stubs del listado
    stubs = await _scrape_listado_todas()
    logger.info(f"Stubs obtenidos del listado: {len(stubs)}")

    if not stubs:
        logger.warning("No se obtuvieron propiedades del listado — abortando")
        return {"total": 0, "nuevas": 0, "removidas": 0}

    # Etapa 2: enriquecer cada stub con datos del detalle
    batch = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for i, stub in enumerate(stubs):
            link = stub.get("link", "")
            if not link:
                batch.append(stub)
                continue

            # Sleep entre requests de detalle para evitar rate limiting en Bertero
            if i > 0:
                await asyncio.sleep(0.5)

            detalle = await _scrape_detalle(link, client)

            # Mergear: precio del detalle OVERRIDE precio del listado (DATA-05)
            merged = {**stub}
            if detalle.get("precio"):
                merged["precio"] = detalle["precio"]
            if detalle.get("precio_num"):
                merged["precio_num"] = detalle["precio_num"]

            # Campos exclusivos del detalle
            for campo in ("ambientes", "dormitorios", "banos", "sup_cubierta",
                          "sup_total", "antiguedad", "expensas", "descripcion"):
                if campo in detalle:
                    merged[campo] = detalle[campo]

            # Timestamp del scraping
            merged["scraped_at"] = datetime.now(timezone.utc).isoformat()

            batch.append(merged)
            logger.debug(f"Detalle scrapeado: {stub['propiedad_id']} ({i+1}/{len(stubs)})")

    # Etapa 3: persistir en Supabase
    total = await upsert_propiedades(batch)

    # Etapa 4: limpiar propiedades que ya no están en el sitio
    ids_activos = [p["propiedad_id"] for p in batch]
    removidas = await marcar_removidas(ids_activos)

    logger.info(f"Scrape completado: {total} totales, {removidas} removidas")
    return {"total": total, "nuevas": total, "removidas": removidas}


async def _scrape_listado_todas() -> list[dict]:
    """
    Fetches hasta 4 páginas del listado de Bertero y retorna los stubs combinados.

    Returns:
        Lista de dicts con claves: propiedad_id, link, tipo, operacion, zona,
        direccion, precio, precio_num, superficie
    """
    todas = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for page in range(1, 5):
            try:
                r = await client.get(f"{BASE_URL}/Propiedades", params={"p": str(page)})
                if r.status_code != 200:
                    logger.warning(f"Listado página {page}: HTTP {r.status_code}")
                    break
                nuevas = _parsear_listado_raw(r.text)
                if not nuevas:
                    logger.info(f"Listado página {page}: sin propiedades — fin del listado")
                    break
                todas.extend(nuevas)
                logger.info(f"Listado página {page}: {len(nuevas)} propiedades")
            except httpx.TimeoutException:
                logger.error(f"Timeout en listado página {page}")
                break
            except Exception as e:
                logger.error(f"Error en listado página {page}: {e}")
                break

    return todas


def _parsear_listado_raw(html: str) -> list[dict]:
    """
    Parsea el HTML del listado de Bertero y retorna stubs de propiedades.

    Misma lógica que _parsear_listado en tools.py pero retorna dicts con
    claves compatibles con el schema de Supabase (propiedad_id en lugar de id).

    Args:
        html: HTML completo de la página de listado

    Returns:
        Lista de dicts con: propiedad_id, link, tipo, operacion, zona, direccion,
        precio, precio_num, superficie
    """
    propiedades = []
    links = list(re.finditer(r'href="(/p/(\d+)-([^"]+))"', html))

    seen_ids: set[str] = set()
    for i, match in enumerate(links):
        pid = match.group(2)
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        link = match.group(1)
        slug = match.group(3)

        # Extraer tipo, operación, zona del slug: Tipo-en-Operacion-en-Zona-Direccion
        partes = slug.split("-en-")
        tipo = partes[0].replace("-", " ").strip() if len(partes) > 0 else ""
        operacion = partes[1].replace("-", " ").strip() if len(partes) > 1 else ""
        resto = partes[2] if len(partes) > 2 else ""

        zona = ""
        direccion = ""
        if resto:
            dir_match = re.search(r'(.+?)[-,]?\s*(?:al\s*\d|esquina|\d{2,})', resto, re.IGNORECASE)
            if dir_match:
                zona = dir_match.group(1).rstrip("-").replace("-", " ").strip()
                direccion = resto.replace("-", " ").replace("  ", " ").strip()
            else:
                zona = resto.replace("-", " ").strip()

        # Precio del listado (puede ser sobreescrito por precio del detalle)
        precio = ""
        precio_num = 0
        start = links[i - 1].end() if i > 0 else 0
        bloque = html[start:match.start()]
        precios = re.findall(r'(USD|U\$S)\s*([\d.,]+)', bloque)
        if precios:
            moneda, valor = precios[-1]
            precio = f"USD {valor}"
            try:
                precio_num = int(valor.replace(".", "").replace(",", ""))
            except ValueError:
                pass

        # Superficie del listado
        superficie = ""
        sup_matches = re.findall(r'(\d+(?:[.,]\d+)?)\s*m[²2]', bloque)
        if sup_matches:
            superficie = f"{sup_matches[-1]} m²"

        propiedades.append({
            "propiedad_id": pid,
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


async def _scrape_detalle(link: str, client: httpx.AsyncClient | None = None) -> dict:
    """
    Fetches la página de detalle de una propiedad y extrae campos estructurados.

    Args:
        link: Path relativo, ej: "/p/7778974-departamento-en-venta-..."
        client: httpx.AsyncClient reutilizable (opcional; crea uno nuevo si no se pasa)

    Returns:
        Dict con: precio, precio_num, ambientes, dormitorios, banos, sup_cubierta,
        sup_total, antiguedad, expensas, descripcion
    """
    try:
        if client is not None:
            r = await client.get(f"{BASE_URL}{link}")
        else:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
                r = await c.get(f"{BASE_URL}{link}")

        if r.status_code != 200:
            logger.warning(f"Detalle {link}: HTTP {r.status_code}")
            return {}

        return _parsear_detalle_campos(r.text)

    except httpx.TimeoutException:
        logger.warning(f"Timeout en detalle {link}")
        return {}
    except Exception as e:
        logger.error(f"Error scrapeando detalle {link}: {e}")
        return {}


def _parsear_detalle_campos(html: str) -> dict:
    """
    Extrae campos estructurados del HTML de una página de detalle de Bertero.

    Estructura HTML de Bertero (verificada 2026-03-28):
    - #lista_informacion_basica: <li>Dormitorios : 2</li> etc.
    - #lista_superficies: <li>Cubierta: 79 m²</li> etc.
    - Precio: texto plano "USD 65.000" o "USD65.000" en el heading

    Returns:
        Dict con: precio, precio_num, ambientes, dormitorios, banos,
        sup_cubierta, sup_total, antiguedad, expensas, descripcion
    """
    result: dict = {}

    # ── Precio del detalle (AUTHORITATIVE — DATA-05) ──────────────────────────
    precio_match = re.search(r'(USD|U\$S)\s*([\d.,]+)', html)
    if precio_match:
        valor = precio_match.group(2)
        result["precio"] = f"USD {valor}"
        try:
            result["precio_num"] = int(valor.replace(".", "").replace(",", ""))
        except ValueError:
            result["precio_num"] = 0

    # ── #lista_informacion_basica ─────────────────────────────────────────────
    info_bloque = re.search(r'id="lista_informacion_basica"[^>]*>(.*?)</ul>', html, re.DOTALL)
    if info_bloque:
        lis = re.findall(r'<li>([^<]+)</li>', info_bloque.group(1))
        info: dict[str, str] = {}
        for li in lis:
            if ':' in li:
                key, _, val = li.partition(':')
                info[key.strip().lower()] = val.strip()

        if "ambientes" in info:
            result["ambientes"] = _safe_int(info["ambientes"])
        if "dormitorios" in info:
            result["dormitorios"] = _safe_int(info["dormitorios"])
        # Acepta tanto "baños" como "banos" por variaciones de encoding
        banos_key = next((k for k in info if "ba" in k and ("o" in k or "ñ" in k)), None)
        if banos_key:
            result["banos"] = _safe_int(info[banos_key])
        # Antigüedad — guardar como string completo (ej: "36 Años")
        antig_key = next((k for k in info if "antig" in k), None)
        if antig_key:
            result["antiguedad"] = info[antig_key]
        if "expensas" in info:
            result["expensas"] = info["expensas"]

    # ── #lista_superficies ────────────────────────────────────────────────────
    sup_bloque = re.search(r'id="lista_superficies"[^>]*>(.*?)</ul>', html, re.DOTALL)
    if sup_bloque:
        lis = re.findall(r'<li>([^<]+)</li>', sup_bloque.group(1))
        sups: dict[str, str] = {}
        for li in lis:
            if ':' in li:
                key, _, val = li.partition(':')
                sups[key.strip().lower()] = val.strip()

        # "cubierta" → sup_cubierta
        if "cubierta" in sups:
            result["sup_cubierta"] = sups["cubierta"]
        # "total construido" → sup_total
        total_key = next((k for k in sups if "total" in k), None)
        if total_key:
            result["sup_total"] = sups[total_key]

    # ── Descripción ───────────────────────────────────────────────────────────
    desc_match = re.search(r'class="[^"]*description[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    if desc_match:
        desc = re.sub(r'<[^>]+>', ' ', desc_match.group(1))
        desc = re.sub(r'\s+', ' ', desc).strip()
        if desc and len(desc) > 5:
            result["descripcion"] = desc[:1000]

    return result


def _safe_int(value: str, default: int = 0) -> int:
    """
    Parsea el primer número entero de un string de forma segura.

    Ejemplos:
        "2"      → 2
        "36 Años"→ 36
        "$ 109.000" → 109000
        ""       → default (0)

    Args:
        value: String con número al inicio o mezclado con texto
        default: Valor a retornar si no se encuentra ningún dígito

    Returns:
        Entero parseado o default
    """
    if not value:
        return default
    # Extraer primer bloque de dígitos (puede tener separadores de miles)
    digits_match = re.search(r'[\d.,]+', value.strip())
    if not digits_match:
        return default
    try:
        return int(digits_match.group(0).replace(".", "").replace(",", ""))
    except ValueError:
        return default
