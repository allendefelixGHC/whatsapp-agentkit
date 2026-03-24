# agent/brain.py — Cerebro del agente: conexión con Claude API + Tool Use
# Generado por AgentKit

"""
Lógica de IA del agente. Lee el system prompt de prompts.yaml
y genera respuestas usando la API de Anthropic Claude con tool_use
para buscar propiedades en tiempo real.
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
    TOOLS_DEFINITION,
)

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente de Anthropic
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


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
    """Retorna el mensaje de error configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("error_message", "Lo siento, estoy teniendo problemas técnicos. Por favor intenta de nuevo en unos minutos.")


def obtener_mensaje_fallback() -> str:
    """Retorna el mensaje de fallback configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("fallback_message", "Disculpa, no entendí tu mensaje. ¿Podrías reformularlo?")


async def _ejecutar_herramienta(nombre: str, parametros: dict) -> str:
    """Ejecuta una herramienta y retorna el resultado como texto."""
    logger.info(f"Ejecutando herramienta: {nombre} con params: {parametros}")

    if nombre == "buscar_propiedades":
        return await buscar_propiedades(**parametros)
    elif nombre == "obtener_detalle_propiedad":
        return await obtener_detalle_propiedad(**parametros)
    else:
        return f"Herramienta desconocida: {nombre}"


async def generar_respuesta(mensaje: str, historial: list[dict]) -> str:
    """
    Genera una respuesta usando Claude API con tool_use.
    Si Claude necesita buscar propiedades, ejecuta la herramienta
    y le devuelve los resultados para que formule la respuesta final.

    Args:
        mensaje: El mensaje nuevo del usuario
        historial: Lista de mensajes anteriores [{"role": "user/assistant", "content": "..."}]

    Returns:
        La respuesta generada por Claude
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    system_prompt = cargar_system_prompt()

    # Construir mensajes para la API
    mensajes = []
    for msg in historial:
        mensajes.append({
            "role": msg["role"],
            "content": msg["content"]
        })
    mensajes.append({
        "role": "user",
        "content": mensaje
    })

    try:
        # Primera llamada — Claude decide si necesita herramientas
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=mensajes,
            tools=TOOLS_DEFINITION,
        )

        logger.info(f"Respuesta Claude ({response.usage.input_tokens} in / {response.usage.output_tokens} out) — stop: {response.stop_reason}")

        # Si Claude quiere usar una herramienta
        if response.stop_reason == "tool_use":
            # Procesar todos los bloques de la respuesta
            tool_results = []
            assistant_content = response.content

            for block in response.content:
                if block.type == "tool_use":
                    # Ejecutar la herramienta
                    resultado = await _ejecutar_herramienta(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": resultado,
                    })

            # Segunda llamada — Claude formula la respuesta con los datos
            mensajes.append({"role": "assistant", "content": assistant_content})
            mensajes.append({"role": "user", "content": tool_results})

            response2 = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                messages=mensajes,
                tools=TOOLS_DEFINITION,
            )

            logger.info(f"Respuesta final ({response2.usage.input_tokens} in / {response2.usage.output_tokens} out)")

            # Extraer texto de la respuesta
            for block in response2.content:
                if hasattr(block, "text"):
                    return block.text

            return obtener_mensaje_error()

        # Si Claude responde directamente (sin herramientas)
        for block in response.content:
            if hasattr(block, "text"):
                return block.text

        return obtener_mensaje_error()

    except Exception as e:
        logger.error(f"Error Claude API: {e}")
        return obtener_mensaje_error()
