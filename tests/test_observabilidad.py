"""Sondas de salud y logs que no filtran datos personales."""
import json
import logging

import pytest


def test_health_no_toca_la_base(cliente):
    """/health responde si el PROCESO está vivo. No consulta nada: si fallara
    por culpa de Postgres, un orquestador reiniciaría la aplicación en bucle
    cuando el problema está fuera de ella."""
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.get_json()["estado"] == "vivo"


def test_ready_comprueba_la_base(cliente):
    r = cliente.get("/ready")
    assert r.status_code == 200
    d = r.get_json()
    assert d["estado"] == "listo"
    assert d["base_de_datos"] == "ok"


def test_las_sondas_no_exigen_sesion(cliente):
    """Un orquestador no tiene credenciales."""
    for ruta in ("/health", "/ready"):
        assert cliente.get(ruta).status_code == 200


def test_cada_respuesta_lleva_identificador_de_peticion(cliente):
    """Permite que un usuario que reporta un fallo cite el id y se encuentre su
    petición exacta en el log."""
    r = cliente.get("/health")
    assert r.headers.get("X-Request-ID")


def test_se_respeta_el_identificador_entrante(cliente):
    """Para poder seguir una operación a través de varios servicios."""
    r = cliente.get("/health", headers={"X-Request-ID": "trazaexterna123"})
    assert r.headers["X-Request-ID"] == "trazaexterna123"


def test_un_identificador_absurdo_no_se_propaga(cliente):
    """Un id inventado por el cliente acaba en los logs: no puede ser
    arbitrariamente largo ni traer caracteres de control."""
    r = cliente.get("/health", headers={"X-Request-ID": "x" * 500})
    assert r.headers["X-Request-ID"] != "x" * 500


def test_el_log_de_una_peticion_no_lleva_datos_personales(cliente, crear_usuario, auth, capturar_logs):
    """Lo que NO se registra importa tanto como lo que sí.

    QuestCash cifra los datos personales en reposo; volcarlos al log los sacaría
    por la puerta de atrás, y los logs acaban en sistemas con retención larga y
    control de acceso más laxo que la base de datos.
    """
    import datetime

    u = crear_usuario(correo="secreto.log@questcash.com")
    cab = auth(u["access"])
    limite = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    capturados = capturar_logs()

    meta = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Meta secreta", "monto_objetivo": "4321.99", "fecha_limite": limite,
    }).get_json()["quest"]["id"]
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab, json={
        "tipo": "aporte", "monto": "1234.56", "nota": "NOTA-MUY-PRIVADA",
    })

    # Sin esta comprobación, la prueba pasaría aunque no se registrara nada:
    # comprobar que algo NO aparece en una lista vacía no prueba nada.
    assert capturados.registros, "no se capturó ningún registro"

    texto = "\n".join(
        r.getMessage() + json.dumps(getattr(r, "extra_json", {}), default=str)
        for r in capturados.registros
    )
    for prohibido in ("secreto.log@questcash.com", "NOTA-MUY-PRIVADA", "1234.56",
                      "4321.99", u["access"], u["password"]):
        assert prohibido not in texto, f"el log filtró: {prohibido[:20]}"


def test_el_log_si_registra_lo_necesario_para_investigar(cliente, crear_usuario, auth, capturar_logs):
    u = crear_usuario(); cab = auth(u["access"])
    capturados = capturar_logs()
    cliente.get("/api/v1/dashboard", headers=cab)

    peticiones = [getattr(r, "extra_json", {}) for r in capturados.registros
                  if r.getMessage() == "peticion"]
    assert peticiones, "no se registró la petición"
    campos = peticiones[-1]
    assert campos["ruta"] == "/api/v1/dashboard"
    assert campos["metodo"] == "GET"
    assert campos["estado"] == 200
    assert campos["usuario_id"] == u["id"]   # el id, nunca el correo
    assert campos["peticion_id"]
    assert isinstance(campos["ms"], float)


def test_las_sondas_no_ensucian_el_log(cliente, capturar_logs):
    """Llegan cada pocos segundos y ahogarían cualquier cosa útil."""
    capturados = capturar_logs()
    for _ in range(5):
        cliente.get("/health")
    assert not [r for r in capturados.registros if r.getMessage() == "peticion"]


def test_el_formato_json_serializa_los_campos_extra():
    from observabilidad import FormatoJSON

    registro = logging.LogRecord("x", logging.INFO, "f", 1, "hola", None, None)
    registro.extra_json = {"ruta": "/x", "estado": 200}
    salida = json.loads(FormatoJSON().format(registro))
    assert salida["mensaje"] == "hola"
    assert salida["nivel"] == "INFO"
    assert salida["ruta"] == "/x" and salida["estado"] == 200
    assert "hora" in salida


def test_las_migraciones_no_silencian_los_loggers(aplicacion, capturar_logs):
    """Regresión de un fallo que dejaba la aplicación muda EN PRODUCCIÓN.

    `fileConfig()` desactiva por omisión todos los loggers existentes, y
    Alembic lo llama desde migrations/env.py. Como las migraciones corren al
    arrancar el contenedor —antes de levantar gunicorn—, la aplicación
    funcionaba y no registraba absolutamente nada durante toda la vida del
    proceso. Nadie se habría enterado hasta necesitar los logs.
    """
    import logging
    from flask_migrate import upgrade

    capturados = capturar_logs("questcash.peticiones", logging.DEBUG)

    with aplicacion.app_context():
        upgrade()   # vuelve a pasar por fileConfig

    logging.getLogger("questcash.peticiones").info("después de migrar")
    assert capturados.registros, "las migraciones dejaron el logger desactivado"
    assert not logging.getLogger("questcash.peticiones").disabled
