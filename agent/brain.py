# agent/brain.py — Cerebro del agente: conexión con Claude API + Tool Use
# Generado por AgentKit

"""
Lógica de IA del agente. Lee el system prompt de prompts.yaml
y genera respuestas usando la API de Anthropic Claude con tool_use
para buscar propiedades y enviar mensajes interactivos.
"""

import os
import io
import json
import yaml
import logging
import base64
import asyncio
import httpx
from anthropic import AsyncAnthropic
from openai import OpenAI
from dotenv import load_dotenv

from agent.tools import (
    buscar_propiedades,
    obtener_detalle_propiedad,
    registrar_lead_ghl,
    obtener_link_agendar,
    obtener_propiedades_para_visita,
    reiniciar_conversacion,
    TOOLS_DEFINITION,
)
from agent.providers.base import Respuesta, Boton, SeccionLista, FilaLista

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente de Anthropic
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Cliente de OpenAI para transcripcion Whisper
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Modelo — Haiku 3.5 para costos bajos en producción, Sonnet para desarrollo/testing
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Cache del system prompt y mensajes de error/fallback (se cargan una sola vez)
_config_cache = None


def _get_config() -> dict:
    """Lee config de prompts.yaml con cache en memoria."""
    global _config_cache
    if _config_cache is None:
        try:
            with open("config/prompts.yaml", "r", encoding="utf-8") as f:
                _config_cache = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.error("config/prompts.yaml no encontrado")
            _config_cache = {}
    return _config_cache

