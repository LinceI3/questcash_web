# crypto_utils.py
"""
Cifrado en reposo para QuestCash — Entregable ED, Semana 1.

Qué resuelve
------------
El hashing de contraseñas (`werkzeug.security`) es *irreversible*: sirve para
verificar una contraseña, no para recuperarla. Pero hay datos que la aplicación
SÍ necesita leer de vuelta (el correo del usuario, su nombre, las notas de sus
movimientos). Esos no se pueden hashear: se cifran.

Este módulo implementa cifrado autenticado **AES-256-GCM** a nivel de
aplicación, de modo que lo que queda escrito en el archivo/servidor de base de
datos es texto ilegible aunque alguien obtenga una copia del `.db`, del volumen
de Postgres o de un respaldo.

Formato del valor cifrado
-------------------------
    qc1:<base64url( nonce[12] || ciphertext || tag[16] )>

  * `qc1:` es un prefijo de versión. Permite rotar el algoritmo más adelante
    sin tener que adivinar cómo estaba cifrado cada registro.
  * El nonce es aleatorio y distinto en cada escritura. Por eso cifrar dos
    veces el mismo correo produce dos cadenas distintas — bueno para la
    privacidad, y la razón por la que hace falta el índice ciego de abajo.
  * El tag GCM es de integridad: si alguien altera un byte del registro
    directamente en la base de datos, el descifrado falla en vez de devolver
    basura silenciosamente.

Índice ciego (blind index)
--------------------------
Como el cifrado es aleatorio, `WHERE correo = 'x@y.com'` deja de funcionar.
La solución estándar es guardar, junto al campo cifrado, un HMAC-SHA256
determinista del valor normalizado:

    correo_bi = HMAC-SHA256(clave_indice, correo.strip().lower())

El HMAC es determinista (permite buscar y poner un UNIQUE) pero no reversible,
y al llevar clave propia no se puede atacar por diccionario sin robar también
esa clave. El login busca por `correo_bi`, nunca por el correo en claro.

Claves
------
Se leen del entorno y **nunca** se versionan en el repositorio:

    DATA_ENC_KEY      32 bytes en base64url  (clave AES-256-GCM)
    BLIND_INDEX_KEY   32 bytes en base64url  (clave HMAC del índice ciego)

Para generarlas:

    python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

Si no están definidas, se derivan de `SECRET_KEY` con HKDF-SHA256 y se emite un
aviso: eso permite levantar el proyecto en desarrollo sin configurar nada, pero
NO es aceptable en producción, donde rotar `SECRET_KEY` volvería ilegibles
todos los datos ya cifrados.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import warnings

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Prefijo de versión del sobre criptográfico.
PREFIJO = "qc1:"

# Tamaño del nonce recomendado para GCM (96 bits).
NONCE_BYTES = 12

# Datos autenticados adicionales: no van cifrados, pero quedan cubiertos por el
# tag de integridad. Ata el criptograma a esta aplicación y a esta versión.
_AAD = b"questcash/v1"

_ENC_KEY: bytes | None = None
_BI_KEY: bytes | None = None


# ---------------------------------------------------------------------------
#  Carga de claves
# ---------------------------------------------------------------------------
def _hkdf_sha256(material: bytes, info: bytes, largo: int = 32) -> bytes:
    """HKDF-SHA256 (RFC 5869) con sal vacía. Solo para el modo de desarrollo."""
    prk = hmac.new(b"\x00" * 32, material, hashlib.sha256).digest()
    okm, bloque, contador = b"", b"", 1
    while len(okm) < largo:
        bloque = hmac.new(prk, bloque + info + bytes([contador]), hashlib.sha256).digest()
        okm += bloque
        contador += 1
    return okm[:largo]


def _leer_clave(nombre_var: str, info_derivacion: bytes) -> bytes:
    crudo = os.environ.get(nombre_var)
    if crudo:
        try:
            clave = base64.urlsafe_b64decode(crudo + "=" * (-len(crudo) % 4))
        except Exception as exc:  # pragma: no cover - error de configuración
            raise RuntimeError(f"{nombre_var} no es base64url válido") from exc
        if len(clave) != 32:
            raise RuntimeError(f"{nombre_var} debe ser de 32 bytes (256 bits)")
        return clave

    secreto = os.environ.get("SECRET_KEY")
    if not secreto:
        secreto = "dev_key"
    warnings.warn(
        f"{nombre_var} no está definida: se deriva de SECRET_KEY con HKDF. "
        "Aceptable en desarrollo, NO en producción.",
        RuntimeWarning,
        stacklevel=2,
    )
    return _hkdf_sha256(secreto.encode("utf-8"), info_derivacion)


def _clave_cifrado() -> bytes:
    global _ENC_KEY
    if _ENC_KEY is None:
        _ENC_KEY = _leer_clave("DATA_ENC_KEY", b"questcash-data-encryption")
    return _ENC_KEY


def _clave_indice() -> bytes:
    global _BI_KEY
    if _BI_KEY is None:
        _BI_KEY = _leer_clave("BLIND_INDEX_KEY", b"questcash-blind-index")
    return _BI_KEY


def recargar_claves() -> None:
    """Olvida las claves cacheadas. Útil en pruebas y tras rotar el entorno."""
    global _ENC_KEY, _BI_KEY
    _ENC_KEY = None
    _BI_KEY = None


# ---------------------------------------------------------------------------
#  Cifrado / descifrado
# ---------------------------------------------------------------------------
def esta_cifrado(valor) -> bool:
    return isinstance(valor, str) and valor.startswith(PREFIJO)


def cifrar(texto):
    """Devuelve el sobre `qc1:...`. `None` y `''` pasan tal cual (no hay nada
    que proteger y así los campos opcionales siguen siendo NULL en la BD)."""
    if texto is None or texto == "":
        return texto
    if esta_cifrado(texto):
        return texto  # idempotente: no se cifra dos veces
    nonce = os.urandom(NONCE_BYTES)
    ct = AESGCM(_clave_cifrado()).encrypt(nonce, str(texto).encode("utf-8"), _AAD)
    return PREFIJO + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def descifrar(valor):
    """Inverso de `cifrar`. Si el valor no trae el prefijo se devuelve tal cual:
    eso permite que la aplicación siga funcionando con filas todavía sin migrar."""
    if valor is None or valor == "":
        return valor
    if not esta_cifrado(valor):
        return valor
    crudo = base64.urlsafe_b64decode(valor[len(PREFIJO):] + "=" * (-len(valor[len(PREFIJO):]) % 4))
    nonce, ct = crudo[:NONCE_BYTES], crudo[NONCE_BYTES:]
    return AESGCM(_clave_cifrado()).decrypt(nonce, ct, _AAD).decode("utf-8")


# ---------------------------------------------------------------------------
#  Índice ciego
# ---------------------------------------------------------------------------
def indice_ciego(valor) -> str | None:
    """HMAC-SHA256 determinista sobre el valor normalizado (trim + minúsculas).
    Es lo que se guarda en `usuarios.correo_bi` y por lo que se busca al hacer
    login o al invitar a un colaborador."""
    if valor is None:
        return None
    normalizado = str(valor).strip().lower()
    if not normalizado:
        return None
    return hmac.new(_clave_indice(), normalizado.encode("utf-8"), hashlib.sha256).hexdigest()
