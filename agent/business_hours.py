# agent/business_hours.py — Deteccion de horario de atencion de Bertero Inmobiliaria
# Generado por AgentKit (FU-03)

"""
Modulo de horario de atencion para Bertero Cordoba.
Detecta si el momento actual esta dentro del horario de atencion en la
zona horaria de Argentina/Cordoba (UTC-3, sin DST).

Horario:
  Lunes a Viernes: 9:00 a 18:00 hs
  Sabados: 10:00 a 14:00 hs
  Domingos: cerrado

Exporta:
  esta_en_horario() -> bool
  AFTER_HOURS_MESSAGE: str
"""

from zoneinfo import ZoneInfo
from datetime import datetime

# Zona horaria de Argentina/Cordoba — UTC-3, sin horario de verano (DST)
TZ_BERTERO = ZoneInfo("America/Argentina/Cordoba")

# Horario de atencion por dia de la semana (0=Lunes, 6=Domingo)
# Valor: (hora_apertura, hora_cierre) | None si el dia esta cerrado
# La condicion es: hora_apertura <= hora_actual < hora_cierre
HORARIOS: dict[int, tuple[int, int] | None] = {
    0: (9, 18),   # Lunes
    1: (9, 18),   # Martes
    2: (9, 18),   # Miercoles
    3: (9, 18),   # Jueves
    4: (9, 18),   # Viernes
    5: (10, 14),  # Sabado
    6: None,      # Domingo — cerrado
}


def esta_en_horario() -> bool:
    """
    Retorna True si el momento actual esta dentro del horario de atencion de Bertero.
    Usa la zona horaria America/Argentina/Cordoba (UTC-3, sin DST).

    Retorna False si:
    - Es domingo
    - Es fuera del rango de horas del dia correspondiente
    """
    ahora = datetime.now(TZ_BERTERO)
    horario = HORARIOS.get(ahora.weekday())
    if horario is None:
        # Dia cerrado (domingo)
        return False
    hora_apertura, hora_cierre = horario
    return hora_apertura <= ahora.hour < hora_cierre


# Mensaje de respuesta automatica fuera de horario (FU-03)
# Incluye el horario real de Bertero y link al sitio web
AFTER_HOURS_MESSAGE = (
    "Gracias por escribirnos! 🏠\n\n"
    "Nuestro horario de atencion es:\n"
    "- Lunes a Viernes: 9:00 a 18:00 hs\n"
    "- Sabados: 10:00 a 14:00 hs\n\n"
    "Te contactaremos el proximo dia habil. "
    "Si queres ver propiedades disponibles, podes hacerlo en cualquier momento en: "
    "www.inmobiliariabertero.com.ar"
)