# Herramientas de mensajes interactivos (se agregan a TOOLS_DEFINITION)
INTERACTIVE_TOOLS = [
    {
        "name": "enviar_botones",
        "description": "Envía mensaje con botones de respuesta rápida (máx 3). Usar después de mostrar propiedades o detalles. NO usar en primer contacto ni en conversación fluida.",
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
        "description": "Envía mensaje con lista desplegable de opciones. Usar en el flujo de calificación: 1) Saludo→opciones de consulta, 2) Tipo de propiedad, 3) Zona, 4) Presupuesto. Ver system prompt para IDs y secciones exactas. NO usar en conversación fluida con texto libre.",
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


def cargar_system_prompt() -> str:
    """Lee el system prompt (cacheado en memoria)."""
    return _get_config().get("system_prompt", "Eres un asistente útil. Responde en español.")


def obtener_mensaje_error() -> str:
    return _get_config().get("error_message", "Lo siento, estoy teniendo problemas técnicos.")


def obtener_mensaje_fallback() -> str:
    return _get_config().get("fallback_message", "Disculpa, no entendí tu mensaje.")


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
    elif nombre == "obtener_propiedades_para_visita":
        return obtener_propiedades_para_visita(**parametros)
    elif nombre == "reiniciar_conversacion":
        return await reiniciar_conversacion(**parametros)
    elif nombre in ("enviar_botones", "enviar_lista"):
        return _construir_respuesta_interactiva(nombre, parametros)
    else:
        return f"Herramienta desconocida: {nombre}"


async def _descargar_y_transcribir_audio(url: str, mime: str = "audio/ogg; codecs=opus") -> str | None:
    """Descarga audio desde Whapi y lo transcribe con OpenAI Whisper en memoria (sin escribir a disco)."""
    if not url:
        return None
    try:
        token = os.getenv("WHAPI_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(url, headers=headers, follow_redirects=True)
            if r.status_code != 200:
                logger.error(f"Error descargando audio: {r.status_code}")
                return None

        # Mapear MIME a extension que Whisper reconoce
        mime_base = mime.split(";")[0].strip()
        mime_to_ext = {
            "audio/ogg": "oga",
            "audio/opus": "oga",
            "audio/mpeg": "mp3",
            "audio/mp4": "m4a",
            "audio/wav": "wav",
            "audio/webm": "webm",
        }
        ext = mime_to_ext.get(mime_base, "oga")

        # Crear buffer en memoria — el nombre es critico para que Whisper detecte el formato
        buffer = io.BytesIO(r.content)
        buffer.name = f"audio.{ext}"

        logger.info(f"Transcribiendo audio: {len(r.content)} bytes, ext={ext}")

        # Llamada sincrona a Whisper envuelta en asyncio.to_thread para no bloquear el event loop
        def transcribir():
            return openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=buffer,
                language="es",
            )
        resultado = await asyncio.to_thread(transcribir)

        texto = resultado.text.strip() if resultado.text else None
        if texto:
            logger.info(f"Audio transcrito ({len(r.content)} bytes): '{texto[:80]}'")
        return texto or None

    except Exception as e:
        logger.error(f"Error transcribiendo audio: {e}")
        return None


async def _descargar_imagen_base64(url: str, mime: str = "image/jpeg") -> tuple[str, str] | None:
    """Descarga una imagen desde Whapi y la convierte a base64 para Claude Vision."""
    if not url:
        return None
    try:
        token = os.getenv("WHAPI_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers=headers, follow_redirects=True)
            if r.status_code == 200:
                img_b64 = base64.b64encode(r.content).decode("utf-8")
                # Detectar mime del content-type si no lo tenemos
                content_type = r.headers.get("content-type", mime)
                if "/" in content_type:
                    mime = content_type.split(";")[0].strip()
                logger.info(f"Imagen descargada: {len(r.content)} bytes, mime={mime}")
                return img_b64, mime
            else:
                logger.error(f"Error descargando imagen: {r.status_code}")
                return None
    except Exception as e:
        logger.error(f"Error descargando imagen: {e}")
        return None


async def generar_respuesta(mensaje: str, historial: list[dict], imagen_url: str = "", imagen_mime: str = "", audio_url: str = "", audio_mime: str = "") -> Respuesta:
    """
    Genera una respuesta usando Claude API con tool_use.
    Retorna un objeto Respuesta que puede ser texto, botones o lista.
    Soporta imágenes via Claude Vision y transcripcion de audio via Whisper.
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return Respuesta(tipo="texto", texto=obtener_mensaje_fallback())

    # Si hay audio, transcribir y reemplazar SOLO el placeholder (ultima linea del contexto)
    # Preserva las etiquetas [CONTEXTO INTERNO], [CLIENTE NUEVO/RECURRENTE], boton/lista IDs
    if audio_url:
        transcripcion = await _descargar_y_transcribir_audio(audio_url, audio_mime)
        if transcripcion:
            # rsplit('\n', 1) separa el contexto prefix de la ultima linea (placeholder del audio)
            lines = mensaje.rsplit('\n', 1)
            mensaje = lines[0] + '\n' + transcripcion
            logger.info(f"Audio transcrito: '{transcripcion[:80]}'")
        else:
            return Respuesta(tipo="texto", texto="No pude escuchar bien tu mensaje de voz. ¿Podrias escribirme lo que necesitas?")

    system_prompt = cargar_system_prompt()

    # Construir mensajes para la API — últimos 16 mensajes (8 intercambios)
    # para no perder contexto del flujo de calificación (operación, tipo, zona, precio)
    # Recortar mensajes muy largos (listados de propiedades) para no volar el contexto
    MAX_MSG_CHARS = 1500
    mensajes = []
    historial_reciente = historial[-16:] if len(historial) > 16 else historial
    for msg in historial_reciente:
        content = msg["content"]
        if len(content) > MAX_MSG_CHARS:
            content = content[:MAX_MSG_CHARS] + "\n[... mensaje recortado por longitud]"
        mensajes.append({"role": msg["role"], "content": content})

    # Si hay imagen, construir mensaje multimodal (imagen + texto)
    if imagen_url:
        img_data = await _descargar_imagen_base64(imagen_url, imagen_mime)
        if img_data:
            img_b64, mime = img_data
            mensajes.append({
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": mensaje,
                    },
                ],
            })
        else:
            # Si no se pudo descargar la imagen, enviar solo texto con aviso
            mensajes.append({"role": "user", "content": mensaje + "\n[No se pudo procesar la imagen enviada]"})
    else:
        mensajes.append({"role": "user", "content": mensaje})

    try:
        # Primera llamada — necesita espacio suficiente para tool_use con listas interactivas (muchas filas)
        response = await client.messages.create(
            model=MODEL,
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

            # Si hay una respuesta interactiva, incluir el texto que Claude generó
            if respuesta_interactiva:
                texto_previo = ""
                for block in assistant_content:
                    if hasattr(block, "text") and block.text:
                        texto_previo += block.text
                if texto_previo:
                    # Usar texto de Claude como texto principal, reemplazando el de la lista
                    # para evitar duplicación (Claude suele repetir la misma frase en ambos)
                    respuesta_interactiva.texto = texto_previo.strip()
                return respuesta_interactiva

            # Segunda llamada — Claude formula la respuesta con los datos de la herramienta
            # Incluimos tools solo para enviar_botones/enviar_lista (puede querer agregar botones post-búsqueda)
            mensajes.append({"role": "assistant", "content": assistant_content})
            mensajes.append({"role": "user", "content": tool_results})

            response2 = await client.messages.create(
                model=MODEL,
                max_tokens=768,
                system=system_prompt,
                messages=mensajes,
                tools=INTERACTIVE_TOOLS,
            )

            logger.info(f"Respuesta final ({response2.usage.input_tokens} in / {response2.usage.output_tokens} out) — stop: {response2.stop_reason}")

            # Verificar si la segunda respuesta tiene texto + herramientas interactivas
            # Claude puede responder con texto (propiedades) + botones en el mismo response
            texto_acumulado = ""
            respuesta_interactiva2 = None

            for block in response2.content:
                if hasattr(block, "text") and block.text:
                    texto_acumulado += block.text
                elif block.type == "tool_use" and block.name in ("enviar_botones", "enviar_lista"):
                    respuesta_interactiva2 = _construir_respuesta_interactiva(block.name, block.input)

            # Si hay interactivo, usar texto de Claude como principal (evita duplicación)
            if respuesta_interactiva2:
                if texto_acumulado:
                    respuesta_interactiva2.texto = texto_acumulado.strip()
                return respuesta_interactiva2

            # Solo texto
            if texto_acumulado:
                return Respuesta(tipo="texto", texto=texto_acumulado)

            return Respuesta(tipo="texto", texto=obtener_mensaje_error())

        # Respuesta directa (sin herramientas)
        for block in response.content:
            if hasattr(block, "text"):
                return Respuesta(tipo="texto", texto=block.text)

        return Respuesta(tipo="texto", texto=obtener_mensaje_error())

    except Exception as e:
        import traceback
        logger.error(f"Error Claude API: {e}\n{traceback.format_exc()}")
        return Respuesta(tipo="texto", texto=obtener_mensaje_error())
