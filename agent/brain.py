# agent/brain.py — Cerebro del agente: conexión con Claude API + Tool Use
# Generado por AgentKit

"""
Lógica de IA del agente. Lee el system prompt de prompts.yaml
y genera respuestas usando la API de Anthropic Claude con tool_use
para buscar propiedades y enviar mensajes interactivos.
"""

import os
import json
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.tools import (
    buscar_propiedades,
    obtener_detalle_propiedad,
    registrar_lead_ghl,
    obtener_link_agendar,
    TOOLS_DEFINITION,
)
from agent.providers.base import Respuesta, Boton, SeccionLista, FilaLista

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente de Anthropic
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Herramientas de mensajes interactivos (se agregan a TOOLS_DEFINITION)
INTERACTIVE_TOOLS = [
    {
        "name": "enviar_botones",
        "description": """Envía un mensaje de WhatsApp con botones de respuesta rápida (máximo 3 botones).
Usá esta herramienta en estos momentos:
- Después de mostrar propiedades: botones "Ver más", "Agendar visita", "Hablar con asesor"
- Después de dar detalles de una propiedad: "Quiero visitarla", "Ver más opciones", "Hablar con asesor"
- Para confirmar una cita: "Confirmar", "Cambiar horario"
- Cuando el cliente pide hablar con alguien fuera de horario: "Dejar mis datos", "Ver propiedades"
NUNCA uses botones para el primer contacto (usá la lista de opciones en su lugar).
NUNCA uses botones en medio de una conversación fluida donde el cliente está dando detalles.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "El mensaje principal que acompaña los botones",
                },
                "botones": {
                    "type": "array",
                    "description": "Lista de botones (máximo 3)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "ID único del botón (ej: btn_ver_mas)"},
                            "titulo": {"type": "string", "description": "Texto del botón (máx 20 caracteres)"},
                        },
                        "required": ["id", "titulo"],
                    },
                },
            },
            "required": ["texto", "botones"],
        },
    },
    {
        "name": "enviar_lista",
        "description": """Envía un mensaje de WhatsApp con una lista desplegable de opciones.
Usá esta herramienta SOLO en el primer contacto cuando el cliente saluda ("Hola", "Buenos días", etc.)
para preguntar qué tipo de consulta tiene. NO la uses en otros momentos.
La lista permite más opciones que los botones y es ideal para menús iniciales.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "El mensaje principal que acompaña la lista",
                },
                "texto_boton": {
                    "type": "string",
                    "description": "Texto del botón que abre la lista (ej: 'Ver opciones')",
                },
                "secciones": {
                    "type": "array",
                    "description": "Secciones de la lista",
                    "items": {
                        "type": "object",
                        "properties": {
                            "titulo": {"type": "string", "description": "Título de la sección"},
                            "filas": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string", "description": "ID único de la opción"},
                                        "titulo": {"type": "string", "description": "Texto de la opción (máx 24 chars)"},
                                        "descripcion": {"type": "string", "description": "Descripción opcional (máx 72 chars)"},
                                    },
                                    "required": ["id", "titulo"],
                                },
                            },
                        },
                        "required": ["titulo", "filas"],
                    },
                },
            },
            "required": ["texto", "texto_boton", "secciones"],
        },
    },
]

ALL_TOOLS = TOOLS_DEFINITION + INTERACTIVE_TOOLS


def cargar_config_prompts() -> dict:
    """Lee toda la configuración desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    """Lee el system prompt desde config/prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("system_prompt", "Eres un asistente útil. Responde en español.")


def obtener_mensaje_error() -> str:
    config = cargar_config_prompts()
    return config.get("error_message", "Lo siento, estoy teniendo problemas técnicos.")


def obtener_mensaje_fallback() -> str:
    config = cargar_config_prompts()
    return config.get("fallback_message", "Disculpa, no entendí tu mensaje.")


