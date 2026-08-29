"""Consentimiento en metas compartidas, y no revelar quién tiene cuenta."""
import datetime


def _fecha(dias=90):
    return (datetime.date.today() + datetime.timedelta(days=dias)).isoformat()


def _meta_colaborativa(cliente, cab, nombre="Compartida"):
    return cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": nombre, "monto_objetivo": "900.00",
        "fecha_limite": _fecha(), "es_colaborativo": True,
    }).get_json()["quest"]["id"]


def test_invitar_no_mete_a_nadie_en_la_meta(cliente, crear_usuario, auth):
    """Antes, invitar creaba la participación directamente: la persona quedaba
    dentro de una meta ajena sin aceptar nada y sin poder salirse."""
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    cab_ana, cab_beto = auth(ana["access"]), auth(beto["access"])
    meta = _meta_colaborativa(cliente, cab_ana)

    assert cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana,
                        json={"correo": beto["correo"]}).status_code == 201

    participantes = cliente.get(f"/api/v1/quests/{meta}/colaboradores",
                                headers=cab_ana).get_json()["participaciones"]
    assert beto["id"] not in [p["usuario"]["id"] for p in participantes]
    # Y sin aceptar, no puede ni verla.
    assert cliente.get(f"/api/v1/quests/{meta}", headers=cab_beto).status_code == 403


def test_invitar_no_revela_si_el_correo_tiene_cuenta(cliente, crear_usuario, auth):
    """El endpoint respondía "No existe un usuario registrado con ese correo",
    lo que lo convertía en un oráculo para averiguar quién está registrado."""
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    cab_ana = auth(ana["access"])
    meta = _meta_colaborativa(cliente, cab_ana)

    existe = cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana,
                          json={"correo": beto["correo"]})
    no_existe = cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana,
                             json={"correo": "jamas.existio@questcash.com"})

    assert existe.status_code == no_existe.status_code == 201
    assert set(existe.get_json()["invitacion"]) == set(no_existe.get_json()["invitacion"])


def test_aceptar_mete_al_invitado_y_rechazar_no(cliente, crear_usuario, auth):
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    carla = crear_usuario(nombre="Carla")
    cab_ana, cab_beto, cab_carla = auth(ana["access"]), auth(beto["access"]), auth(carla["access"])
    meta = _meta_colaborativa(cliente, cab_ana)

    for u in (beto, carla):
        cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana,
                     json={"correo": u["correo"]})

    inv_beto = cliente.get("/api/v1/invitaciones", headers=cab_beto).get_json()["invitaciones"][0]
    inv_carla = cliente.get("/api/v1/invitaciones", headers=cab_carla).get_json()["invitaciones"][0]

    assert cliente.post(f"/api/v1/invitaciones/{inv_beto['id']}/aceptar",
                        headers=cab_beto).status_code == 200
    assert cliente.post(f"/api/v1/invitaciones/{inv_carla['id']}/rechazar",
                        headers=cab_carla).status_code == 200

    ids = [p["usuario"]["id"] for p in
           cliente.get(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana)
           .get_json()["participaciones"]]
    assert beto["id"] in ids and carla["id"] not in ids


def test_no_se_responde_dos_veces_ni_una_invitacion_ajena(cliente, crear_usuario, auth):
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    intruso = crear_usuario(nombre="Intruso")
    cab_ana, cab_beto, cab_intruso = auth(ana["access"]), auth(beto["access"]), auth(intruso["access"])
    meta = _meta_colaborativa(cliente, cab_ana)
    cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana,
                 json={"correo": beto["correo"]})
    inv = cliente.get("/api/v1/invitaciones", headers=cab_beto).get_json()["invitaciones"][0]

    # Un tercero no puede responderla, y recibe 404 —no 403— para no confirmar
    # que existe.
    assert cliente.post(f"/api/v1/invitaciones/{inv['id']}/aceptar",
                        headers=cab_intruso).status_code == 404

    assert cliente.post(f"/api/v1/invitaciones/{inv['id']}/aceptar",
                        headers=cab_beto).status_code == 200
    assert cliente.post(f"/api/v1/invitaciones/{inv['id']}/aceptar",
                        headers=cab_beto).status_code == 409


def test_al_invitado_no_se_le_manda_el_correo_y_al_creador_si(cliente, crear_usuario, auth):
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    cab_ana, cab_beto = auth(ana["access"]), auth(beto["access"])
    meta = _meta_colaborativa(cliente, cab_ana)
    cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana,
                 json={"correo": beto["correo"]})

    del_invitado = cliente.get("/api/v1/invitaciones", headers=cab_beto).get_json()["invitaciones"][0]
    del_creador = cliente.get(f"/api/v1/quests/{meta}/invitaciones",
                              headers=cab_ana).get_json()["invitaciones"][0]

    assert "correo" not in del_invitado          # ya sabe cuál es el suyo
    assert del_creador["correo"] == beto["correo"]   # lo escribió él al invitar


def test_se_puede_abandonar_una_meta_y_el_aporte_se_conserva(cliente, crear_usuario, auth):
    """No existía forma de salir de una meta. Los aportes ya hechos no se
    borran: son movimientos de la meta, no del participante."""
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    cab_ana, cab_beto = auth(ana["access"]), auth(beto["access"])
    meta = _meta_colaborativa(cliente, cab_ana)
    cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana,
                 json={"correo": beto["correo"]})
    inv = cliente.get("/api/v1/invitaciones", headers=cab_beto).get_json()["invitaciones"][0]
    cliente.post(f"/api/v1/invitaciones/{inv['id']}/aceptar", headers=cab_beto)
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_beto,
                 json={"tipo": "aporte", "monto": "40.00"})

    assert cliente.post(f"/api/v1/quests/{meta}/abandonar", headers=cab_beto).status_code == 204
    assert cliente.get(f"/api/v1/quests/{meta}", headers=cab_beto).status_code == 403

    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab_ana).get_json()
    assert detalle["quest"]["monto_actual"] == 40.00


def test_el_creador_no_puede_abandonar_su_propia_meta(cliente, crear_usuario, auth):
    ana = crear_usuario(nombre="Ana"); cab = auth(ana["access"])
    meta = _meta_colaborativa(cliente, cab)
    r = cliente.post(f"/api/v1/quests/{meta}/abandonar", headers=cab)
    assert r.status_code == 400
    assert r.get_json()["error"] == "creator_cannot_leave"
