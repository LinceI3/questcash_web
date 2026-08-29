# config.py
"""Configuración de QuestCash, separada por entorno.

Antes esto era una sola clase `Config` con valores por omisión pensados para
desarrollo: SECRET_KEY caía a "dev_key", la cookie de sesión no llevaba marca
Secure y la base de datos caía a un SQLite local. Eso está bien en la máquina
del desarrollador y es peligroso en producción, donde un despliegue al que se
le olvidó una variable arrancaba igual, en silencio, con el valor inseguro.

Ahora el entorno se declara y manda:

    ENTORNO=development   (por omisión)  — valores cómodos, avisos tolerados
    ENTORNO=testing                      — base efímera, sin estado compartido
    ENTORNO=staging                      — como producción, con datos sintéticos
    ENTORNO=production                   — exige TODO; si falta algo, no arranca

La regla que evita el accidente clásico: en staging y production, la aplicación
falla al importarse si falta un secreto o si alguien dejó el modo debug
activado. Es preferible un contenedor que no levanta a uno que sirve datos
financieros con la clave por omisión.
"""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

ENTORNO = os.environ.get("ENTORNO", "development").strip().lower()
ENTORNOS_VALIDOS = {"development", "testing", "staging", "production"}
if ENTORNO not in ENTORNOS_VALIDOS:
    raise RuntimeError(
        f"ENTORNO='{ENTORNO}' no es válido. Usa uno de: {', '.join(sorted(ENTORNOS_VALIDOS))}"
    )

# En estos entornos no se tolera ningún valor por omisión inseguro.
ES_DESPLIEGUE_REAL = ENTORNO in {"staging", "production"}

# Valores que delatan una plantilla sin rellenar.
VALORES_PROHIBIDOS = {"dev_key", "cambiame", "CAMBIAME", "1234", "changeme", "PURGADO-ROTAR-EN-RENDER"}


def _exigido(nombre, por_omision=None):
    """Lee una variable de entorno. En staging/production no acepta que falte
    ni que traiga un valor de plantilla."""
    valor = os.environ.get(nombre, por_omision)

    if not ES_DESPLIEGUE_REAL:
        return valor

    if not valor:
        raise RuntimeError(
            f"{nombre} no está definida y ENTORNO={ENTORNO}. "
            f"Defínela en el gestor de secretos antes de desplegar."
        )
    if valor in VALORES_PROHIBIDOS:
        raise RuntimeError(
            f"{nombre} tiene un valor de plantilla ({valor!r}) y ENTORNO={ENTORNO}. "
            f"Genera uno real: python -c \"import os,base64;"
            f"print(base64.urlsafe_b64encode(os.urandom(32)).decode())\""
        )
    return valor


def _booleano(nombre, por_omision=False):
    return os.environ.get(nombre, str(por_omision)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    ENTORNO = ENTORNO

    # --- Secretos -----------------------------------------------------------
    SECRET_KEY = _exigido("SECRET_KEY", None if ES_DESPLIEGUE_REAL else "dev_key")
    JWT_SECRET_KEY = _exigido("JWT_SECRET_KEY", None if ES_DESPLIEGUE_REAL else SECRET_KEY)
    # Access corto y refresh largo. El access no se puede revocar —se valida
    # solo por firma— así que su vida útil es la ventana de exposición de un
    # token robado: 60 minutos en vez de los 30 días de antes.
    JWT_ACCESS_MINUTOS = int(os.environ.get("JWT_ACCESS_MINUTOS", 60))
    JWT_REFRESH_DIAS = int(os.environ.get("JWT_REFRESH_DIAS", 30))

    # --- Base de datos ------------------------------------------------------
    # En desarrollo se tolera el SQLite local; en un despliegue real, no: correr
    # producción sobre un archivo del contenedor significa perder los datos en
    # cada redespliegue.
    SQLALCHEMY_DATABASE_URI = _exigido(
        "DATABASE_URL",
        None if ES_DESPLIEGUE_REAL else "sqlite:///" + os.path.join(BASE_DIR, "questcash.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Seguridad ----------------------------------------------------------
    WTF_CSRF_ENABLED = True

    SESSION_COOKIE_HTTPONLY = True
    # Secure obliga a que la cookie viaje solo por HTTPS. En desarrollo se
    # trabaja sobre http://localhost, donde activarlo impediría iniciar sesión.
    SESSION_COOKIE_SECURE = _booleano("SESSION_COOKIE_SECURE", ES_DESPLIEGUE_REAL)
    SESSION_COOKIE_SAMESITE = "Lax"

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SESSION_REFRESH_EACH_REQUEST = True
    SESSION_PROTECTION = "strong"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)

    # No filtrar trazas al cliente.
    PROPAGATE_EXCEPTIONS = False

    # --- Subida de archivos (foto de perfil) --------------------------------
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "profiles")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}


# --- Comprobaciones que solo tienen sentido en un despliegue real -----------
if ES_DESPLIEGUE_REAL:
    if _booleano("FLASK_DEBUG") or _booleano("DEBUG"):
        raise RuntimeError(
            f"El modo debug está activado y ENTORNO={ENTORNO}. Con debug, cualquier "
            "excepción publica una consola que ejecuta código en el servidor."
        )

    # Sin estas dos, crypto_utils deriva las claves de SECRET_KEY: rotar
    # SECRET_KEY dejaría ilegibles todos los datos cifrados.
    for clave in ("DATA_ENC_KEY", "BLIND_INDEX_KEY"):
        _exigido(clave)

    # Sin proveedor de correo no hay recuperación de contraseña, y sin
    # recuperación un usuario que olvida la suya pierde la cuenta. En
    # desarrollo se tolera el modo consola; en un despliegue real, no.
    _exigido("MAIL_SMTP_HOST")
    _exigido("MAIL_REMITENTE")

    if Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
        raise RuntimeError(
            f"DATABASE_URL apunta a SQLite y ENTORNO={ENTORNO}. Usa PostgreSQL: "
            "un archivo dentro del contenedor se pierde en cada redespliegue."
        )
