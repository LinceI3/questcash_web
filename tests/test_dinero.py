"""Integridad de los importes.

Cada prueba de este archivo corresponde a un defecto REAL que existió en
QuestCash y que se corrigió durante la auditoría. No son hipótesis: son
regresiones que ya ocurrieron una vez.
"""
import datetime

import pytest


def _fecha(dias=90):
    return (datetime.date.today() + datetime.timedelta(days=dias)).isoformat()


def _crear_meta(cliente, cab, objetivo="5000.00"):
    r = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Meta", "monto_objetivo": objetivo, "fecha_limite": _fecha(),
    })
    assert r.status_code == 201, r.get_json()
    return r.get_json()["quest"]["id"]


# ---------------------------------------------------------------------------
#  NaN e infinitos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor", ["nan", "NaN", "-nan", "inf", "-inf", "Infinity", "sNaN"])
def test_monto_no_finito_se_rechaza_en_movimientos(cliente, crear_usuario, auth, valor):
    """float("nan") pasaba TODAS las validaciones.

    Toda comparación con NaN es falsa, así que ni `<= 0` ni `> 1e9` lo
    detenían. Entraba a la base y dejaba el monto de la meta corrupto de forma
    irreversible: progreso, estadísticas y puntos rotos sin manera de repararlo
    desde la aplicación.
    """
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)

    r = cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                     json={"tipo": "aporte", "monto": valor})
    assert r.status_code == 400

    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    assert detalle["quest"]["monto_actual"] == 0.0


@pytest.mark.parametrize("valor", ["nan", "inf", "-inf"])
def test_monto_no_finito_se_rechaza_en_gastos_y_metas(cliente, crear_usuario, auth, valor):
    u = crear_usuario(); cab = auth(u["access"])
    assert cliente.post("/api/v1/gastos", headers=cab,
                        json={"monto": valor, "descripcion": "x"}).status_code == 400
    assert cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "M", "monto_objetivo": valor, "fecha_limite": _fecha(),
    }).status_code == 400


# ---------------------------------------------------------------------------
#  Precisión decimal
# ---------------------------------------------------------------------------
def test_los_centavos_no_derivan(cliente, crear_usuario, auth):
    """Con Float, diez aportes de 0.10 daban 0.9999999999999999.

    El error de la coma flotante se ACUMULA en cada suma sobre el saldo. En una
    aplicación cuyo texto principal es "te faltan $X para tu meta", eso produce
    centavos que aparecen y desaparecen.
    """
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)

    for _ in range(10):
        r = cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                         json={"tipo": "aporte", "monto": "0.10"})
        assert r.status_code == 201

    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    assert detalle["quest"]["monto_actual"] == 1.00


def test_redondeo_a_centavos(cliente, crear_usuario, auth):
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "aporte", "monto": "0.005"})
    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    assert detalle["quest"]["monto_actual"] == 0.01


def test_el_saldo_cuadra_con_sus_movimientos(cliente, crear_usuario, auth):
    """El saldo de una meta debe ser siempre la suma de sus movimientos."""
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)

    for monto in ("100.33", "50.11", "0.01", "7.77"):
        cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                     json={"tipo": "aporte", "monto": monto})
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "retiro", "monto": "8.22"})

    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    movs = cliente.get(f"/api/v1/quests/{meta}/movimientos", headers=cab).get_json()

    suma = sum(
        (m["monto"] if m["tipo"] == "aporte" else -m["monto"])
        for m in movs["movimientos"]
    )
    assert round(suma, 2) == detalle["quest"]["monto_actual"] == 150.00


# ---------------------------------------------------------------------------
#  Idempotencia
# ---------------------------------------------------------------------------
def test_la_misma_clave_no_cobra_dos_veces(cliente, crear_usuario, auth):
    """Un doble toque o un reintento tras timeout registraban dos aportes.

    Desde el servidor son dos operaciones legítimas indistinguibles; solo la
    cabecera Idempotency-Key permite reconocerlas como la misma.
    """
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)
    cab_clave = {**cab, "Idempotency-Key": "clave-fija-de-prueba"}

    r1 = cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_clave,
                      json={"tipo": "aporte", "monto": "10.00"})
    r2 = cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_clave,
                      json={"tipo": "aporte", "monto": "10.00"})

    assert r1.status_code == r2.status_code == 201
    assert r2.headers.get("Idempotent-Replay") == "true"
    assert r1.get_json()["movimiento"]["id"] == r2.get_json()["movimiento"]["id"]

    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    assert detalle["quest"]["monto_actual"] == 10.00


def test_claves_distintas_son_operaciones_distintas(cliente, crear_usuario, auth):
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)
    for i in range(3):
        cliente.post(f"/api/v1/quests/{meta}/movimientos",
                     headers={**cab, "Idempotency-Key": f"clave-{i}"},
                     json={"tipo": "aporte", "monto": "5.00"})
    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    assert detalle["quest"]["monto_actual"] == 15.00


def test_una_operacion_fallida_no_quema_la_clave(cliente, crear_usuario, auth):
    """Si la operación falla, el cliente debe poder reintentar con la misma
    clave tras corregir el error."""
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)
    cab_clave = {**cab, "Idempotency-Key": "clave-tras-fallo"}

    assert cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_clave,
                        json={"tipo": "aporte", "monto": "nan"}).status_code == 400
    assert cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_clave,
                        json={"tipo": "aporte", "monto": "7.00"}).status_code == 201


def test_sin_cabecera_el_comportamiento_no_cambia(cliente, crear_usuario, auth):
    """Los clientes que aún no mandan la cabecera siguen funcionando."""
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)
    for _ in range(3):
        cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                     json={"tipo": "aporte", "monto": "1.00"})
    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    assert detalle["quest"]["monto_actual"] == 3.00


# ---------------------------------------------------------------------------
#  Reglas de negocio
# ---------------------------------------------------------------------------
def test_no_se_puede_retirar_mas_de_lo_ahorrado(cliente, crear_usuario, auth):
    u = crear_usuario(); cab = auth(u["access"])
    meta = _crear_meta(cliente, cab)
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "aporte", "monto": "50.00"})
    r = cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                     json={"tipo": "retiro", "monto": "51.00"})
    assert r.status_code == 400
