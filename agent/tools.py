# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas para Inmobiliaria Bertero.
Funciones de FAQ, búsqueda de propiedades, agendamiento de citas y calificación de leads.
"""

import os
import yaml
import logging
from datetime import datetime

logger = logging.getLogger("agentkit")


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio."""
    info = cargar_info_negocio()
    return {
        "horario": info.get("negocio", {}).get("horario", "No disponible"),
        "esta_abierto": True,  # TODO: calcular según hora actual y horario
    }


def buscar_en_knowledge(consulta: str) -> str:
    """
    Busca información relevante en los archivos de /knowledge.
    Retorna el contenido más relevante encontrado.
    """
    resultados = []
    knowledge_dir = "knowledge"

    if not os.path.exists(knowledge_dir):
        return "No hay archivos de conocimiento disponibles."

    for archivo in os.listdir(knowledge_dir):
        ruta = os.path.join(knowledge_dir, archivo)
        if archivo.startswith(".") or not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                if consulta.lower() in contenido.lower():
                    resultados.append(f"[{archivo}]: {contenido[:500]}")
        except (UnicodeDecodeError, IOError):
            continue

    if resultados:
        return "\n---\n".join(resultados)
    return "No encontré información específica sobre eso en mis archivos."


def obtener_tipos_propiedades() -> dict:
    """Retorna los tipos de propiedades disponibles y cantidades."""
    info = cargar_info_negocio()
    return {
        "tipos": info.get("propiedades", {}).get("tipos", []),
        "total": info.get("propiedades", {}).get("total", 0),
        "rango_precios": info.get("propiedades", {}).get("rango_precios", "No disponible"),
        "zonas": info.get("propiedades", {}).get("zonas", []),
    }


def registrar_lead(telefono: str, nombre: str, interes: str, presupuesto: str = "", zona: str = "") -> dict:
    """
    Registra un nuevo lead interesado en comprar/alquilar.
    En producción esto se conectaría a un CRM.
    """
    lead = {
        "telefono": telefono,
        "nombre": nombre,
        "interes": interes,
        "presupuesto": presupuesto,
        "zona": zona,
        "fecha": datetime.now().isoformat(),
        "estado": "nuevo",
    }
    logger.info(f"Nuevo lead registrado: {lead}")
    # TODO: enviar a CRM, Google Sheets, o base de datos de leads
    return lead


def agendar_visita(telefono: str, nombre: str, propiedad: str, fecha: str, hora: str) -> dict:
    """
    Agenda una visita a una propiedad.
    En producción esto se conectaría a Google Calendar o sistema de citas.
    """
    cita = {
        "telefono": telefono,
        "nombre": nombre,
        "propiedad": propiedad,
        "fecha": fecha,
        "hora": hora,
        "estado": "pendiente",
        "creada": datetime.now().isoformat(),
    }
    logger.info(f"Visita agendada: {cita}")
    # TODO: crear evento en Google Calendar, notificar al asesor
    return cita
