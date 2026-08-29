# services/rangos.py
"""Escalafón de rangos por puntos acumulados.

Funciones puras: reciben un número y devuelven un diccionario. No tocan la base
de datos ni dependen de Flask.
"""
from __future__ import annotations

RANGOS = [
    {"key": "recluta",      "name": "Recluta del Ahorro",      "min_points": 0,    "color": "#9CA3AF", "accent": "#E5E7EB"},
    {"key": "cabo",         "name": "Cabo Financiero",         "min_points": 250,  "color": "#22C55E", "accent": "#BBF7D0"},
    {"key": "sargento",     "name": "Sargento del Ahorro",     "min_points": 700,  "color": "#3B82F6", "accent": "#BFDBFE"},
    {"key": "veterano",     "name": "Veterano Financiero",     "min_points": 1400, "color": "#8B5CF6", "accent": "#DDD6FE"},
    {"key": "comandante",   "name": "Comandante del Ahorro",   "min_points": 2400, "color": "#DC2626", "accent": "#FECACA"},
    {"key": "elite",        "name": "Élite Financiero",        "min_points": 3800, "color": "#F59E0B", "accent": "#FDE68A"},
    {"key": "leyenda",      "name": "Leyenda Quest",           "min_points": 6000, "color": "#FACC15", "accent": "#FEF08A"},
    {"key": "jefe_maestro", "name": "Jefe Maestro del Ahorro", "min_points": 9000, "color": "#10B981", "accent": "#FBBF24"},
]


def rango_de(puntos_totales) -> dict:
    puntos = int(puntos_totales or 0)
    actual = RANGOS[0]
    for rango in RANGOS:
        if puntos >= rango["min_points"]:
            actual = rango
        else:
            break
    return actual


def siguiente_rango(puntos_totales) -> dict | None:
    puntos = int(puntos_totales or 0)
    for rango in RANGOS:
        if puntos < rango["min_points"]:
            return rango
    return None


def estado(puntos_totales) -> dict:
    """Rango actual, siguiente y progreso entre ambos."""
    puntos = int(puntos_totales or 0)
    actual = rango_de(puntos)
    siguiente = siguiente_rango(puntos)

    piso = int(actual["min_points"])
    if siguiente:
        techo = int(siguiente["min_points"])
        tramo = max(techo - piso, 1)
        avance = puntos - piso
        porcentaje = max(0.0, min((avance / tramo) * 100, 100.0))
        restantes = max(techo - puntos, 0)
    else:
        techo = None
        avance = 0
        porcentaje = 100.0
        restantes = 0

    return {
        "current": actual,
        "next": siguiente,
        "current_name": actual["name"],
        "current_key": actual["key"],
        "current_color": actual["color"],
        "current_accent": actual["accent"],
        "current_min_points": piso,
        "next_name": siguiente["name"] if siguiente else None,
        "next_min_points": techo,
        "points": puntos,
        "points_into_rank": max(avance, 0),
        "points_remaining": restantes,
        "progress_percent": round(porcentaje, 1),
        "is_max_rank": siguiente is None,
    }


def con_nivel(estado_rango: dict) -> dict:
    """Añade `level` y `total_levels` para que un cliente pueda mapear el
    escalafón a un número sin duplicar la tabla."""
    estado_rango = dict(estado_rango)
    idx = next(
        (i for i, r in enumerate(RANGOS) if r["key"] == estado_rango["current_key"]), 0
    )
    estado_rango["level"] = idx + 1
    estado_rango["total_levels"] = len(RANGOS)
    return estado_rango
