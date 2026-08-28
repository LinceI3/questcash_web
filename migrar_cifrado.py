#!/usr/bin/env python3
# migrar_cifrado.py
"""
Migración única: cifra en reposo los datos que YA estaban guardados en claro.

El `TypeDecorator` de `models.py` solo cifra lo que se escribe a partir de
ahora. Las filas que ya existían siguen en texto plano hasta que se ejecuta
esto. El script:

  1. Respalda la base (solo SQLite; en Postgres se asume `pg_dump` previo).
  2. Agrega la columna `usuarios.correo_bi` si no existe.
  3. Ensancha las columnas afectadas a VARCHAR(512) — necesario en Postgres,
     innecesario en SQLite (tipado dinámico).
  4. Cifra fila por fila los campos sensibles y calcula el índice ciego.
  5. Crea el índice UNIQUE sobre `correo_bi`.

Es idempotente: `cifrar()` detecta el prefijo `qc1:` y no vuelve a cifrar, así
que correrlo dos veces no hace daño.

Uso
---
    export DATA_ENC_KEY=...
    export BLIND_INDEX_KEY=...

    python migrar_cifrado.py                        # SQLite local (questcash.db)
    python migrar_cifrado.py --url postgresql://... # Postgres del contenedor

    python migrar_cifrado.py --dry-run              # solo reporta, no escribe
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime

from crypto_utils import cifrar, esta_cifrado, indice_ciego

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# (tabla, columna) de todo lo que pasa a estar cifrado en reposo.
CAMPOS = [
    ("usuarios", "nombre"),
    ("usuarios", "correo"),
    ("usuarios", "alias"),
    ("movimientos", "nota"),
    ("gastos", "descripcion"),
]


def abrir(url: str):
    """Devuelve (conexión, dialecto, marcador_de_parámetro)."""
    if url.startswith("postgres"):
        import psycopg2  # noqa: F401  (solo si de verdad se usa Postgres)

        return psycopg2.connect(url), "postgres", "%s"
    import sqlite3

    ruta = url.replace("sqlite:///", "")
    return sqlite3.connect(ruta), "sqlite", "?"


def columnas(cur, dialecto: str, tabla: str) -> set[str]:
    if dialecto == "sqlite":
        cur.execute(f"PRAGMA table_info({tabla})")
        return {fila[1] for fila in cur.fetchall()}
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (tabla,),
    )
    return {fila[0] for fila in cur.fetchall()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--url",
        default=os.environ.get(
            "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "questcash.db")
        ),
    )
    ap.add_argument("--dry-run", action="store_true", help="no escribe nada")
    args = ap.parse_args()

    conn, dialecto, ph = abrir(args.url)
    cur = conn.cursor()

    print(f"Base de datos : {args.url}")
    print(f"Dialecto      : {dialecto}")
    print(f"Modo          : {'SIMULACIÓN (no escribe)' if args.dry_run else 'ESCRITURA'}")
    print("-" * 66)

    # ---- 1. Respaldo -----------------------------------------------------
    if dialecto == "sqlite" and not args.dry_run:
        ruta = args.url.replace("sqlite:///", "")
        copia = f"{ruta}.bak-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(ruta, copia)
        print(f"Respaldo       : {copia}")

    # ---- 2. Columna del índice ciego ------------------------------------
    if "correo_bi" not in columnas(cur, dialecto, "usuarios"):
        print("Agregando columna usuarios.correo_bi ...")
        if not args.dry_run:
            cur.execute("ALTER TABLE usuarios ADD COLUMN correo_bi VARCHAR(64)")
    else:
        print("usuarios.correo_bi ya existe.")

    # ---- 3. Ensanchar columnas (solo Postgres) --------------------------
    if dialecto == "postgres" and not args.dry_run:
        anchos = {"nota": 2048, "descripcion": 1024}
        for tabla, col in CAMPOS:
            cur.execute(
                f"ALTER TABLE {tabla} ALTER COLUMN {col} TYPE VARCHAR({anchos.get(col, 512)})"
            )
        print("Columnas ensanchadas a VARCHAR(512+).")

    # ---- 4. Cifrado fila por fila ---------------------------------------
    total_cifrados = 0
    for tabla, col in CAMPOS:
        cur.execute(f"SELECT id, {col} FROM {tabla}")
        filas = cur.fetchall()
        pendientes = [(i, v) for i, v in filas if v and not esta_cifrado(v)]
        for id_, valor in pendientes:
            if not args.dry_run:
                cur.execute(
                    f"UPDATE {tabla} SET {col} = {ph} WHERE id = {ph}", (cifrar(valor), id_)
                )
        total_cifrados += len(pendientes)
        print(f"  {tabla}.{col:<12} {len(pendientes):>4} de {len(filas):>4} filas cifradas")

    # ---- 5. Índice ciego de los correos ---------------------------------
    # Se recalcula desde el valor en claro que se acaba de leer, por eso este
    # paso va después del cifrado pero usa los datos originales en memoria.
    cur.execute("SELECT id, correo FROM usuarios")
    correos = cur.fetchall()
    sin_indice = 0
    for id_, valor in correos:
        from crypto_utils import descifrar

        claro = descifrar(valor)
        bi = indice_ciego(claro)
        if not args.dry_run:
            cur.execute(f"UPDATE usuarios SET correo_bi = {ph} WHERE id = {ph}", (bi, id_))
        sin_indice += 1
    print(f"  usuarios.correo_bi {sin_indice:>3} índices ciegos calculados")

    if not args.dry_run:
        try:
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_usuarios_correo_bi ON usuarios (correo_bi)"
            )
            print("Índice UNIQUE ux_usuarios_correo_bi creado.")
        except Exception as exc:  # correos duplicados preexistentes
            print(f"  ! No se pudo crear el índice UNIQUE: {exc}")
        conn.commit()

    conn.close()
    print("-" * 66)
    print(f"Listo. {total_cifrados} valores cifrados.")
    if args.dry_run:
        print("(Simulación: no se escribió nada.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
