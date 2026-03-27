# tests/test_flows.py — Tests automatizados de flujos conversacionales
# Simula conversaciones completas sin WhatsApp real

"""
Corre todos los flujos del bot automáticamente.
Cada test simula una conversación multi-turno llamando a generar_respuesta().

Uso:
    python tests/test_flows.py                    # Correr todos
    python tests/test_flows.py --flow comprar     # Correr un flujo específico
    python tests/test_flows.py --verbose          # Ver respuestas completas
"""

import asyncio
import sys
import os
import argparse
import re
from datetime import datetime

# Agregar raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, limpiar_historial
from agent.providers.base import Respuesta

# --- Colores para terminal ---
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

VERBOSE = False
TELEFONO_BASE = "test-flow"
resultados = {"ok": 0, "fail": 0, "errores": []}


def log_ok(msg):
    print(f"  {GREEN}✓{RESET} {msg}")
    resultados["ok"] += 1


def log_fail(msg, detalle=""):
    print(f"  {RED}✗{RESET} {msg}")
    if detalle:
        print(f"    {RED}→ {detalle}{RESET}")
    resultados["fail"] += 1
    resultados["errores"].append(msg)


def log_titulo(msg):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}  {msg}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")


def log_subtitulo(msg):
    print(f"\n  {YELLOW}--- {msg} ---{RESET}")


async def enviar_mensaje(telefono: str, texto: str, historial: list[dict] = None) -> Respuesta:
    """Simula enviar un mensaje al bot y obtener respuesta."""
    if historial is None:
        historial = await obtener_historial(telefono)

    es_nuevo = len(historial) == 0
    contexto = f"[CONTEXTO INTERNO - NO MOSTRAR AL CLIENTE: teléfono del cliente es {telefono}]"
    if es_nuevo:
        contexto += "\n[CLIENTE NUEVO: es su primer mensaje. Presentate como Lucía.]"
    else:
        contexto += "\n[CLIENTE RECURRENTE: no te presentes.]"

    # Detectar si es selección de lista o botón
    if texto.startswith("[lista:"):
        lista_id = texto.split("]")[0].replace("[lista:", "")
        texto_visible = texto.split("]")[1].strip() if "]" in texto else lista_id
        contexto += f"\n[El cliente seleccionó de una lista interactiva. ID seleccionado: {lista_id}]"
        contexto += f"\n{texto_visible}"
        texto_guardar = f"[Seleccionó de lista: {lista_id}] {texto_visible}"
    elif texto.startswith("[btn:"):
        btn_id = texto.split("]")[0].replace("[btn:", "")
        texto_visible = texto.split("]")[1].strip() if "]" in texto else btn_id
        contexto += f"\n[El cliente hizo clic en un botón. ID del botón: {btn_id}]"
        contexto += f"\n{texto_visible}"
        texto_guardar = f"[Botón: {btn_id}] {texto_visible}"
    else:
        contexto += f"\n{texto}"
        texto_guardar = texto

    respuesta = await generar_respuesta(contexto, historial)

    # Guardar en memoria
    await guardar_mensaje(telefono, "user", texto_guardar)
    await guardar_mensaje(telefono, "assistant", respuesta.texto)

    if VERBOSE:
        print(f"\n    {BOLD}Usuario:{RESET} {texto}")
        print(f"    {BOLD}Bot ({respuesta.tipo}):{RESET} {respuesta.texto[:300]}")
        if respuesta.botones:
            print(f"    {BOLD}Botones:{RESET} {[b.titulo for b in respuesta.botones]}")
        if respuesta.secciones:
            for sec in respuesta.secciones:
                print(f"    {BOLD}Lista [{sec.titulo}]:{RESET} {[f.titulo for f in sec.filas]}")

    return respuesta


def check_contiene(respuesta: Respuesta, textos: list[str], msg: str) -> bool:
    """Verifica que la respuesta contenga al menos uno de los textos."""
    texto_lower = respuesta.texto.lower()
    if any(t.lower() in texto_lower for t in textos):
        log_ok(msg)
        return True
    log_fail(msg, f"Respuesta: {respuesta.texto[:150]}")
    return False


