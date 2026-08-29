"""Infraestructura común de las pruebas.

Las pruebas corren contra **PostgreSQL real**, no SQLite. No es un capricho:
casi todo lo que hay que verificar aquí se comporta distinto o no existe en
SQLite —`Numeric` con precisión exacta, `SELECT ... FOR UPDATE`, las
restricciones UNIQUE que sostienen la idempotencia, los tipos con zona
horaria—. Una suite que pasara en SQLite no diría nada sobre producción.

El esquema se crea aplicando las MIGRACIONES, no `db.create_all()`. Así cada
ejecución comprueba de paso que las migraciones reproducen el esquema que los
modelos describen, que es justo lo que se rompió una vez durante la fase 2.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# --- Entorno de pruebas, ANTES de importar la aplicación --------------------
#
# app.py llama a create_app() al importarse, así que la configuración tiene que
# estar puesta antes del primer import.
def _url_de_pruebas() -> str:
    """Base de datos de pruebas, SIEMPRE distinta de la de desarrollo.

    Orden: TEST_DATABASE_URL explícita > compuesta de las POSTGRES_* del
    entorno (lo que hace `set -a; . ./.env`) > valores por omisión del
    contenedor de servicio de CI.
    """
    explicita = os.environ.get("TEST_DATABASE_URL")
    if explicita:
        return explicita

    usuario = os.environ.get("POSTGRES_USER", "questcash")
    password = os.environ.get("POSTGRES_PASSWORD", "questcash")
    host = os.environ.get("TEST_DB_HOST", "127.0.0.1")
    puerto = os.environ.get("TEST_DB_PORT", "5432")
    return f"postgresql://{usuario}:{password}@{host}:{puerto}/questcash_test"


URL_BASE = _url_de_pruebas()

# Salvaguarda: una prueba TRUNCA todas las tablas entre casos. Apuntar por
# accidente a la base de desarrollo —o peor— la vaciaría entera.
if not URL_BASE.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError(
        f"La base de pruebas debe terminar en '_test', y es '{URL_BASE.rsplit('/', 1)[-1]}'. "
        "Las pruebas truncan todas las tablas: apuntar a otra base la vaciaría."
    )
os.environ["ENTORNO"] = "testing"
os.environ["DATABASE_URL"] = URL_BASE
os.environ.setdefault("SECRET_KEY", "clave-de-pruebas-no-usar-fuera")
os.environ.setdefault("JWT_SECRET_KEY", "clave-jwt-de-pruebas")

def _clave_de_pruebas(etiqueta: str) -> str:
    """Clave de 32 bytes derivada de una etiqueta.

    Se DERIVA en vez de escribirse literal a propósito. Una cadena base64 de 32
    bytes dentro de un archivo versionado es indistinguible de una clave de
    verdad: los detectores de secretos la marcan —con razón, porque no pueden
    saber que es de mentira— y acostumbrarse a ignorar esas alertas es
    exactamente cómo se cuela una filtración real.

    Es determinista para que los datos cifrados en una prueba se puedan leer en
    la siguiente línea, y no tiene ningún valor fuera de aquí.
    """
    import base64
    import hashlib
    return base64.urlsafe_b64encode(
        hashlib.sha256(f"questcash-pruebas-{etiqueta}".encode()).digest()
    ).decode()


os.environ.setdefault("DATA_ENC_KEY", _clave_de_pruebas("cifrado"))
os.environ.setdefault("BLIND_INDEX_KEY", _clave_de_pruebas("indice-ciego"))
# Sin REDIS_URL, rate_limit usa memoria de proceso: es lo que se quiere aquí,
# para que una prueba no arrastre el estado de otra.
os.environ.pop("REDIS_URL", None)
# Sin proveedor SMTP: correo.py escribe en el log en vez de enviar.
os.environ.pop("MAIL_SMTP_HOST", None)


@pytest.fixture(scope="session")
def aplicacion():
    from app import app as flask_app
    from flask_migrate import upgrade

    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with flask_app.app_context():
        upgrade()          # el esquema sale de las migraciones reales
        _sembrar_insignias()

    yield flask_app


def _sembrar_insignias():
    from app import seed_insignias
    from services import gastos as gastos_svc
    seed_insignias()
    gastos_svc.sembrar()


@pytest.fixture(autouse=True)
def base_limpia(aplicacion):
    """Deja la base como recién migrada entre pruebas.

    TRUNCATE con CASCADE y reinicio de secuencias: más rápido que recrear el
    esquema y deja los ids empezando en 1, lo que hace las pruebas
    reproducibles. Las insignias se resiembran porque son datos de sistema, no
    de usuario.
    """
    from models import db

    with aplicacion.app_context():
        tablas = [
            "claves_idempotencia", "tokens_correo", "sesiones",
            "invitaciones_quest", "notificaciones", "usuarios_insignias",
            "movimientos", "participaciones_quest", "gastos", "quests",
            "categorias_gasto", "insignias", "usuarios",
        ]
        db.session.execute(
            db.text("TRUNCATE " + ", ".join(tablas) + " RESTART IDENTITY CASCADE")
        )
        db.session.commit()
        _sembrar_insignias()
        # rate_limit guarda estado en memoria del proceso entre pruebas.
        import rate_limit
        rate_limit.reiniciar()
    yield


@pytest.fixture
def cliente(aplicacion):
    return aplicacion.test_client()


# ---------------------------------------------------------------------------
#  Ayudas
# ---------------------------------------------------------------------------
PASSWORD = "PruebaSegura9"


@pytest.fixture
def crear_usuario(cliente):
    """Registra un usuario y devuelve sus tokens y su id."""
    def _crear(correo=None, nombre="Usuario Prueba", password=PASSWORD):
        correo = correo or f"u{uuid.uuid4().hex[:10]}@questcash.com"
        r = cliente.post("/api/v1/auth/register", json={
            "nombre": nombre, "correo": correo,
            "password": password, "password2": password,
        })
        assert r.status_code == 201, r.get_json()
        d = r.get_json()
        return {
            "correo": correo, "password": password,
            "access": d["access_token"], "refresh": d["refresh_token"],
            "id": d["user"]["id"],
        }
    return _crear


@pytest.fixture
def auth():
    """Cabecera Authorization a partir de un access token."""
    def _auth(token):
        return {"Authorization": f"Bearer {token}"}
    return _auth
