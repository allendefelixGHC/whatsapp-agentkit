# tests/test_local.py — Simulador de chat en terminal
# Generado por AgentKit

"""
Prueba tu agente sin necesitar WhatsApp.
Simula una conversación en la terminal con soporte para mensajes interactivos.
"""

import asyncio
import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, limpiar_historial

TELEFONO_TEST = "test-local-001"


def mostrar_respuesta(respuesta):
    """Muestra la respuesta formateada según su tipo."""
    print(f"\nSoporte Bertero: {respuesta.texto}")

    if respuesta.tipo == "botones" and respuesta.botones:
        print("\n  [Botones]")
        for b in respuesta.botones:
            print(f"  [ {b.titulo} ]")

    elif respuesta.tipo == "lista" and respuesta.secciones:
        print(f"\n  [{respuesta.texto_boton_lista or 'Ver opciones'}]")
        for sec in respuesta.secciones:
            print(f"  --- {sec.titulo} ---")
            for fila in sec.filas:
                desc = f" — {fila.descripcion}" if fila.descripcion else ""
                print(f"    > {fila.titulo}{desc}")

    print()


async def main():
    """Loop principal del chat de prueba."""
    await inicializar_db()

    print()
    print("=" * 55)
    print("   AgentKit — Test Local")
    print("   Agente: Soporte Bertero")
    print("   Negocio: Inmobiliaria Bertero")
    print("=" * 55)
    print()
    print("  Escribe mensajes como si fueras un cliente.")
    print("  Comandos especiales:")
    print("    'limpiar'  — borra el historial")
    print("    'salir'    — termina el test")
    print()
    print("-" * 55)
    print()

    while True:
        try:
            mensaje = input("Tu: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nTest finalizado.")
            break

        if not mensaje:
            continue

        if mensaje.lower() == "salir":
            print("\nTest finalizado.")
            break

        if mensaje.lower() == "limpiar":
            await limpiar_historial(TELEFONO_TEST)
            print("[Historial borrado]\n")
            continue

        historial = await obtener_historial(TELEFONO_TEST)
        respuesta = await generar_respuesta(mensaje, historial)

        mostrar_respuesta(respuesta)

        await guardar_mensaje(TELEFONO_TEST, "user", mensaje)
        await guardar_mensaje(TELEFONO_TEST, "assistant", respuesta.texto)


if __name__ == "__main__":
    asyncio.run(main())
