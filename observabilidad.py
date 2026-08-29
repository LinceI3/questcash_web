# observabilidad.py
"""Logs estructurados, identificador de petición y seguimiento de errores.

Qué resuelve
------------
No había nada. Los errores iban al stderr por omisión de Flask, sin formato,
sin forma de correlacionar las líneas de una misma petición y sin identificar a
quién le pasó. La única manera de enterarse de que algo falló en producción era
que un usuario lo dijera.

Formato
-------
Una línea JSON por evento. No es por moda: un recolector de logs puede filtrar
por campo —`nivel=ERROR`, `ruta=/api/v1/gastos`, `peticion_id=...`— y eso es lo
que convierte un montón de texto en algo con lo que se puede investigar. En
desarrollo se puede pedir el formato legible con LOG_FORMATO=texto.

Qué NO se registra
------------------
Esto importa tanto como lo que sí. QuestCash cifra los datos personales en
reposo; volcarlos al log los sacaría por la puerta de atrás, y los logs suelen
acabar en sistemas de terceros con retención larga y control de acceso más laxo
que la base de datos.

Nunca se registran: correos, nombres, notas de movimientos, descripciones de
gastos, importes, contraseñas ni tokens. Sí se registra el **id numérico** del
usuario, que permite investigar un incidente sin exponer quién es.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from flask import g, request

# Cabeceras que nunca deben aparecer en un log.
CABECERAS_SENSIBLES = {"authorization", "cookie", "set-cookie", "x-api-key", "idempotency-key"}

# Rutas que no vale la pena registrar: las sondas de salud llegan cada pocos
# segundos y ahogarían cualquier cosa útil.
RUTAS_SILENCIOSAS = {"/health", "/ready"}


class FormatoJSON(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        datos = {
            "hora": datetime.fromtimestamp(registro.created, timezone.utc).isoformat(),
            "nivel": registro.levelname,
            "logger": registro.name,
            "mensaje": registro.getMessage(),
        }
        # Todo lo que se pase por `extra=` acaba aquí.
        for clave, valor in getattr(registro, "extra_json", {}).items():
            datos[clave] = valor
        if registro.exc_info:
            datos["excepcion"] = self.formatException(registro.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)


def _configurar_raiz():
    nivel = os.environ.get("LOG_NIVEL", "INFO").upper()
    formato = os.environ.get("LOG_FORMATO", "json").lower()

    manejador = logging.StreamHandler(sys.stdout)
    if formato == "texto":
        manejador.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    else:
        manejador.setFormatter(FormatoJSON())

    raiz = logging.getLogger()
    raiz.handlers = [manejador]
    raiz.setLevel(nivel)

    # Werkzeug duplica cada petición con su propio formato; el registro lo
    # hacemos nosotros con más contexto.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def registrar(logger, nivel, mensaje, **campos):
    """Emite una línea con campos adicionales."""
    logger.log(nivel, mensaje, extra={"extra_json": campos})


def _id_de_peticion() -> str:
    """Identificador de esta petición.

    Se respeta el que venga en la cabecera para poder seguir una operación a
    través de varios servicios; si no viene, se genera.
    """
    entrante = (request.headers.get("X-Request-ID") or "").strip()
    if entrante and len(entrante) <= 64 and entrante.isascii():
        return entrante
    return uuid.uuid4().hex[:16]


def init_app(app):
    _configurar_raiz()
    logger = logging.getLogger("questcash.peticiones")

    @app.before_request
    def _abrir():
        g.peticion_id = _id_de_peticion()
        g.peticion_inicio = time.perf_counter()

    @app.after_request
    def _cerrar(respuesta):
        # La cabecera va SIEMPRE, incluso en las rutas que no se registran:
        # permite que un usuario que reporta un fallo cite el id y se encuentre
        # su petición exacta.
        respuesta.headers["X-Request-ID"] = getattr(g, "peticion_id", "")

        if request.path in RUTAS_SILENCIOSAS:
            return respuesta

        inicio = getattr(g, "peticion_inicio", None)
        ms = round((time.perf_counter() - inicio) * 1000, 1) if inicio else None

        # El id del usuario, nunca su correo ni su nombre.
        usuario_id = None
        for atributo in ("api_usuario", "usuario_actual"):
            actual = getattr(g, atributo, None)
            if actual is not None:
                usuario_id = actual.id
                break

        registrar(
            logger,
            logging.WARNING if respuesta.status_code >= 500 else logging.INFO,
            "peticion",
            peticion_id=getattr(g, "peticion_id", None),
            metodo=request.method,
            ruta=request.path,
            estado=respuesta.status_code,
            ms=ms,
            usuario_id=usuario_id,
            ip=request.remote_addr,
        )
        return respuesta

    @app.errorhandler(Exception)
    def _error_no_capturado(error):
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return error   # 404, 403 y compañía no son fallos del servidor

        logging.getLogger("questcash").error(
            "excepción no capturada",
            exc_info=error,
            extra={"extra_json": {
                "peticion_id": getattr(g, "peticion_id", None),
                "ruta": request.path,
                "metodo": request.method,
            }},
        )
        raise error   # que Flask siga su curso normal

    _configurar_sentry(app)
    return app


def _configurar_sentry(app):
    """Conecta el seguimiento de errores si hay DSN.

    Va detrás de una variable para que no haga falta cuenta en desarrollo. Sin
    ella, la aplicación funciona igual y los errores quedan en el log.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        logging.getLogger("questcash").warning(
            "SENTRY_DSN está definida pero sentry-sdk no está instalado"
        )
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ENTORNO", "development"),
        integrations=[FlaskIntegration()],
        # Muestreo bajo por omisión: el rendimiento interesa menos que los
        # errores y el volumen se cobra.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES", "0.05")),
        # QuestCash trata datos financieros: nunca mandar cuerpos ni cabeceras.
        send_default_pii=False,
        max_request_body_size="never",
    )
    logging.getLogger("questcash").info("seguimiento de errores activo")
