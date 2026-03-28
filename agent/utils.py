# agent/utils.py — Utilidades compartidas del agente
# Generado por AgentKit

"""
Funciones de utilidad centralizadas usadas en todo el sistema.
Evita duplicar lógica de normalización de teléfonos entre módulos.
"""

import re
import logging

logger = logging.getLogger("agentkit")


def normalizar_telefono(raw: str) -> str:
    """
    Normaliza cualquier formato de teléfono a dígitos puros con prefijo correcto.

    Retorna siempre dígitos sin prefijo '+', sin sufijos WhatsApp, en forma canónica
    para Argentina (13 dígitos: 549 + área + abonado).

    Entradas aceptadas:
      - "5493517575244@s.whatsapp.net"  → "5493517575244"  (formato Whapi entrante)
      - "5493517575244@c.us"            → "5493517575244"  (formato alternativo)
      - "+543517575244"                 → "5493517575244"  (GHL: falta el 9 móvil AR)
      - "543517575244"                  → "5493517575244"  (sin +, falta el 9 móvil)
      - "0351 7575244"                  → "5493517575244"  (trunk prefix + área local)
      - "3517575244"                    → "5493517575244"  (sin código de país, 10 dígitos)
      - "15 7575244"                    → resultado variable (prefijo móvil local, baja confianza)

    Args:
        raw: Número de teléfono en cualquier formato de entrada

    Returns:
        Número normalizado como string de dígitos puros.
        Para Argentina móvil: 13 dígitos comenzando con "549".
    """
    if not raw:
        logger.warning("normalizar_telefono: recibió string vacío")
        return ""

    # Quitar sufijo WhatsApp (@s.whatsapp.net, @c.us, etc.)
    s = re.sub(r"@.*", "", raw)

    # Quitar todo lo que no sea dígito (espacios, +, -, paréntesis, etc.)
    s = re.sub(r"[^\d]", "", s)

    if not s:
        logger.warning(f"normalizar_telefono: no quedan dígitos después de limpiar '{raw}'")
        return raw

    # Remover trunk prefix "0" de Argentina (ej: "0351..." → "351...")
    if s.startswith("0"):
        s = s[1:]

    # Remover prefijo móvil local "15" solo si el número aún es corto
    # (sin código de país, <= 10 dígitos: área + abonado + prefijo)
    if s.startswith("15") and len(s) <= 10:
        s = s[2:]

    # Si tiene 10 dígitos: número local AR sin código de país (área 3 dígitos + abonado 7)
    # Agregar prefijo completo "549" (código país + indicador móvil)
    if len(s) == 10:
        s = "549" + s

    # Si tiene código de país 54 pero le falta el indicador móvil 9 (12 dígitos)
    # GHL almacena: +543517575244 (12 dígitos) → WhatsApp necesita: 5493517575244 (13 dígitos)
    if s.startswith("54") and not s.startswith("549") and len(s) == 12:
        s = "549" + s[2:]

    return s
