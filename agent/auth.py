# agent/auth.py — Verificación de firma GHL Ed25519
# Generado por AgentKit — Plan 01-02

"""
Módulo de autenticación para webhooks de GoHighLevel (GHL).

GHL firma cada webhook con Ed25519 (header X-GHL-Signature).
La clave pública está hardcodeada aquí porque ES una clave pública — no es un secreto.

Fuente: https://marketplace.gohighlevel.com/docs/webhook/WebhookIntegrationGuide/index.html
Deprecación RSA (X-WH-Signature): julio 1, 2026 — solo implementar Ed25519.
"""

import base64
import logging
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger("agentkit")

# Clave pública de GHL para verificar X-GHL-Signature (Ed25519)
# Esta es una clave PÚBLICA — está bien hardcodearla y commitearla.
# Fuente oficial: GHL Developer Documentation (webhook integration guide)
GHL_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAi2HR1srL4o18O8BRa7gVJY7G7bupbN3H9AwJrHCDiOg=
-----END PUBLIC KEY-----"""

# Cargar la clave pública al inicializar el módulo (una sola vez)
_ghl_pubkey: Ed25519PublicKey = serialization.load_pem_public_key(GHL_PUBLIC_KEY_PEM)  # type: ignore[assignment]


def verificar_firma_ghl(raw_body: bytes, signature_b64: str) -> bool:
    """
    Verifica la firma Ed25519 de un webhook de GHL.

    Args:
        raw_body: El cuerpo del request en bytes (leer con request.body() ANTES de request.json())
        signature_b64: El valor del header X-GHL-Signature (base64 encoded)

    Returns:
        True si la firma es válida, False si es inválida o hay cualquier error.
    """
    try:
        sig = base64.b64decode(signature_b64)
        _ghl_pubkey.verify(sig, raw_body)
        return True
    except InvalidSignature:
        logger.warning("Webhook GHL rechazado — firma Ed25519 inválida")
        return False
    except Exception as e:
        logger.warning(f"Webhook GHL rechazado — error al verificar firma: {e}")
        return False
