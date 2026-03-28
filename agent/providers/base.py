# agent/providers/base.py — Clase base para proveedores de WhatsApp
# Generado por AgentKit

"""
Define la interfaz común que todos los proveedores de WhatsApp deben implementar.
Esto permite cambiar de proveedor sin modificar el resto del código.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fastapi import Request


@dataclass
class MensajeEntrante:
    """Mensaje normalizado — mismo formato sin importar el proveedor."""
    telefono: str       # Número del remitente
    texto: str          # Contenido del mensaje
    mensaje_id: str     # ID único del mensaje
    es_propio: bool     # True si lo envió el agente (se ignora)
    boton_id: str = ""  # ID del botón clickeado (si aplica)
    lista_id: str = ""  # ID de la opción de lista seleccionada (si aplica)
    imagen_url: str = ""  # URL de la imagen (si el mensaje es una foto)
    imagen_mime: str = ""  # MIME type de la imagen (image/jpeg, image/png, etc.)
    audio_url: str = ""   # URL del audio/voice note (si el mensaje es audio)
    audio_mime: str = ""  # MIME type del audio (audio/ogg; codecs=opus, etc.)


@dataclass
class Boton:
    """Un botón de respuesta rápida."""
    id: str         # ID único del botón (se recibe en el webhook)
    titulo: str     # Texto visible del botón (máx ~20 chars)


@dataclass
class FilaLista:
    """Una opción dentro de una sección de lista."""
    id: str              # ID único de la opción
    titulo: str          # Texto visible
    descripcion: str = ""  # Descripción opcional


@dataclass
class SeccionLista:
    """Una sección dentro de una lista."""
    titulo: str                    # Título de la sección
    filas: list[FilaLista] = field(default_factory=list)


@dataclass
class Respuesta:
    """Respuesta del agente — puede ser texto, botones o lista."""
    tipo: str = "texto"           # "texto" | "botones" | "lista"
    texto: str = ""               # Mensaje principal
    botones: list[Boton] = field(default_factory=list)          # Para tipo "botones" (máx 3)
    texto_boton_lista: str = ""   # Texto del botón que abre la lista
    secciones: list[SeccionLista] = field(default_factory=list)  # Para tipo "lista"


class ProveedorWhatsApp(ABC):
    """Interfaz que cada proveedor de WhatsApp debe implementar."""

    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Extrae y normaliza mensajes del payload del webhook."""
        ...

    @abstractmethod
    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía un mensaje de texto. Retorna True si fue exitoso."""
        ...

    async def enviar_botones(self, telefono: str, texto: str, botones: list[Boton]) -> bool:
        """Envía mensaje con botones. Fallback: envía como texto."""
        texto_con_opciones = texto + "\n\n" + "\n".join(
            f"• {b.titulo}" for b in botones
        )
        return await self.enviar_mensaje(telefono, texto_con_opciones)

    async def enviar_lista(self, telefono: str, texto: str, texto_boton: str, secciones: list[SeccionLista]) -> bool:
        """Envía mensaje con lista desplegable. Fallback: envía como texto."""
        texto_con_opciones = texto
        for sec in secciones:
            texto_con_opciones += f"\n\n*{sec.titulo}*"
            for fila in sec.filas:
                texto_con_opciones += f"\n• {fila.titulo}"
                if fila.descripcion:
                    texto_con_opciones += f" — {fila.descripcion}"
        return await self.enviar_mensaje(telefono, texto_con_opciones)

    async def enviar_respuesta(self, telefono: str, respuesta: Respuesta) -> bool:
        """Envía una respuesta según su tipo."""
        if respuesta.tipo == "botones" and respuesta.botones:
            return await self.enviar_botones(telefono, respuesta.texto, respuesta.botones)
        elif respuesta.tipo == "lista" and respuesta.secciones:
            return await self.enviar_lista(telefono, respuesta.texto, respuesta.texto_boton_lista, respuesta.secciones)
        else:
            return await self.enviar_mensaje(telefono, respuesta.texto)

    async def enviar_indicador_tipeo(self, telefono: str) -> bool:
        """Envía indicador de 'escribiendo...' al chat. Override en cada proveedor."""
        return False

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Verificación GET del webhook (solo Meta la requiere). Retorna respuesta o None."""
        return None