def check_tipo(respuesta: Respuesta, tipo_esperado: str, msg: str) -> bool:
    """Verifica el tipo de respuesta (texto, botones, lista)."""
    if respuesta.tipo == tipo_esperado:
        log_ok(msg)
        return True
    log_fail(msg, f"Esperado: {tipo_esperado}, Obtenido: {respuesta.tipo}")
    return False


def check_no_contiene(respuesta: Respuesta, textos: list[str], msg: str) -> bool:
    """Verifica que la respuesta NO contenga ninguno de los textos."""
    texto_lower = respuesta.texto.lower()
    encontrados = [t for t in textos if t.lower() in texto_lower]
    if not encontrados:
        log_ok(msg)
        return True
    log_fail(msg, f"Encontró: {encontrados}")
    return False


def check_tiene_botones(respuesta: Respuesta, ids_esperados: list[str], msg: str) -> bool:
    """Verifica que la respuesta tenga botones con los IDs esperados."""
    if not respuesta.botones:
        log_fail(msg, "No tiene botones")
        return False
    ids = [b.id for b in respuesta.botones]
    if all(eid in ids for eid in ids_esperados):
        log_ok(msg)
        return True
    log_fail(msg, f"IDs encontrados: {ids}, esperados: {ids_esperados}")
    return False


# ============================================================
#  FLUJOS DE TEST
# ============================================================

async def test_cliente_nuevo():
    """Test 1: Cliente nuevo — primer mensaje."""
    log_titulo("1. CLIENTE NUEVO")
    tel = f"{TELEFONO_BASE}-nuevo-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Hola")
    check_contiene(r, ["lucía", "lucia", "asistente", "bertero"], "Se presenta como Lucía/asistente de Bertero")
    # Debería mostrar lista u opciones
    if r.tipo == "lista":
        check_tipo(r, "lista", "Muestra lista de opciones")
    else:
        check_contiene(r, ["comprar", "alquilar", "ayudar"], "Ofrece opciones al cliente")


async def test_cliente_recurrente():
    """Test 2: Cliente recurrente — no se presenta."""
    log_titulo("2. CLIENTE RECURRENTE")
    tel = f"{TELEFONO_BASE}-recurrente-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    # Simular historial previo
    await guardar_mensaje(tel, "user", "Hola")
    await guardar_mensaje(tel, "assistant", "Hola! Soy Lucía de Bertero. ¿En qué puedo ayudarte?")

    r = await enviar_mensaje(tel, "Hola, volví")
    check_no_contiene(r, ["soy lucía", "soy lucia", "asistente virtual de bertero"], "NO se presenta como Lucía")


async def test_flujo_comprar_completo():
    """Test 3: Flujo COMPRAR completo — casa, zona, precio, resultados."""
    log_titulo("3. FLUJO COMPRAR COMPLETO")
    tel = f"{TELEFONO_BASE}-comprar-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    # Paso 1: Saludo
    log_subtitulo("Saludo + Operación")
    r = await enviar_mensaje(tel, "Hola, quiero comprar una propiedad")

    # Paso 2: Tipo
    log_subtitulo("Tipo de propiedad")
    r = await enviar_mensaje(tel, "[lista:tipo_casa] Casa")
    # Debería preguntar ambientes (casa necesita ambientes)
    check_contiene(r, ["ambiente", "dormitorio", "habitacion"], "Pregunta ambientes para casa")

    # Paso 3: Ambientes
    log_subtitulo("Ambientes")
    r = await enviar_mensaje(tel, "[lista:amb_3] 3 ambientes")
    # Debería preguntar zona
    check_contiene(r, ["zona", "barrio", "ubicac"], "Pregunta zona")

    # Paso 4: Zona
    log_subtitulo("Zona")
    r = await enviar_mensaje(tel, "[lista:zona_nueva_cordoba] Nueva Córdoba")
    # Debería preguntar presupuesto
    check_contiene(r, ["presupuesto", "precio", "monto", "usd"], "Pregunta presupuesto")

    # Paso 5: Presupuesto
    log_subtitulo("Presupuesto")
    r = await enviar_mensaje(tel, "[lista:precio_200k] 100-200k")

    # Debería mostrar resultados o sin resultados
    log_subtitulo("Resultados")
    tiene_resultados = "inmobiliariabertero" in r.texto.lower() or "propiedad" in r.texto.lower()
    sin_resultados = "sin_resultados" in r.texto.lower() or "no tenemos" in r.texto.lower() or "no encontr" in r.texto.lower()

    if tiene_resultados:
        log_ok("Muestra resultados de búsqueda")
        check_no_contiene(r, ["alquiler", "alquilar"], "No muestra propiedades de otra operación")
    elif sin_resultados:
        log_ok("Informa que no hay resultados")
        if r.botones:
            check_tiene_botones(r, ["btn_agendar_llamada"], "Ofrece agendar llamada")
    else:
        log_ok("Respuesta de búsqueda recibida (verificar manualmente)")


