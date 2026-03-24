# agent/providers/whapi.py — Adaptador para Whapi.cloud
# Generado por AgentKit

import os
import logging
import httpx
from fastapi import Request
from agent.providers.base import (
    ProveedorWhatsApp, MensajeEntrante,
    Boton, SeccionLista,
)

logger = logging.getLogger("agentkit")

API_BASE = "https://gate.whapi.cloud"


class ProveedorWhapi(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando Whapi.cloud con soporte para mensajes interactivos."""

    def __init__(self):
        self.token = os.getenv("WHAPI_TOKEN")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload de Whapi.cloud incluyendo respuestas de botones/listas."""
        body = await request.json()
        mensajes = []
        for msg in body.get("messages", []):
            texto = msg.get("text", {}).get("body", "")
            boton_id = ""
            lista_id = ""

            # Detectar respuestas interactivas (botón o lista)
            interactive = msg.get("interactive", {})
            if interactive:
                tipo_interactivo = interactive.get("type", "")
                if tipo_interactivo == "buttons_reply":
                    reply = interactive.get("buttons_reply", {})
                    boton_id = reply.get("id", "")
                    texto = reply.get("title", texto)
                elif tipo_interactivo == "list_reply":
                    reply = interactive.get("list_reply", {})
                    lista_id = reply.get("id", "")
                    texto = reply.get("title", texto)

            mensajes.append(MensajeEntrante(
                telefono=msg.get("chat_id", ""),
                texto=texto,
                mensaje_id=msg.get("id", ""),
                es_propio=msg.get("from_me", False),
                boton_id=boton_id,
                lista_id=lista_id,
            ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía mensaje de texto via Whapi.cloud."""
        if not self.token:
            logger.warning("WHAPI_TOKEN no configurado — mensaje no enviado")
            return False
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{API_BASE}/messages/text",
                json={"to": telefono, "body": mensaje},
                headers=self._headers(),
            )
            if r.status_code != 200:
                logger.error(f"Error Whapi texto: {r.status_code} — {r.text}")
            return r.status_code == 200

    async def enviar_botones(self, telefono: str, texto: str, botones: list[Boton]) -> bool:
        """Envía mensaje con botones de respuesta rápida via Whapi.cloud."""
        if not self.token:
            logger.warning("WHAPI_TOKEN no configurado — mensaje no enviado")
            return False

        payload = {
            "to": telefono,
            "type": "button",
            "body": {"text": texto},
            "action": {
                "buttons": [
                    {
                        "type": "quick_reply",
                        "title": b.titulo[:20],  # Máx 20 chars
                        "id": b.id,
                    }
                    for b in botones[:3]  # Máx 3 botones
                ]
            },
        }

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{API_BASE}/messages/interactive",
                json=payload,
                headers=self._headers(),
            )
            if r.status_code != 200:
                logger.warning(f"Error Whapi botones: {r.status_code} — {r.text}. Enviando como texto.")
                # Fallback a texto si los botones fallan
                return await super().enviar_botones(telefono, texto, botones)
            return True

    async def enviar_lista(self, telefono: str, texto: str, texto_boton: str, secciones: list[SeccionLista]) -> bool:
        """Envía mensaje con lista desplegable via Whapi.cloud."""
        if not self.token:
            logger.warning("WHAPI_TOKEN no configurado — mensaje no enviado")
            return False

        payload = {
            "to": telefono,
            "type": "list",
            "body": {"text": texto},
            "action": {
                "list": {
                    "label": texto_boton or "Ver opciones",
                    "sections": [
                        {
                            "title": sec.titulo,
                            "rows": [
                                {
                                    "id": fila.id,
                                    "title": fila.titulo[:24],  # Máx 24 chars
                                    "description": fila.descripcion[:72] if fila.descripcion else "",
                                }
                                for fila in sec.filas
                            ],
                        }
                        for sec in secciones
                    ],
                }
            },
        }

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{API_BASE}/messages/interactive",
                json=payload,
                headers=self._headers(),
            )
            if r.status_code != 200:
                logger.warning(f"Error Whapi lista: {r.status_code} — {r.text}. Enviando como texto.")
                # Fallback a texto si la lista falla
                return await super().enviar_lista(telefono, texto, texto_boton, secciones)
            return True
