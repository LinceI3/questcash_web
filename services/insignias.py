# services/insignias.py
"""Catálogo de insignias y las reglas que las otorgan.

La concesión no sabe nada de Flask. Los efectos de interfaz —el aviso emergente
de la web— entran por el callback `al_otorgar`, para que la misma función sirva
a la vista HTML y a la API sin que ninguna arrastre las dependencias de la otra.
"""
from __future__ import annotations

from datetime import date

CATALOGO = [
    {"codigo": "PRIMER_AHORRO", "nombre": "Primer ahorro registrado",
     "descripcion": "Registraste tu primer aporte de ahorro.",
     "rareza": "común", "icono": "primer_ahorro.png"},
    {"codigo": "PRIMERA_META", "nombre": "Primera meta creada",
     "descripcion": "Creaste tu primera meta en QuestCash.",
     "rareza": "rara", "icono": "Primera_meta.png"},
    {"codigo": "PRIMER_RETO", "nombre": "Primer reto completado",
     "descripcion": "Completaste tu primer reto de ahorro.",
     "rareza": "épica", "icono": "primer_reto.png"},
    {"codigo": "AHORRO_1000", "nombre": "Has ahorrado $1,000 MXN",
     "descripcion": "Alcanzaste un total acumulado de $1,000 MXN.",
     "rareza": "legendaria", "icono": "Ahorro_1000.png"},
    {"codigo": "META_A_TIEMPO", "nombre": "Meta cumplida a tiempo",
     "descripcion": "Completaste un reto antes o justo en la fecha límite.",
     "rareza": "mítica", "icono": "Meta_tiempo.png"},
]

COLOR_POR_RAREZA = {
    "común": "#22C55E",
    "rara": "#2563EB",
    "épica": "#9333EA",
    "legendaria": "#F59E0B",
    "mítica": "#EC4899",
}

UMBRAL_AHORRO_TOTAL = 1000


def sembrar():
    """Crea las insignias del catálogo que falten. Idempotente."""
    from models import Insignia, db

    for datos in CATALOGO:
        if not Insignia.query.filter_by(codigo=datos["codigo"]).first():
            db.session.add(Insignia(**datos))
    db.session.commit()


def otorgar(codigo, usuario, events=None, al_otorgar=None, crear_notificacion=None):
    """Da una insignia si el usuario no la tenía. Sin commit: decide quien llama."""
    from models import Insignia, UsuarioInsignia, db

    insignia = Insignia.query.filter_by(codigo=codigo).first()
    if insignia is None:
        return False

    ya_la_tiene = UsuarioInsignia.query.filter_by(
        usuario_id=usuario.id, insignia_id=insignia.id
    ).first()
    if ya_la_tiene:
        return False

    db.session.add(UsuarioInsignia(usuario_id=usuario.id, insignia_id=insignia.id))

    if al_otorgar is not None:
        al_otorgar(insignia)

    if crear_notificacion is not None:
        crear_notificacion(
            usuario,
            tipo="insignia_nueva",
            titulo="Nueva insignia",
            mensaje=f"Desbloqueaste la insignia {insignia.nombre}.",
            icono="shield-checkmark",
            color=COLOR_POR_RAREZA.get((insignia.rareza or "").lower(), "#FBBF24"),
        )

    if events is not None:
        events.append({
            "type": "insignia",
            "codigo": insignia.codigo,
            "nombre": insignia.nombre,
            "descripcion": insignia.descripcion,
            "rareza": insignia.rareza,
            "icono": insignia.icono,
        })
    return True


def revisar_evento(usuario, evento, quest=None, events=None, **cb):
    """Otorga las insignias que correspondan a un evento del usuario."""
    from models import Movimiento, Quest, db

    dar = lambda codigo: otorgar(codigo, usuario, events=events, **cb)

    if evento == "primer_movimiento":
        aportes = Movimiento.query.filter_by(usuario_id=usuario.id, tipo="aporte").count()
        if aportes == 1:
            dar("PRIMER_AHORRO")

        total = (
            db.session.query(db.func.sum(Movimiento.monto))
            .filter_by(usuario_id=usuario.id, tipo="aporte")
            .scalar() or 0
        )
        if float(total) >= UMBRAL_AHORRO_TOTAL:
            dar("AHORRO_1000")

    elif evento == "primer_reto_creado":
        if Quest.query.filter_by(usuario_id=usuario.id).count() == 1:
            dar("PRIMERA_META")

    elif evento == "reto_completado" and quest is not None:
        dar("PRIMER_RETO")
        if (quest.fecha_limite
                and quest.monto_actual >= quest.monto_objetivo
                and date.today() <= quest.fecha_limite):
            dar("META_A_TIEMPO")
