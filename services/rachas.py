# services/rachas.py
"""Días consecutivos con aportes.

Dos correcciones respecto a la versión anterior, que vivía como closure en
app.py:

1. **La racha actual se compara con hoy.** Antes se devolvía la longitud del
   último bloque consecutivo sin mirar si ese bloque terminaba hoy o hace meses.
   Un usuario que ahorró siete días seguidos y luego lo dejó seguía viendo
   "racha de 7" para siempre: el mecanismo de retención central del producto
   mentía.

2. **Zona horaria.** Los movimientos se guardan en UTC y la racha se comparaba
   contra `date.today()` del servidor. Para alguien en México (UTC−6), todo
   aporte hecho después de las 18:00 locales contaba como del día siguiente, lo
   que partía rachas legítimas y unía días que no eran consecutivos.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Zona en la que se cuentan los días. QuestCash es un producto mexicano: un día
# de ahorro es un día del calendario del usuario, no del UTC del servidor.
# Configurable porque el día que haya usuarios en otra zona, esto pasa a ser
# una preferencia por cuenta.
ZONA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Mexico_City"))


def _dia_local(momento: datetime) -> date:
    """Fecha del calendario del usuario para un instante dado."""
    if momento.tzinfo is None:
        # Las filas antiguas se guardaron con datetime.utcnow(), sin zona.
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(ZONA).date()


def hoy_local() -> date:
    return datetime.now(ZONA).date()


def calcular(fechas_de_aporte) -> dict:
    """Racha actual y mejor histórica a partir de las fechas de los aportes.

    Recibe fechas en vez de consultar la base: así se puede probar la lógica
    sin montar una aplicación, y quien llama decide cómo obtenerlas.
    """
    dias = sorted({_dia_local(f) for f in fechas_de_aporte if f is not None})
    if not dias:
        return {"racha_actual": 0, "mejor_racha": 0, "ultimo_dia": None}

    mejor = 1
    corrida = 1
    for anterior, actual in zip(dias, dias[1:]):
        corrida = corrida + 1 if (actual - anterior).days == 1 else 1
        mejor = max(mejor, corrida)

    ultimo = dias[-1]
    hoy = hoy_local()

    # Una racha sigue viva si el último aporte fue hoy o ayer. Ayer cuenta
    # porque a las 00:01 nadie ha ahorrado todavía y romperle la racha a
    # alguien por eso sería absurdo.
    viva = (hoy - ultimo).days <= 1

    return {
        "racha_actual": corrida if viva else 0,
        "mejor_racha": mejor,
        "ultimo_dia": ultimo,
    }


def calcular_de_usuario(usuario) -> dict:
    """Igual que `calcular`, leyendo los aportes del usuario de la base."""
    from models import Movimiento

    fechas = [
        f for (f,) in
        Movimiento.query
        .with_entities(Movimiento.fecha)
        .filter(Movimiento.usuario_id == usuario.id, Movimiento.tipo == "aporte")
        .order_by(Movimiento.fecha.asc())
        .all()
    ]
    return calcular(fechas)
