# services/puntos.py
"""Dificultad de una meta y puntos que otorga. Funciones puras."""
from __future__ import annotations

import math
from datetime import date


def dificultad(monto_objetivo, fecha_limite, fecha_creacion=None) -> str:
    """Qué tan exigente es la meta, medido en ahorro diario necesario."""
    fecha_creacion = fecha_creacion or date.today()
    if not monto_objetivo or monto_objetivo <= 0:
        return "desconocida"

    dias = max((fecha_limite - fecha_creacion).days, 1)
    por_dia = float(monto_objetivo) / dias

    if por_dia < 50:
        return "fácil"
    if por_dia < 150:
        return "media"
    return "difícil"


def puntos_de_meta(monto_objetivo, fecha_limite, dificultad_txt, tipo, fecha_creacion=None) -> int:
    """Recompensa base de una meta.

    Cuatro componentes: cuánto se ahorra (logarítmico, para que una meta diez
    veces mayor no dé diez veces los puntos), en cuánto tiempo, qué tan
    exigente es, y si es compartida.
    """
    fecha_creacion = fecha_creacion or date.today()
    if not monto_objetivo or monto_objetivo <= 0:
        return 0

    dias = max((fecha_limite - fecha_creacion).days, 1)

    score_monto = math.log10(max(float(monto_objetivo), 1)) * 25
    score_plazo = min((30 / dias) * 30, 60)

    texto = (dificultad_txt or "").lower()
    if "dificil" in texto or "difícil" in texto:
        score_riesgo = 20
    elif "media" in texto:
        score_riesgo = 10
    else:
        score_riesgo = 0

    score_extra = 15 if tipo == "colaborativo" else 0

    return max(5, int(round(score_monto + score_plazo + score_riesgo + score_extra)))
