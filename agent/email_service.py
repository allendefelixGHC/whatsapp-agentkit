# agent/email_service.py — Envío de emails via SMTP (Microsoft 365)
# Generado por AgentKit

"""
Servicio de emails para notificaciones de visitas.
Usa SMTP de Microsoft 365 (agenda@propulsar.ai) para enviar
confirmaciones al cliente y notificaciones al vendedor.
"""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("agentkit")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
VENDEDOR_EMAIL = os.getenv("VENDEDOR_EMAIL", "ventasbertero@gmail.com")


def _enviar_email(destinatario: str, asunto: str, cuerpo_html: str) -> bool:
    """Envía un email via SMTP. Retorna True si fue exitoso."""
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP no configurado — email no enviado")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"Inmobiliaria Bertero <{SMTP_FROM}>"
        msg["To"] = destinatario
        msg["Subject"] = asunto
        msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Email enviado a {destinatario}: {asunto}")
        return True

    except Exception as e:
        logger.error(f"Error enviando email a {destinatario}: {e}")
        return False


def enviar_confirmacion_cliente(
    email_cliente: str,
    nombre: str,
) -> bool:
    """Envía email de confirmación de visita al cliente."""
    asunto = "Confirmación de tu visita — Inmobiliaria Bertero"
    cuerpo = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2c3e50;">¡Hola {nombre}!</h2>
        <p style="font-size: 16px; color: #333;">
            <strong>¡Tu visita ha sido confirmada!</strong> 🎉
        </p>
        <p style="font-size: 15px; color: #555;">
            Un asesor de Inmobiliaria Bertero va a estar esperándote.
        </p>
        <p style="font-size: 15px; color: #555;">
            Si necesitás reprogramar o cancelar, podés hacerlo desde el mismo link
            de confirmación o escribirnos por WhatsApp al
            <strong>351 593 2736</strong>.
        </p>
        <p style="font-size: 15px; color: #555;">¡Nos vemos pronto!</p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
        <p style="font-size: 13px; color: #999;">
            <strong>Bertero Negocios Inmobiliarios</strong><br>
            Av. Maipú 51 - Piso 10 - Oficina 1, Córdoba<br>
            <a href="https://www.inmobiliariabertero.com.ar" style="color: #3498db;">
                www.inmobiliariabertero.com.ar
            </a>
        </p>
    </div>
    """
    return _enviar_email(email_cliente, asunto, cuerpo)


def enviar_notificacion_vendedor(
    nombre_cliente: str,
    email_cliente: str,
    telefono_cliente: str,
) -> bool:
    """Envía notificación de nueva visita al vendedor."""
    asunto = f"🏠 Nueva visita agendada — {nombre_cliente}"
    cuerpo = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2c3e50;">Nueva visita agendada</h2>
        <p style="font-size: 16px; color: #333;">
            Se ha agendado una nueva visita para <strong>{nombre_cliente}</strong>.
        </p>
        <table style="font-size: 15px; color: #555; border-collapse: collapse; margin: 15px 0;">
            <tr>
                <td style="padding: 8px 15px 8px 0;"><strong>📧 Email:</strong></td>
                <td style="padding: 8px 0;">{email_cliente}</td>
            </tr>
            <tr>
                <td style="padding: 8px 15px 8px 0;"><strong>📱 Teléfono:</strong></td>
                <td style="padding: 8px 0;">{telefono_cliente}</td>
            </tr>
        </table>
        <p style="font-size: 15px; color: #555;">
            Revisá los detalles en el sistema.
        </p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
        <p style="font-size: 13px; color: #999;">
            Notificación automática — Inmobiliaria Bertero
        </p>
    </div>
    """
    return _enviar_email(VENDEDOR_EMAIL, asunto, cuerpo)
