"""Paginación por cursor y endpoint de estadísticas."""
import datetime


def _fecha(dias=90):
    return (datetime.date.today() + datetime.timedelta(days=dias)).isoformat()


def _meta_con_movimientos(cliente, cab, n):
    meta = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Con historial", "monto_objetivo": "100000.00", "fecha_limite": _fecha(),
    }).get_json()["quest"]["id"]
    for _ in range(n):
        cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                     json={"tipo": "aporte", "monto": "1.00"})
    return meta


def test_paginacion_recorre_todo_sin_repetir_ni_saltar(cliente, crear_usuario, auth):
    """Se usa cursor y no offset porque con offset, insertar una fila mientras
    alguien pagina desplaza el resto y repite o salta elementos."""
    u = crear_usuario(); cab = auth(u["access"])
    meta = _meta_con_movimientos(cliente, cab, 25)

    vistos, cursor, paginas = [], None, 0
    while True:
        url = f"/api/v1/quests/{meta}/movimientos?limit=10"
        if cursor:
            url += f"&cursor={cursor}"
        d = cliente.get(url, headers=cab).get_json()
        vistos += [m["id"] for m in d["movimientos"]]
        paginas += 1
        if not d["has_more"]:
            break
        cursor = d["next_cursor"]
        assert paginas < 10, "la paginación no termina"

    assert len(vistos) == 25
    assert len(set(vistos)) == 25, "hay elementos repetidos entre páginas"
    assert paginas == 3


def test_el_limite_tiene_tope(cliente, crear_usuario, auth):
    """Sin tope, un cliente puede pedir toda la tabla en una petición."""
    u = crear_usuario(); cab = auth(u["access"])
    meta = _meta_con_movimientos(cliente, cab, 5)
    d = cliente.get(f"/api/v1/quests/{meta}/movimientos?limit=99999", headers=cab).get_json()
    assert d["limit"] <= 200


def test_un_cursor_invalido_no_revienta(cliente, crear_usuario, auth):
    u = crear_usuario(); cab = auth(u["access"])
    meta = _meta_con_movimientos(cliente, cab, 3)
    r = cliente.get(f"/api/v1/quests/{meta}/movimientos?cursor=basura", headers=cab)
    assert r.status_code == 200
    assert len(r.get_json()["movimientos"]) == 3


def test_estadisticas_para_la_app_movil(cliente, crear_usuario, auth):
    """calcular_estadisticas() existía desde el principio pero solo la usaba la
    vista HTML: la app móvil no podía construir su pantalla."""
    u = crear_usuario(); cab = auth(u["access"])
    meta = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Con datos", "monto_objetivo": "1000.00", "fecha_limite": _fecha(),
    }).get_json()["quest"]["id"]
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "aporte", "monto": "120.00"})

    r = cliente.get("/api/v1/estadisticas", headers=cab)
    assert r.status_code == 200
    d = r.get_json()

    assert d["resumen"]["total_ahorrado"] == 120.00
    assert d["resumen"]["num_aportes"] == 1
    assert d["resumen"]["metas_activas"] == 1
    assert d["resumen"]["racha_actual"] == 1
    assert d["serie_30_dias"]["labels"] and d["serie_30_dias"]["data"]
    assert "Con datos" in d["serie_por_meta"]["labels"]


def test_las_estadisticas_no_cruzan_usuarios(cliente, crear_usuario, auth):
    ana, beto = crear_usuario(nombre="Ana"), crear_usuario(nombre="Beto")
    cab_ana, cab_beto = auth(ana["access"]), auth(beto["access"])
    meta = cliente.post("/api/v1/quests", headers=cab_ana, json={
        "nombre": "De Ana", "monto_objetivo": "1000.00", "fecha_limite": _fecha(),
    }).get_json()["quest"]["id"]
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab_ana,
                 json={"tipo": "aporte", "monto": "500.00"})

    d = cliente.get("/api/v1/estadisticas", headers=cab_beto).get_json()
    assert d["resumen"]["total_ahorrado"] == 0
    assert d["serie_por_meta"]["labels"] == []
