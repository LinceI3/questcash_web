# services/gastos.py
"""Categorías de gasto.

Las del sistema (`usuario_id IS NULL`) son comunes y de solo lectura. Cualquier
otra pertenece a quien la creó y solo él la ve.

Antes la tabla era global y escribible por cualquiera: el nombre llegaba del
cliente sin validar y se servía entero a todos. Un usuario podía hacer que los
demás vieran texto que él eligió, la tabla crecía sin límite, y un nombre de
más de 50 caracteres reventaba la restricción de columna con un 500.
"""
from __future__ import annotations

DEL_SISTEMA = [
    ("Comida",         "#F97316"),
    ("Transporte",     "#2563EB"),
    ("Entretenimiento","#8B5CF6"),
    ("Salud",          "#EC4899"),
    ("Educación",      "#14B8A6"),
    ("Hogar",          "#4ADE80"),
    ("Ropa",           "#FBBF24"),
    ("Otros",          "#D1D5DB"),
]

LARGO_MAXIMO = 50


def sembrar():
    """Crea las categorías del sistema que falten. Idempotente."""
    from models import CategoriaGasto, db

    for nombre, color in DEL_SISTEMA:
        existe = CategoriaGasto.query.filter_by(nombre=nombre, usuario_id=None).first()
        if not existe:
            db.session.add(CategoriaGasto(nombre=nombre, color=color, usuario_id=None))
    db.session.commit()


def normalizar(nombre_crudo: str) -> str:
    nombre = (nombre_crudo or "").strip()
    if not nombre:
        return "Otros"
    return nombre[:LARGO_MAXIMO].capitalize()


def visibles_para(usuario):
    """Las del sistema más las propias. Nunca las de otra persona."""
    from models import CategoriaGasto, db

    return (
        CategoriaGasto.query
        .filter(db.or_(CategoriaGasto.usuario_id.is_(None),
                       CategoriaGasto.usuario_id == usuario.id))
        .order_by(CategoriaGasto.nombre)
        .all()
    )


def obtener_o_crear(nombre_crudo, usuario):
    """Devuelve la categoría a usar, creándola como PROPIA si no existe.

    Se recorta el nombre a la longitud de la columna en vez de dejar que la
    base lance un error: un nombre largo es un dato del usuario, no un fallo
    del servidor.
    """
    from models import CategoriaGasto, db

    nombre = normalizar(nombre_crudo)

    del_sistema = CategoriaGasto.query.filter_by(nombre=nombre, usuario_id=None).first()
    if del_sistema:
        return del_sistema

    propia = CategoriaGasto.query.filter_by(nombre=nombre, usuario_id=usuario.id).first()
    if propia:
        return propia

    nueva = CategoriaGasto(nombre=nombre, usuario_id=usuario.id)
    db.session.add(nueva)
    db.session.commit()
    return nueva