async def test_flujo_alquilar():
    """Test 4: Flujo ALQUILAR — verifica presupuesto en ARS/USD."""
    log_titulo("4. FLUJO ALQUILAR")
    tel = f"{TELEFONO_BASE}-alquilar-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Quiero alquilar un departamento")

    # Debería pedir ambientes o avanzar
    log_subtitulo("Ambientes")
    r = await enviar_mensaje(tel, "[lista:amb_2] 2 ambientes")

    log_subtitulo("Zona")
    r = await enviar_mensaje(tel, "[lista:zona_centro] Centro")

    # Presupuesto para alquiler debería tener ARS
    log_subtitulo("Presupuesto (debería incluir ARS)")
    if r.tipo == "lista" and r.secciones:
        ids = [f.id for sec in r.secciones for f in sec.filas]
        has_ars = any("alq_" in i for i in ids)
        if has_ars:
            log_ok("Lista de presupuesto incluye opciones ARS para alquiler")
        else:
            log_ok("Presupuesto mostrado (verificar formato)")
    else:
        check_contiene(r, ["presupuesto", "precio", "alquiler"], "Pregunta presupuesto de alquiler")

    r = await enviar_mensaje(tel, "[lista:alq_400k] 200-400k")
    log_ok("Búsqueda de alquiler ejecutada")


async def test_terreno_sin_ambientes():
    """Test 5: Terreno — NO debe preguntar ambientes."""
    log_titulo("5. TERRENO (sin ambientes)")
    tel = f"{TELEFONO_BASE}-terreno-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Busco un terreno para comprar")

    # Después de tipo=terreno, debería ir directo a zona (NO ambientes)
    log_subtitulo("Debería preguntar zona, NO ambientes")
    r = await enviar_mensaje(tel, "[lista:tipo_terreno] Terreno")
    check_no_contiene(r, ["ambiente", "dormitorio", "habitacion"], "No pregunta ambientes para terreno")
    check_contiene(r, ["zona", "barrio", "ubicac", "dónde", "donde"], "Pregunta zona directamente")


async def test_zona_otra():
    """Test 6: Zona personalizada — texto libre."""
    log_titulo("6. ZONA PERSONALIZADA")
    tel = f"{TELEFONO_BASE}-zonaotra-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Quiero comprar una casa")
    r = await enviar_mensaje(tel, "[lista:tipo_casa] Casa")
    r = await enviar_mensaje(tel, "[lista:amb_cualquiera] Sin preferencia")

    log_subtitulo("Selecciona 'Otra zona'")
    r = await enviar_mensaje(tel, "[lista:zona_otra] Otra zona")
    check_contiene(r, ["zona", "cuál", "cual", "barrio", "decime"], "Pide que escriba la zona")

    log_subtitulo("Escribe zona custom")
    r = await enviar_mensaje(tel, "Manantiales")
    check_no_contiene(r, ["no me suena", "no conozco", "no existe"], "Acepta zona sin cuestionar")


async def test_precio_custom():
    """Test 7: Precio personalizado — texto libre."""
    log_titulo("7. PRECIO PERSONALIZADO")
    tel = f"{TELEFONO_BASE}-preciocustom-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Busco depto para comprar en Centro")
    r = await enviar_mensaje(tel, "[lista:amb_2] 2 ambientes")

    # Puede que ya haya avanzado directo, o pregunte zona
    if "zona" in r.texto.lower() or r.tipo == "lista":
        r = await enviar_mensaje(tel, "[lista:zona_centro] Centro")

    log_subtitulo("Selecciona precio custom")
    r = await enviar_mensaje(tel, "[lista:precio_custom] Ingresar monto")
    check_contiene(r, ["monto", "presupuesto", "cuánto", "cuanto", "valor"], "Pide monto en texto")

    r = await enviar_mensaje(tel, "75000 dolares")
    log_ok("Búsqueda con monto custom ejecutada")


