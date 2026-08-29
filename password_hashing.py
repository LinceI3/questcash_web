# password_hashing.py
"""
Política de hashing de contraseñas de QuestCash.

Antes este proyecto llamaba directamente a `generate_password_hash(password)`
desde `app.py` y desde `api.py`, aceptando los parámetros por omisión de
Werkzeug. Eso funciona, pero deja la política de seguridad repartida en dos
archivos y sin forma de endurecerla en un solo lugar. Este módulo la
centraliza.

Algoritmo
---------
**scrypt** (RFC 7914), una función de derivación de clave *memory-hard*: para
calcular un hash hay que reservar decenas de megabytes de RAM, no solo gastar
ciclos de CPU. Eso es justamente lo que encarece un ataque con GPU o ASIC,
donde el cuello de botella es la memoria por núcleo y no la aritmética.

Parámetros
----------
    scrypt:32768:8:3   ->   N=2^15, r=8, p=3

Corresponde exactamente a una de las combinaciones que recomienda la *OWASP
Password Storage Cheat Sheet* para scrypt (N=2^15 / 32 MiB, r=8, p=3). Se
eligió la variante de 32 MiB en vez de la de 128 MiB porque el servicio
público corre en Render con memoria limitada: subir N dispararía el consumo de
RAM por cada inicio de sesión, mientras que subir p multiplica el trabajo de
CPU sin multiplicar la memoria.

El valor por omisión de Werkzeug es `scrypt:32768:8:1` — misma memoria pero un
tercio del trabajo. Aquí se sube deliberadamente a p=3 para alinearse con la
recomendación de OWASP.

Migración transparente
----------------------
`check_password_hash` lee los parámetros del propio hash almacenado, así que
las contraseñas guardadas con la configuración anterior siguen verificándose
sin problema. `necesita_rehash()` detecta esos hashes viejos y permite
regenerarlos en el siguiente inicio de sesión correcto, cuando la contraseña
en claro está disponible por única vez. Nadie tiene que restablecer nada.
"""

from __future__ import annotations

import os

from werkzeug.security import check_password_hash, generate_password_hash

# N=2^15 (32 MiB) : r=8 : p=3  — combinación recomendada por OWASP.
METODO_HASH = os.environ.get("PASSWORD_HASH_METHOD", "scrypt:32768:8:3")


def hashear_password(password: str) -> str:
    """Único punto del proyecto donde se crea un hash de contraseña."""
    return generate_password_hash(password, method=METODO_HASH)


def verificar_password(hash_guardado: str, password: str) -> bool:
    """Comparación en tiempo constante contra el hash almacenado.

    Nunca se descifra nada: se vuelve a derivar el hash con la sal y los
    parámetros que vienen dentro del propio `hash_guardado` y se comparan los
    resultados.
    """
    if not hash_guardado or password is None:
        return False
    return check_password_hash(hash_guardado, password)


def necesita_rehash(hash_guardado: str) -> bool:
    """True si el hash se generó con una configuración anterior a la vigente."""
    if not hash_guardado:
        return True
    return not hash_guardado.startswith(METODO_HASH + "$")


def describir(hash_guardado: str) -> dict:
    """Desglosa un hash almacenado. Se usa en la evidencia del reporte para
    mostrar que lo guardado son parámetros + sal + derivación, y no la
    contraseña."""
    algoritmo, sal, derivado = hash_guardado.split("$", 2)
    partes = algoritmo.split(":")
    return {
        "algoritmo": partes[0],
        "N": int(partes[1]) if len(partes) > 1 else None,
        "r": int(partes[2]) if len(partes) > 2 else None,
        "p": int(partes[3]) if len(partes) > 3 else None,
        "memoria_mib": (128 * int(partes[1]) * int(partes[2])) // (1024 * 1024)
        if len(partes) > 2
        else None,
        "sal": sal,
        "derivado_bits": len(derivado) * 4,
        "longitud_total": len(hash_guardado),
    }
