#!/usr/bin/env python3
"""Prepara la base de datos antes de levantar la aplicación.

Corre como paso explícito del despliegue (lo llama wait-for-db.sh antes de
`exec gunicorn`), NO al importar app.py. Esa es la diferencia con lo que había
antes: `db.create_all()` se ejecutaba en cada arranque de cada worker, sin
historial, sin reversión y compitiendo entre procesos por ejecutar DDL.

Hace tres cosas, en orden:

  1. ADOPCIÓN. Si la base ya tiene tablas de QuestCash pero no tiene
     `alembic_version`, es una base creada por el viejo `create_all()`. No se
     puede aplicarle la migración inicial —fallaría con "la tabla ya existe"—
     así que se marca (`stamp`) en la primera revisión, declarando que ya está
     a ese nivel. Esto ocurre una sola vez por base.

  2. MIGRACIÓN. `upgrade head` aplica lo que falte. En una base vacía crea todo
     desde cero; en una ya adoptada aplica solo las revisiones nuevas.

  3. SEMILLAS. Las insignias base. Es datos, no esquema, y es idempotente.

Uso:
    python scripts/preparar_bd.py            # aplica
    python scripts/preparar_bd.py --revisar  # solo informa, no escribe
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from flask_migrate import stamp, upgrade  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app import app, seed_insignias  # noqa: E402
from models import db  # noqa: E402

# Una tabla que solo existe si QuestCash ya creó su esquema alguna vez.
TABLA_TESTIGO = "usuarios"


def revision_inicial() -> str | None:
    """La primera revisión de la cadena (la que no tiene padre)."""
    directorio = ScriptDirectory.from_config(
        __import__("flask_migrate").current_app.extensions["migrate"].migrate.get_config()
    )
    for revision in directorio.walk_revisions():
        if revision.down_revision is None:
            return revision.revision
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revisar", action="store_true", help="informa sin escribir")
    args = ap.parse_args()

    with app.app_context():
        inspector = inspect(db.engine)
        tablas = set(inspector.get_table_names())

        tiene_esquema = TABLA_TESTIGO in tablas

        # No basta con que exista la tabla `alembic_version`: un
        # `flask db migrate` que no encontró cambios la crea VACÍA, sin
        # ninguna revisión dentro. Una base así sigue estando sin adoptar, y
        # tratarla como adoptada hace que `upgrade` intente crear tablas que
        # ya existen. Lo que decide es si hay una revisión registrada.
        with db.engine.connect() as conexion:
            revision_actual = MigrationContext.configure(conexion).get_current_revision()
        tiene_alembic = revision_actual is not None

        print(f"Base de datos : {db.engine.url.render_as_string(hide_password=True)}")
        print(f"Tablas        : {len(tablas)}")
        print(f"Bajo Alembic  : {revision_actual if tiene_alembic else 'no'}")

        if args.revisar:
            if tiene_esquema and not tiene_alembic:
                print("Acción        : adoptar (stamp) y luego migrar")
            elif not tiene_esquema:
                print("Acción        : crear el esquema desde cero")
            else:
                print("Acción        : aplicar migraciones pendientes")
            return 0

        # ---- 1. Adopción de una base anterior a Alembic --------------------
        if tiene_esquema and not tiene_alembic:
            inicial = revision_inicial()
            if inicial is None:
                print("ERROR: no hay ninguna revisión inicial en migrations/versions/")
                return 1
            print(f"Adoptando     : la base ya existía; se marca en {inicial}")
            stamp(revision=inicial)

        # ---- 2. Migraciones ------------------------------------------------
        print("Migrando      : upgrade head")
        upgrade()

        # ---- 3. Semillas ---------------------------------------------------
        print("Sembrando     : insignias base")
        seed_insignias()

        print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