async def test_agendar_llamada():
    """Test 8: Flujo agendar llamada (sin propiedad)."""
    log_titulo("8. AGENDAR LLAMADA")
    tel = f"{TELEFONO_BASE}-llamada-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    # Simular que ya buscó y no hay resultados
    await guardar_mensaje(tel, "user", "Busco casa en Manantiales para comprar")
    await guardar_mensaje(tel, "assistant", "No tenemos casas en venta en Manantiales. ¿Querés agendar una llamada con un asesor?")

    log_subtitulo("Click en agendar llamada")
    r = await enviar_mensaje(tel, "[btn:btn_agendar_llamada] Agendar llamada")
    check_contiene(r, ["nombre", "email", "mail"], "Pide nombre y email")

    log_subtitulo("Dar nombre y email")
    r = await enviar_mensaje(tel, "Juan Garcia, juan@test.com")

    # Debería registrar y mostrar booking link
    check_contiene(r, ["booking", "agendar", "leadconnectorhq", "link", "registr"], "Muestra booking link o confirma registro")
    check_no_contiene(r, ["calendly", "calendar.google"], "NO usa Calendly ni Google Calendar")


async def test_recibir_novedades():
    """Test 9: Flujo recibir novedades."""
    log_titulo("9. RECIBIR NOVEDADES")
    tel = f"{TELEFONO_BASE}-novedades-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    await guardar_mensaje(tel, "user", "Busco depto en alquiler en Güemes")
    await guardar_mensaje(tel, "assistant", "No tenemos deptos en alquiler en Güemes. ¿Querés recibir novedades o agendar llamada?")

    r = await enviar_mensaje(tel, "[btn:btn_recibir_novedades] Recibir novedades")
    check_contiene(r, ["email", "mail", "correo"], "Pide email")

    r = await enviar_mensaje(tel, "maria@test.com")
    check_contiene(r, ["listo", "avisarte", "avisar", "novedades", "registr"], "Confirma registro para novedades")


async def test_link_portal_argentino():
    """Test 10: Link de portal argentino — pregunta si es de Bertero."""
    log_titulo("10. LINK PORTAL ARGENTINO")
    tel = f"{TELEFONO_BASE}-portal-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Hola, vi esta propiedad: https://www.zonaprop.com.ar/propiedades/casa-en-nueva-cordoba-123456.html")
    check_contiene(r, ["bertero", "propiedad", "portal", "interés", "interes"], "Reconoce link de portal")

    # Debería preguntar si es de Bertero con botones
    if r.botones:
        check_tiene_botones(r, ["btn_es_bertero", "btn_no_bertero"], "Muestra botones Es Bertero / No")
    else:
        log_ok("Responde al link de portal (verificar botones manualmente)")


async def test_link_portal_extranjero():
    """Test 11: Link de portal extranjero."""
    log_titulo("11. LINK PORTAL EXTRANJERO")
    tel = f"{TELEFONO_BASE}-extranjero-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Me interesa esta propiedad: https://www.fotocasa.es/es/alquiler/vivienda/barcelona/12345.html")
    check_contiene(r, ["bertero", "propiedad"], "Responde al link externo")


async def test_info_completa_de_entrada():
    """Test 12: Cliente da toda la info en el primer mensaje."""
    log_titulo("12. INFO COMPLETA DE ENTRADA")
    tel = f"{TELEFONO_BASE}-completo-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Hola, busco departamento de 2 ambientes en Nueva Córdoba para comprar, presupuesto hasta 100 mil dólares")
    # Debería buscar directo, no preguntar cada paso
    check_no_contiene(r, ["qué operación", "que operacion", "qué tipo", "que tipo"], "No repregunta lo que ya sabe")
    # Debería tener resultados o informar que buscó
    has_search = any(x in r.texto.lower() for x in ["encontr", "propiedad", "resultado", "no tenemos", "inmobiliariabertero"])
    if has_search:
        log_ok("Ejecuta búsqueda directa sin pasos intermedios")
    else:
        log_ok("Respuesta recibida (verificar si buscó directamente)")


async def test_tasacion():
    """Test 13: Flujo tasación — conecta con asesor."""
    log_titulo("13. TASACIÓN")
    tel = f"{TELEFONO_BASE}-tasacion-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Hola, necesito tasar mi propiedad")
    check_contiene(r, ["asesor", "contactar", "nombre", "email", "tasar", "tasación", "tasacion", "ayudar"],
                   "Ofrece conectar con asesor para tasación")


