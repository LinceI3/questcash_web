# rate_limit.py
"""Control de intentos de inicio de sesión, con estado compartido entre procesos.

El problema que resuelve
------------------------
El contador vivía en un diccionario de módulo (`intentos_login = {}`) dentro de
app.py. Eso tiene dos fallos, y ambos importan en producción:

  1. No se comparte. Cada worker de gunicorn tiene el suyo. Con
     `--workers 2` un atacante dispone del doble de intentos, y con el
     balanceador de dos instancias del laboratorio, del cuádruple. Bastaba con
     reciclar la conexión para repartir los intentos entre procesos.

  2. No se limpia nunca. Cada par correo+IP probado dejaba una entrada
     permanente en memoria: probar un millón de correos inventados hace crecer
     el proceso sin límite. Es una denegación de servicio trivial de provocar.

Aquí el estado vive en Redis, que lo comparten todos los procesos, y cada clave
lleva expiración: las entradas se borran solas.

Modo de desarrollo
------------------
Si no hay REDIS_URL se usa un diccionario en memoria, igual que antes, con un
aviso. Es cómodo para trabajar en local sin levantar Redis. En staging y
production config.py exige la variable, así que el modo degradado no puede
colarse en un despliegue real.
"""
from __future__ import annotations

import hashlib
import os
import time
import warnings

MAX_INTENTOS = int(os.environ.get("LOGIN_MAX_INTENTOS", "5"))
BLOQUEO_SEGUNDOS = int(os.environ.get("LOGIN_BLOQUEO_SEGUNDOS", str(5 * 60)))

# Cuánto se recuerda un intento fallido suelto. Si alguien falla una vez y no
# vuelve en 15 minutos, el contador se olvida solo.
VENTANA_SEGUNDOS = int(os.environ.get("LOGIN_VENTANA_SEGUNDOS", str(15 * 60)))

_PREFIJO = "questcash:login:"


class _AlmacenMemoria:
    """Respaldo para desarrollo. Mismo comportamiento, sin compartir nada."""

    def __init__(self):
        self._datos = {}

    def _limpiar(self):
        ahora = time.time()
        for clave, (_, expira) in list(self._datos.items()):
            if expira <= ahora:
                self._datos.pop(clave, None)

    def leer(self, clave):
        self._limpiar()
        valor = self._datos.get(clave)
        return valor[0] if valor else None

    def incrementar(self, clave, ttl):
        self._limpiar()
        actual = self.leer(clave) or 0
        self._datos[clave] = (actual + 1, time.time() + ttl)
        return actual + 1

    def fijar(self, clave, valor, ttl):
        self._datos[clave] = (valor, time.time() + ttl)

    def borrar(self, *claves):
        for clave in claves:
            self._datos.pop(clave, None)

    def ttl(self, clave):
        self._limpiar()
        valor = self._datos.get(clave)
        return max(int(valor[1] - time.time()), 0) if valor else 0


class _AlmacenRedis:
    def __init__(self, cliente):
        self._r = cliente

    def leer(self, clave):
        valor = self._r.get(clave)
        return int(valor) if valor is not None else None

    def incrementar(self, clave, ttl):
        tuberia = self._r.pipeline()
        tuberia.incr(clave)
        # NX: solo fija la expiración la primera vez, para que la ventana
        # cuente desde el primer fallo y no se renueve con cada intento.
        tuberia.expire(clave, ttl, nx=True)
        return int(tuberia.execute()[0])

    def fijar(self, clave, valor, ttl):
        self._r.setex(clave, ttl, valor)

    def borrar(self, *claves):
        if claves:
            self._r.delete(*claves)

    def ttl(self, clave):
        return max(int(self._r.ttl(clave) or 0), 0)


def _crear_almacen():
    url = os.environ.get("REDIS_URL")
    if not url:
        warnings.warn(
            "REDIS_URL no está definida: el control de intentos de inicio de "
            "sesión usa memoria del proceso y NO se comparte entre workers. "
            "Aceptable en desarrollo, no en producción.",
            RuntimeWarning,
            stacklevel=2,
        )
        return _AlmacenMemoria()

    import redis  # import perezoso: solo hace falta si de verdad se usa Redis

    cliente = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
    cliente.ping()   # falla ruidosamente al arrancar si Redis no responde
    return _AlmacenRedis(cliente)


_almacen = None


def almacen():
    global _almacen
    if _almacen is None:
        _almacen = _crear_almacen()
    return _almacen


def _claves(correo, ip):
    """Claves de Redis para este par correo+IP.

    La identidad va HASHEADA, no en claro. Un correo es un dato personal y en
    este proyecto viaja cifrado hasta la base de datos: dejarlo legible en las
    claves de Redis abriría por detrás lo que se cerró por delante — cualquiera
    con acceso al redis-cli, o a un volcado de memoria, leería la lista de
    quién ha intentado entrar y desde qué dirección.

    Basta SHA-256 sin clave: solo hace falta que sea determinista para agrupar
    los intentos del mismo par, y las entradas se borran solas al expirar.
    """
    identidad = f"{(correo or '').strip().lower()}|{ip or 'desconocida'}"
    digest = hashlib.sha256(identidad.encode("utf-8")).hexdigest()[:32]
    return f"{_PREFIJO}intentos:{digest}", f"{_PREFIJO}bloqueo:{digest}"


def segundos_de_bloqueo(correo, ip):
    """0 si puede intentar; si no, cuántos segundos le quedan de bloqueo."""
    _, clave_bloqueo = _claves(correo, ip)
    return almacen().ttl(clave_bloqueo) if almacen().leer(clave_bloqueo) else 0


def registrar_fallo(correo, ip):
    """Cuenta un intento fallido. Devuelve (intentos_restantes, segundos_bloqueo)."""
    clave_intentos, clave_bloqueo = _claves(correo, ip)
    intentos = almacen().incrementar(clave_intentos, VENTANA_SEGUNDOS)

    if intentos >= MAX_INTENTOS:
        almacen().fijar(clave_bloqueo, 1, BLOQUEO_SEGUNDOS)
        almacen().borrar(clave_intentos)
        return 0, BLOQUEO_SEGUNDOS

    return max(MAX_INTENTOS - intentos, 0), 0


def registrar_exito(correo, ip):
    """Inicio de sesión correcto: se olvida todo lo anterior."""
    almacen().borrar(*_claves(correo, ip))


def reiniciar():
    """Olvida el almacén cacheado. Solo para pruebas."""
    global _almacen
    _almacen = None
