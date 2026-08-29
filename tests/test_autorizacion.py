"""Aislamiento entre usuarios.

Comprueba que los datos de una persona no son alcanzables por otra. Es la
familia de fallos más cara de una aplicación financiera y la más fácil de
introducir sin darse cuenta al añadir un endpoint.
"""
import datetime

import pytest


def _fecha(dias=90):
    return (datetime.date.today() + datetime.timedelta(days=dias)).isoformat()


@pytest.fixture
def dos_usuarios(cliente, crear_usuario, auth):
    """Ana con una meta, un movimiento y un gasto; Beto sin nada."""
    ana = crear_usuario(nombre="Ana")
    beto = crear_usuario(nombre="Beto")
    cab_ana = auth(ana["access"])

    meta = cliente.post("/api/v1/quests", headers=cab_ana, json={
        "nombre": "Meta de Ana", "monto_objetivo": "1000.00", "fecha_limite": _fecha(),
    }).get_json()["quest"]["id"]

    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_ana,
                 json={"tipo": "aporte", "monto": "100.00"})
    cliente.post("/api/v1/gastos", headers=cab_ana,
                 json={"monto": "20.00", "descripcion": "privado de Ana"})
    notif = cliente.get("/api/v1/notificaciones", headers=cab_ana).get_json()

    return {"ana": ana, "beto": beto, "meta": meta, "notificaciones": notif}


@pytest.mark.parametrize("metodo,ruta", [
    ("get",    "/api/v1/quests/{meta}"),
    ("put",    "/api/v1/quests/{meta}"),
    ("delete", "/api/v1/quests/{meta}"),
    ("post",   "/api/v1/quests/{meta}/cancel"),
    ("get",    "/api/v1/quests/{meta}/movimientos"),
    ("post",   "/api/v1/quests/{meta}/movimientos"),
    ("get",    "/api/v1/quests/{meta}/colaboradores"),
    ("post",   "/api/v1/quests/{meta}/colaboradores"),
    ("get",    "/api/v1/quests/{meta}/invitaciones"),
])
def test_un_usuario_no_alcanza_la_meta_de_otro(cliente, auth, dos_usuarios, metodo, ruta):
    cab = auth(dos_usuarios["beto"]["access"])
    url = ruta.format(meta=dos_usuarios["meta"])
    r = getattr(cliente, metodo)(url, headers=cab, json={})
    assert r.status_code in (403, 404), f"{metodo.upper()} {url} devolvió {r.status_code}"


def test_los_gastos_no_se_cruzan(cliente, auth, dos_usuarios):
    cab = auth(dos_usuarios["beto"]["access"])
    datos = cliente.get("/api/v1/gastos?period=month", headers=cab).get_json()
    assert datos["gastos"] == []
    assert datos["total_periodo"] == 0


def test_el_dashboard_no_cruza_metas(cliente, auth, dos_usuarios):
    cab = auth(dos_usuarios["beto"]["access"])
    datos = cliente.get("/api/v1/dashboard", headers=cab).get_json()
    assert datos["quests"] == []


def test_no_se_puede_marcar_leida_una_notificacion_ajena(cliente, auth, dos_usuarios):
    persistidas = [n for n in dos_usuarios["notificaciones"]["notificaciones"] if n["id"]]
    if not persistidas:
        pytest.skip("no hay notificaciones persistidas en este escenario")
    cab = auth(dos_usuarios["beto"]["access"])
    r = cliente.post(f"/api/v1/notificaciones/{persistidas[0]['id']}/leer", headers=cab)
    assert r.status_code == 404


def test_sin_token_no_se_entra(cliente, dos_usuarios):
    for ruta in ("/api/v1/dashboard", "/api/v1/quests", "/api/v1/perfil",
                 "/api/v1/auth/me", "/api/v1/auth/mis-datos"):
        assert cliente.get(ruta).status_code == 401


def test_un_token_manipulado_no_sirve(cliente, auth, dos_usuarios):
    bueno = dos_usuarios["ana"]["access"]
    # Cambiar un carácter de la firma invalida el token entero.
    manipulado = bueno[:-3] + ("abc" if not bueno.endswith("abc") else "xyz")
    r = cliente.get("/api/v1/auth/me", headers=auth(manipulado))
    assert r.status_code == 401


def test_el_correo_ajeno_no_se_expone_a_otros_participantes(cliente, crear_usuario, auth):
    """serialize_participacion devolvía el correo de cada participante a
    cualquier otro, no solo al creador: un dato personal de un tercero que no
    acordó compartirlo."""
    ana = crear_usuario(nombre="Ana")
    beto = crear_usuario(nombre="Beto")
    cab_ana, cab_beto = auth(ana["access"]), auth(beto["access"])

    meta = cliente.post("/api/v1/quests", headers=cab_ana, json={
        "nombre": "Compartida", "monto_objetivo": "500.00",
        "fecha_limite": _fecha(), "es_colaborativo": True,
    }).get_json()["quest"]["id"]

    cliente.post(f"/api/v1/quests/{meta}/colaboradores", headers=cab_ana,
                 json={"correo": beto["correo"]})
    inv = cliente.get("/api/v1/invitaciones", headers=cab_beto).get_json()["invitaciones"][0]
    cliente.post(f"/api/v1/invitaciones/{inv['id']}/aceptar", headers=cab_beto)

    for cab in (cab_ana, cab_beto):
        datos = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
        for p in datos["participaciones"]:
            assert "correo" not in p["usuario"], "el correo de un participante quedó expuesto"