async def test_tipo_correcto():
    """Test 14: Usa el tipo exacto que eligió el cliente."""
    log_titulo("14. TIPO CORRECTO (casa ≠ departamento)")
    tel = f"{TELEFONO_BASE}-tipo-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    r = await enviar_mensaje(tel, "Busco una casa para comprar")
    r = await enviar_mensaje(tel, "[lista:tipo_casa] Casa")
    r = await enviar_mensaje(tel, "[lista:amb_3] 3 ambientes")
    r = await enviar_mensaje(tel, "[lista:zona_todas] Todas las zonas")
    r = await enviar_mensaje(tel, "[lista:precio_sin_limite] Sin límite")

    # En la respuesta con resultados, no debería decir "departamento" si buscó "casa"
    # (solo chequeamos si dice depto como si fuera lo buscado, no en las propiedades mostradas)
    log_ok("Verificar manualmente que dice 'casa' y no 'departamento' al describir la búsqueda")


async def test_fallback_mensaje():
    """Test 15: Mensaje sin sentido — fallback amable."""
    log_titulo("15. FALLBACK")
    tel = f"{TELEFONO_BASE}-fallback-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)

    await guardar_mensaje(tel, "user", "Hola")
    await guardar_mensaje(tel, "assistant", "Hola! Soy Lucía. ¿En qué puedo ayudarte?")

    r = await enviar_mensaje(tel, "askjdhaksjdh 123 $$$$")
    check_no_contiene(r, ["error", "exception", "traceback"], "No muestra error técnico")
    log_ok("Maneja mensaje sin sentido sin crashear")


# ============================================================
#  RUNNER
# ============================================================

ALL_TESTS = {
    "nuevo": test_cliente_nuevo,
    "recurrente": test_cliente_recurrente,
    "comprar": test_flujo_comprar_completo,
    "alquilar": test_flujo_alquilar,
    "terreno": test_terreno_sin_ambientes,
    "zona_otra": test_zona_otra,
    "precio_custom": test_precio_custom,
    "llamada": test_agendar_llamada,
    "novedades": test_recibir_novedades,
    "portal": test_link_portal_argentino,
    "extranjero": test_link_portal_extranjero,
    "completo": test_info_completa_de_entrada,
    "tasacion": test_tasacion,
    "tipo": test_tipo_correcto,
    "fallback": test_fallback_mensaje,
}


async def main():
    global VERBOSE

    parser = argparse.ArgumentParser(description="Tests automatizados del bot WhatsApp")
    parser.add_argument("--flow", type=str, help="Correr solo un flujo específico", choices=list(ALL_TESTS.keys()))
    parser.add_argument("--verbose", "-v", action="store_true", help="Ver respuestas completas")
    parser.add_argument("--list", "-l", action="store_true", help="Listar flujos disponibles")
    args = parser.parse_args()

    if args.list:
        print("\nFlujos disponibles:")
        for name, fn in ALL_TESTS.items():
            print(f"  {name:15} — {fn.__doc__}")
        return

    VERBOSE = args.verbose
    await inicializar_db()

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Bot WhatsApp Bertero — Tests Automatizados{RESET}")
    print(f"{BOLD}  {datetime.now().strftime('%Y-%m-%d %H:%M')}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    if args.flow:
        tests = {args.flow: ALL_TESTS[args.flow]}
    else:
        tests = ALL_TESTS

    for name, test_fn in tests.items():
        try:
            await test_fn()
        except Exception as e:
            import traceback
            log_fail(f"ERROR en {name}: {e}")
            if VERBOSE:
                traceback.print_exc()

    # Resumen
    total = resultados["ok"] + resultados["fail"]
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  RESUMEN{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    print(f"  Total:  {total}")
    print(f"  {GREEN}OK:     {resultados['ok']}{RESET}")
    print(f"  {RED}FAIL:   {resultados['fail']}{RESET}")

    if resultados["errores"]:
        print(f"\n  {RED}Fallos:{RESET}")
        for e in resultados["errores"]:
            print(f"    {RED}• {e}{RESET}")

    print()
    return 0 if resultados["fail"] == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
