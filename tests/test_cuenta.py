"""Derechos sobre la propia cuenta: acceso, portabilidad y cancelación."""
import datetime

from models import Gasto, Movimiento, Notificacion, ParticipacionQuest, Quest, Sesion, Usuario, db


def _fecha(dias=90):
    return (datetime.date.today() + datetime.timedelta(days=dias)).isoformat()


def test_exportar_devuelve_todo_lo_que_se_guarda(cliente, crear_usuario, auth):
    u = crear_usuario(); cab = auth(u["access"])
    meta = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Mi meta", "monto_objetivo": "500.00", "fecha_limite": _fecha(),
    }).get_json()["quest"]["id"]
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "aporte", "monto": "25.00", "nota": "una nota privada"})
    cliente.post("/api/v1/gastos", headers=cab,
                 json={"monto": "9.99", "descripcion": "un gasto"})

    r = cliente.get("/api/v1/auth/mis-datos", headers=cab)
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")

    d = r.get_json()
    for clave in ("cuenta", "metas", "movimientos", "gastos", "insignias", "sesiones"):
        assert clave in d
    assert d["cuenta"]["correo"] == u["correo"]
    assert len(d["metas"]) == 1 and len(d["movimientos"]) == 1 and len(d["gastos"]) == 1
    # Los campos cifrados se devuelven descifrados: son suyos.
    assert d["movimientos"][0]["nota"] == "una nota privada"


def test_eliminar_exige_la_password(cliente, crear_usuario, auth):
    """Un token no basta para algo irreversible: un dispositivo desatendido no
    debe poder borrar la cuenta de nadie."""
    u = crear_usuario(); cab = auth(u["access"])
    assert cliente.delete("/api/v1/auth/cuenta", headers=cab,
                          json={"password": "equivocada"}).status_code == 400
    assert cliente.get("/api/v1/auth/me", headers=cab).status_code == 200


def test_eliminar_borra_de_verdad(cliente, crear_usuario, auth, aplicacion):
    """El borrado es real, no una marca de baja: una cuenta "dada de baja" que
    conserva los datos no satisface el derecho de cancelación."""
    u = crear_usuario(); cab = auth(u["access"])
    meta = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Mi meta", "monto_objetivo": "500.00", "fecha_limite": _fecha(),
    }).get_json()["quest"]["id"]
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "aporte", "monto": "25.00"})
    cliente.post("/api/v1/gastos", headers=cab, json={"monto": "9.99", "descripcion": "x"})

    assert cliente.delete("/api/v1/auth/cuenta", headers=cab,
                          json={"password": u["password"]}).status_code == 204

    assert cliente.get("/api/v1/auth/me", headers=cab).status_code == 401
    assert cliente.post("/api/v1/auth/login", json={
        "correo": u["correo"], "password": u["password"]}).status_code == 401

    with aplicacion.app_context():
        assert Usuario.query.get(u["id"]) is None
        assert Quest.query.filter_by(usuario_id=u["id"]).count() == 0
        assert Gasto.query.filter_by(usuario_id=u["id"]).count() == 0
        assert Sesion.query.filter_by(usuario_id=u["id"]).count() == 0
        assert Notificacion.query.filter_by(usuario_id=u["id"]).count() == 0
        assert ParticipacionQuest.query.filter_by(usuario_id=u["id"]).count() == 0