def _construir_respuesta_interactiva(nombre_tool: str, params: dict) -> Respuesta:
    """Construye un objeto Respuesta a partir de una herramienta interactiva."""
    if nombre_tool == "enviar_botones":
        botones = [
            Boton(id=b["id"], titulo=b["titulo"])
            for b in params.get("botones", [])[:3]
        ]
        return Respuesta(
            tipo="botones",
            texto=params.get("texto", ""),
            botones=botones,
        )
    elif nombre_tool == "enviar_lista":
        secciones = []
        for sec in params.get("secciones", []):
            filas = [
                FilaLista(
                    id=f.get("id", ""),
                    titulo=f.get("titulo", ""),
                    descripcion=f.get("descripcion", ""),
                )
                for f in sec.get("filas", [])
            ]
            secciones.append(SeccionLista(titulo=sec.get("titulo", ""), filas=filas))
        return Respuesta(
            tipo="lista",
            texto=params.get("texto", ""),
            texto_boton_lista=params.get("texto_boton", "Ver opciones"),
            secciones=secciones,
        )
    return Respuesta(tipo="texto", texto="")


async def _ejecutar_herramienta(nombre: str, parametros: dict) -> str | Respuesta:
    """Ejecuta una herramienta. Retorna str para herramientas de datos, Respuesta para interactivas."""
    logger.info(f"Ejecutando herramienta: {nombre}")

    if nombre == "buscar_propiedades":
        return await buscar_propiedades(**parametros)
    elif nombre == "obtener_detalle_propiedad":
        return await obtener_detalle_propiedad(**parametros)
    elif nombre == "registrar_lead_ghl":
        return await registrar_lead_ghl(**parametros)
    elif nombre == "obtener_link_agendar":
        return await obtener_link_agendar()
    elif nombre in ("enviar_botones", "enviar_lista"):
        return _construir_respuesta_interactiva(nombre, parametros)
    else:
        return f"Herramienta desconocida: {nombre}"


async def generar_respuesta(mensaje: str, historial: list[dict]) -> Respuesta:
    """
    Genera una respuesta usando Claude API con tool_use.
    Retorna un objeto Respuesta que puede ser texto, botones o lista.
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return Respuesta(tipo="texto", texto=obtener_mensaje_fallback())

    system_prompt = cargar_system_prompt()

    # Construir mensajes para la API
    mensajes = []
    for msg in historial:
        mensajes.append({"role": msg["role"], "content": msg["content"]})
    mensajes.append({"role": "user", "content": mensaje})

    try:
        # Primera llamada
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=mensajes,
            tools=ALL_TOOLS,
        )

        logger.info(f"Respuesta Claude ({response.usage.input_tokens} in / {response.usage.output_tokens} out) — stop: {response.stop_reason}")

        if response.stop_reason == "tool_use":
            tool_results = []
            assistant_content = response.content
            respuesta_interactiva = None

            for block in response.content:
                if block.type == "tool_use":
                    resultado = await _ejecutar_herramienta(block.name, block.input)

                    # Si es una herramienta interactiva, guardar la respuesta
                    if isinstance(resultado, Respuesta):
                        respuesta_interactiva = resultado
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Mensaje interactivo ({resultado.tipo}) enviado exitosamente.",
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": resultado,
                        })

            # Si hay una respuesta interactiva, retornarla directamente
            if respuesta_interactiva:
                return respuesta_interactiva

            # Si no, segunda llamada para que Claude formule la respuesta con datos
            mensajes.append({"role": "assistant", "content": assistant_content})
            mensajes.append({"role": "user", "content": tool_results})

            response2 = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                messages=mensajes,
                tools=ALL_TOOLS,
            )

            logger.info(f"Respuesta final ({response2.usage.input_tokens} in / {response2.usage.output_tokens} out) — stop: {response2.stop_reason}")

            # Verificar si la segunda respuesta también usa herramientas interactivas
            if response2.stop_reason == "tool_use":
                for block in response2.content:
                    if block.type == "tool_use" and block.name in ("enviar_botones", "enviar_lista"):
                        return _construir_respuesta_interactiva(block.name, block.input)

            # Extraer texto
            for block in response2.content:
                if hasattr(block, "text"):
                    return Respuesta(tipo="texto", texto=block.text)

            return Respuesta(tipo="texto", texto=obtener_mensaje_error())

        # Respuesta directa (sin herramientas)
        for block in response.content:
            if hasattr(block, "text"):
                return Respuesta(tipo="texto", texto=block.text)

        return Respuesta(tipo="texto", texto=obtener_mensaje_error())

    except Exception as e:
        logger.error(f"Error Claude API: {e}")
        return Respuesta(tipo="texto", texto=obtener_mensaje_error())
