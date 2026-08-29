#!/usr/bin/env python3
# docs/semanaED1/evidencia.py
"""
Evidencia reproducible del Entregable ED — Semana 1.

Ejercita, contra la base de datos real, exactamente las mismas primitivas que
usa QuestCash en producción:

  * `password_hashing.hashear_password` / `verificar_password`
    — lo que llaman `app.py:register` / `app.py:login` y sus equivalentes en
      `api.py`.
  * `crypto_utils.cifrar` / `descifrar` / `indice_ciego`
    — lo que aplica el `TypeDecorator` de `models.py` en cada escritura.

No se conecta por HTTP a propósito: así la prueba corre sin levantar el
servidor y la salida es determinista salvo por las sales y los nonces
aleatorios. Para la evidencia por API (equivalente a Postman) está
`pruebas_api.sh`.

Uso
---
    export DATA_ENC_KEY=...  BLIND_INDEX_KEY=...
    python docs/semanaED1/evidencia.py                # sobre questcash.db
    python docs/semanaED1/evidencia.py --db /ruta.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RAIZ)

from crypto_utils import cifrar, descifrar, indice_ciego  # noqa: E402
from password_hashing import (  # noqa: E402
    METODO_HASH,
    describir,
    hashear_password,
    necesita_rehash,
    verificar_password,
)

LINEA = "=" * 72
PASSWORD = "QuestCash2026!"


def titulo(n, texto):
    print(f"\n{LINEA}\n  PRUEBA {n} — {texto}\n{LINEA}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(RAIZ, "questcash.db"))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()

    correo = f"evidencia_{int(datetime.now().timestamp())}@gmail.com"
    nombre = "Usuario De Evidencia"

    # -----------------------------------------------------------------
    titulo(1, "ALTA DE USUARIO: la contraseña nunca se guarda en claro")
    print(f"Contraseña en claro que se envía : {PASSWORD!r}")
    print(f"Política de hashing vigente      : {METODO_HASH}")

    t0 = time.perf_counter()
    hash_pw = hashear_password(PASSWORD)
    ms = (time.perf_counter() - t0) * 1000

    print(f"Lo que devuelve el hasher        : {hash_pw}")
    print()
    d = describir(hash_pw)
    print(f"  algoritmo          : {d['algoritmo']}   (KDF memory-hard, RFC 7914)")
    print(f"  coste N            : {d['N']} = 2^15  ->  {d['memoria_mib']} MiB de RAM por hash")
    print(f"  tamaño de bloque r : {d['r']}")
    print(f"  paralelismo p      : {d['p']}   (combinación recomendada por OWASP para N=2^15)")
    print(f"  sal aleatoria      : {d['sal']}   <- distinta para cada usuario")
    print(f"  derivación         : {d['derivado_bits']} bits")
    print(f"  longitud total     : {d['longitud_total']} caracteres")
    print(f"  tiempo de cálculo  : {ms:.0f} ms   <- lo que paga un atacante por CADA intento")

    cur.execute(
        "INSERT INTO usuarios (nombre, correo, correo_bi, password_hash, fecha_registro, "
        "puntos_totales, notif_ia, notif_fechas, notif_progreso) "
        "VALUES (?, ?, ?, ?, ?, 0, 1, 1, 1)",
        (cifrar(nombre), cifrar(correo), indice_ciego(correo), hash_pw, datetime.utcnow()),
    )
    conn.commit()
    nuevo_id = cur.lastrowid
    print(f"\nUsuario insertado con id = {nuevo_id}")

    # -----------------------------------------------------------------
    titulo(2, "QUERY DIRECTA A LA BASE: qué quedó escrito en disco")
    cur.execute(
        "SELECT nombre, correo, correo_bi, password_hash FROM usuarios WHERE id = ?",
        (nuevo_id,),
    )
    fila_nombre, fila_correo, fila_bi, fila_hash = cur.fetchone()
    print(f"nombre        = {fila_nombre}")
    print(f"correo        = {fila_correo}")
    print(f"correo_bi     = {fila_bi}")
    print(f"password_hash = {fila_hash}")
    print()
    todo = " ".join(map(str, (fila_nombre, fila_correo, fila_bi, fila_hash)))
    print(f"¿aparece la contraseña {PASSWORD!r} en algún campo?   ", end="")
    print("NO" if PASSWORD not in todo else "SÍ  (¡FALLA!)")
    print(f"¿aparece el correo en claro?   ", end="")
    print("NO" if correo not in str(fila_correo) else "SÍ  (¡FALLA!)")
    print(f"¿aparece el nombre {nombre!r} en claro?   ", end="")
    print("NO" if nombre not in str(fila_nombre) else "SÍ  (¡FALLA!)")

    # -----------------------------------------------------------------
    titulo(3, "LOGIN CORRECTO: se verifica sin revertir el hash")
    bi = indice_ciego(correo)
    print("El correo está cifrado con un nonce distinto en cada escritura, así que")
    print("no se puede hacer WHERE correo = '...'. El login busca por índice ciego:")
    print(f"  HMAC-SHA256(clave, correo) = {bi}")
    cur.execute("SELECT id, nombre, password_hash FROM usuarios WHERE correo_bi = ?", (bi,))
    encontrado = cur.fetchone()
    print(f"\nFila encontrada                 : id = {encontrado[0]}")
    print(f"Nombre descifrado en memoria    : {descifrar(encontrado[1])!r}")
    print(f"verificar_password(hash, '{PASSWORD}') -> {verificar_password(encontrado[2], PASSWORD)}")

    # -----------------------------------------------------------------
    titulo(4, "LOGIN INCORRECTO: variaciones mínimas no pasan")
    for intento in (PASSWORD.lower(), PASSWORD + " ", "QuestCash2026", "123456", hash_pw):
        etiqueta = "<el propio hash robado de la BD>" if intento == hash_pw else repr(intento)
        print(f"  verificar_password(hash, {etiqueta}) -> {verificar_password(encontrado[2], intento)}")

    # -----------------------------------------------------------------
    titulo(5, "SAL ALEATORIA: el mismo password produce hashes distintos")
    otro = hashear_password(PASSWORD)
    print(f"  1) {hash_pw}")
    print(f"  2) {otro}")
    print(f"  ¿son iguales? {hash_pw == otro}")
    print()
    print("  Consecuencia: dos usuarios con la MISMA contraseña tienen hashes distintos.")
    print("  Una tabla arcoíris precomputada no sirve, y ver la base de datos no")
    print("  revela qué cuentas comparten contraseña.")

    # -----------------------------------------------------------------
    titulo(6, "MIGRACIÓN DE PARÁMETROS: los hashes viejos siguen sirviendo")
    from werkzeug.security import generate_password_hash

    viejo = generate_password_hash(PASSWORD, method="scrypt:32768:8:1")
    print(f"Hash con la configuración anterior (p=1):\n  {viejo[:70]}...")
    print(f"  verificar_password(...) -> {verificar_password(viejo, PASSWORD)}   (sigue validando)")
    print(f"  necesita_rehash(...)    -> {necesita_rehash(viejo)}   (se regenera al siguiente login)")
    print(f"  necesita_rehash(hash actual) -> {necesita_rehash(hash_pw)}")

    # -----------------------------------------------------------------
    titulo(7, "CIFRADO EN REPOSO: ida y vuelta + detección de manipulación")
    nota = "Ahorro para la consulta con el cardiólogo"
    sobre = cifrar(nota)
    print(f"Texto original : {nota!r}")
    print(f"Cifrado        : {sobre}")
    print(f"Descifrado     : {descifrar(sobre)!r}")
    print(f"¿coincide?     : {descifrar(sobre) == nota}")
    print()
    alterado = sobre[:-6] + ("A" * 4) + sobre[-2:]
    print("Ahora se altera un byte del criptograma, como haría alguien con acceso")
    print("de escritura al archivo de la base de datos:")
    try:
        descifrar(alterado)
        print("  !! Se descifró: NO hay protección de integridad (esto sería un fallo)")
    except Exception as exc:
        print(f"  El descifrado FALLA -> {type(exc).__name__}: el tag GCM detecta la manipulación")

    # -----------------------------------------------------------------
    titulo(8, "LIMPIEZA")
    cur.execute("DELETE FROM usuarios WHERE id = ?", (nuevo_id,))
    conn.commit()
    print(f"Usuario de prueba id = {nuevo_id} eliminado.")
    conn.close()
    print(f"\n{LINEA}\n  FIN DE LA EVIDENCIA\n{LINEA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
