#!/usr/bin/env python3
# tools/configure_whapi_webhook.py — Configuración one-time del webhook de Whapi
# Generado por AgentKit — Plan 01-02
#
# Run once after deploy to configure Whapi webhook auth header.
#
# PASOS:
# 1. Asegúrate de tener WHAPI_TOKEN, WHAPI_WEBHOOK_SECRET y WEBHOOK_URL en tu .env
# 2. Ejecutar:  python tools/configure_whapi_webhook.py
# 3. Verificar que la respuesta sea 200 OK
#
# Qué hace:
# - Registra tu webhook URL en Whapi via PATCH /settings
# - Agrega el header X-Whapi-Token con tu secreto en cada callback
# - Después de esto, webhook_handler rechaza cualquier request sin el token correcto

import os
import sys
import httpx
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

WHAPI_TOKEN = os.getenv("WHAPI_TOKEN", "")
WHAPI_WEBHOOK_SECRET = os.getenv("WHAPI_WEBHOOK_SECRET", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")


def main():
    # Validar que tenemos todo lo necesario
    if not WHAPI_TOKEN:
        print("ERROR: WHAPI_TOKEN no configurado en .env")
        sys.exit(1)

    if not WHAPI_WEBHOOK_SECRET:
        print("ERROR: WHAPI_WEBHOOK_SECRET no configurado en .env")
        print("Generar un secreto con: openssl rand -hex 32")
        sys.exit(1)

    if not WEBHOOK_URL:
        print("ERROR: WEBHOOK_URL no configurado en .env")
        print("Ejemplo: WEBHOOK_URL=https://tu-app.up.railway.app/webhook")
        sys.exit(1)

    print(f"Configurando webhook en Whapi...")
    print(f"  URL: {WEBHOOK_URL}")
    print(f"  Secret: {WHAPI_WEBHOOK_SECRET[:8]}...{'*' * (len(WHAPI_WEBHOOK_SECRET) - 8)}")

    r = httpx.patch(
        "https://gate.whapi.cloud/settings",
        headers={
            "Authorization": f"Bearer {WHAPI_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "webhooks": [{
                "events": [{"type": "messages", "method": "post"}],
                "mode": "body",
                "headers": {"X-Whapi-Token": WHAPI_WEBHOOK_SECRET},
                "url": WEBHOOK_URL,
            }]
        },
        timeout=30.0,
    )

    print(f"\nRespuesta Whapi: {r.status_code}")
    print(r.text)

    if r.status_code == 200:
        print("\nOK — Webhook configurado correctamente.")
        print("Whapi enviará X-Whapi-Token en cada callback.")
    else:
        print(f"\nERROR — El request falló con status {r.status_code}")
        print("Revisar WHAPI_TOKEN y que tu plan de Whapi soporte webhooks con headers.")
        sys.exit(1)


if __name__ == "__main__":
    main()