def test_eliminar_no_descuadra_las_metas_compartidas_de_otros(cliente, crear_usuario, auth, aplicacion):
    """La primera versión borraba los aportes en metas ajenas, y la meta
    quedaba con un saldo que ya no cuadraba con su historial: el progreso de
    personas que no habían pedido nada se reducía solo."""
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    cab_ana, cab_beto = auth(ana["access"]), auth(beto["access"])

    meta = cliente.post("/api/v1/quests", headers=cab_beto, json={
        "nombre": "De Beto", "monto_objetivo": "900.00",
        "fecha_limite": _fecha(), "es_colaborativo": True,
    }).get_json()["quest"]["id"]
    cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_beto,
                 json={"correo": ana["correo"]})
    inv = cliente.get("/api/v1/invitaciones", headers=cab_ana).get_json()["invitaciones"][0]
    cliente.post(f"/api/v1/invitaciones/{inv['id']}/aceptar", headers=cab_ana)

    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_ana,
                 json={"tipo": "aporte", "monto": "30.00"})
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_beto,
                 json={"tipo": "aporte", "monto": "70.00"})

    antes = cliente.get(f"/api/v1/quests/{meta}", headers=cab_beto).get_json()["quest"]["monto_actual"]
    movs_antes = len(cliente.get(f"/api/v1/quests/{meta}/movimientos",
                                 headers=cab_beto).get_json()["movimientos"])

    cliente.delete("/api/v1/auth/cuenta", headers=cab_ana, json={"password": ana["password"]})

    despues = cliente.get(f"/api/v1/quests/{meta}", headers=cab_beto).get_json()
    movs = cliente.get(f"/api/v1/quests/{meta}/movimientos", headers=cab_beto).get_json()

    assert despues["quest"]["monto_actual"] == antes == 100.00
    assert len(movs["movimientos"]) == movs_antes
    # El aporte se conserva pero deja de estar ligado a nadie.
    assert sum(1 for m in movs["movimientos"] if m["usuario_id"] is None) == 1


def test_eliminar_no_deja_filas_huerfanas(cliente, crear_usuario, auth, aplicacion):
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    cab_ana, cab_beto = auth(ana["access"]), auth(beto["access"])
    meta = cliente.post("/api/v1/quests", headers=cab_beto, json={
        "nombre": "De Beto", "monto_objetivo": "900.00",
        "fecha_limite": _fecha(), "es_colaborativo": True,
    }).get_json()["quest"]["id"]
    cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_beto,
                 json={"correo": ana["correo"]})
    inv = cliente.get("/api/v1/invitaciones", headers=cab_ana).get_json()["invitaciones"][0]
    cliente.post(f"/api/v1/invitaciones/{inv['id']}/aceptar", headers=cab_ana)
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_ana,
                 json={"tipo": "aporte", "monto": "30.00"})

    cliente.delete("/api/v1/auth/cuenta", headers=cab_ana, json={"password": ana["password"]})

    with aplicacion.app_context():
        huerfanas = db.session.execute(db.text("""
            SELECT
              (SELECT count(*) FROM movimientos m LEFT JOIN usuarios u ON m.usuario_id=u.id
                 WHERE m.usuario_id IS NOT NULL AND u.id IS NULL)
            + (SELECT count(*) FROM gastos g LEFT JOIN usuarios u ON g.usuario_id=u.id WHERE u.id IS NULL)
            + (SELECT count(*) FROM participaciones_quest p LEFT JOIN usuarios u ON p.usuario_id=u.id WHERE u.id IS NULL)
            + (SELECT count(*) FROM notificaciones n LEFT JOIN usuarios u ON n.usuario_id=u.id WHERE u.id IS NULL)
            + (SELECT count(*) FROM sesiones s LEFT JOIN usuarios u ON s.usuario_id=u.id WHERE u.id IS NULL)
            + (SELECT count(*) FROM quests q LEFT JOIN usuarios u ON q.usuario_id=u.id WHERE u.id IS NULL)
        """)).scalar()
        assert huerfanas == 0


def test_recuperar_responde_igual_exista_o_no_la_cuenta(cliente, crear_usuario):
    u = crear_usuario()
    existe = cliente.post("/api/v1/auth/recuperar", json={"correo": u["correo"]})
    no_existe = cliente.post("/api/v1/auth/recuperar",
                             json={"correo": "jamas.existio@questcash.com"})
    assert existe.status_code == no_existe.status_code == 200
    assert existe.get_json() == no_existe.get_json()
