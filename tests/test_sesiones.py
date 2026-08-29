"""Ciclo de vida de la sesión: emisión, rotación y revocación."""
import pytest


def test_login_devuelve_los_dos_tokens(cliente, crear_usuario):
    u = crear_usuario()
    r = cliente.post("/api/v1/auth/login",
                     json={"correo": u["correo"], "password": u["password"]})
    d = r.get_json()
    assert r.status_code == 200
    assert d["access_token"] and d["refresh_token"]
    # `token` se conserva como alias: quitarlo rompería a los clientes ya hechos.
    assert d["token"] == d["access_token"]


def test_el_refresh_rota_y_el_anterior_deja_de_valer(cliente, crear_usuario):
    """La rotación es lo que hace detectable el robo de un refresh: si alguien
    lo roba y lo canjea, el legítimo falla en su siguiente intento."""
    u = crear_usuario()
    r1 = cliente.post("/api/v1/auth/refresh", json={"refresh_token": u["refresh"]})
    assert r1.status_code == 200
    nuevo = r1.get_json()["refresh_token"]
    assert nuevo != u["refresh"]

    # El viejo ya no sirve.
    assert cliente.post("/api/v1/auth/refresh",
                        json={"refresh_token": u["refresh"]}).status_code == 401
    # El nuevo sí.
    assert cliente.post("/api/v1/auth/refresh",
                        json={"refresh_token": nuevo}).status_code == 200


def test_un_refresh_no_sirve_como_access(cliente, crear_usuario, auth):
    """La comprobación de `typ` impide que un token de otro propósito valga
    como credencial de acceso."""
    u = crear_usuario()
    r = cliente.get("/api/v1/auth/me", headers=auth(u["refresh"]))
    assert r.status_code == 401


def test_logout_cierra_la_sesion_en_el_servidor(cliente, crear_usuario):
    """Antes, cerrar sesión solo borraba el token del dispositivo: seguía
    siendo válido 30 días para quien lo tuviera."""
    u = crear_usuario()
    assert cliente.post("/api/v1/auth/logout",
                        json={"refresh_token": u["refresh"]}).status_code == 200
    assert cliente.post("/api/v1/auth/refresh",
                        json={"refresh_token": u["refresh"]}).status_code == 401


def test_logout_all_invalida_los_access_de_todos_los_dispositivos(cliente, crear_usuario, auth):
    """Subir token_version mata los access ya emitidos sin tener que buscarlos."""
    u = crear_usuario()
    otra = cliente.post("/api/v1/auth/login",
                        json={"correo": u["correo"], "password": u["password"]}).get_json()

    r = cliente.post("/api/v1/auth/logout-all", headers=auth(u["access"]))
    assert r.status_code == 200

    for token in (u["access"], otra["access_token"]):
        resp = cliente.get("/api/v1/auth/me", headers=auth(token))
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "token_revoked"

    assert cliente.post("/api/v1/auth/refresh",
                        json={"refresh_token": otra["refresh_token"]}).status_code == 401


def test_el_listado_de_sesiones_no_expone_tokens(cliente, crear_usuario, auth):
    u = crear_usuario()
    d = cliente.get("/api/v1/auth/sesiones", headers=auth(u["access"])).get_json()
    assert len(d["sesiones"]) >= 1
    for s in d["sesiones"]:
        assert not any("token" in str(k).lower() for k in s)


def test_cambiar_la_password_cierra_las_demas_sesiones(cliente, crear_usuario, auth):
    u = crear_usuario()
    otra = cliente.post("/api/v1/auth/login",
                        json={"correo": u["correo"], "password": u["password"]}).get_json()

    r = cliente.put("/api/v1/auth/password", headers=auth(u["access"]), json={
        "password_actual": u["password"],
        "password": "OtraClaveSegura9", "password2": "OtraClaveSegura9",
    })
    assert r.status_code == 200
    # Devuelve sesión nueva: expulsar a quien acaba de cambiar su propia
    # contraseña sería absurdo.
    assert r.get_json()["access_token"]

    assert cliente.get("/api/v1/auth/me", headers=auth(otra["access_token"])).status_code == 401
    assert cliente.post("/api/v1/auth/login", json={
        "correo": u["correo"], "password": u["password"]}).status_code == 401
    assert cliente.post("/api/v1/auth/login", json={
        "correo": u["correo"], "password": "OtraClaveSegura9"}).status_code == 200


def test_la_password_actual_es_obligatoria_para_cambiarla(cliente, crear_usuario, auth):
    u = crear_usuario()
    r = cliente.put("/api/v1/auth/password", headers=auth(u["access"]), json={
        "password_actual": "equivocada",
        "password": "OtraClaveSegura9", "password2": "OtraClaveSegura9",
    })
    assert r.status_code == 400


def test_bloqueo_tras_intentos_fallidos(cliente, crear_usuario):
    """El contador estaba en un diccionario de proceso: cada worker daba sus
    propios 5 intentos y las entradas no se limpiaban nunca."""
    u = crear_usuario()
    for i in range(5):
        r = cliente.post("/api/v1/auth/login",
                         json={"correo": u["correo"], "password": "mala"})
        assert r.status_code == 401, f"intento {i+1}"

    r = cliente.post("/api/v1/auth/login",
                     json={"correo": u["correo"], "password": "mala"})
    assert r.status_code == 429
    assert r.get_json()["error"] == "locked"

    # El bloqueo aplica también a la contraseña correcta.
    r = cliente.post("/api/v1/auth/login",
                     json={"correo": u["correo"], "password": u["password"]})
    assert r.status_code == 429
