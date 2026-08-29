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


def test_los_gastos_paginan_pero_el_total_no_miente(cliente, crear_usuario, auth):
    """Los agregados se calculan sobre TODOS los gastos del período.

    Paginar el cálculo daría un total que depende de cuántos elementos pidió el
    cliente, que es exactamente el tipo de número en el que un usuario no puede
    confiar.
    """
    u = crear_usuario(); cab = auth(u["access"])
    for _ in range(12):
        cliente.post("/api/v1/gastos", headers=cab,
                     json={"monto": "10.00", "descripcion": "x", "categoria": "Comida"})

    d = cliente.get("/api/v1/gastos?period=month&limit=5", headers=cab).get_json()
    assert len(d["gastos"]) == 5
    assert d["has_more"] is True
    assert d["total_periodo"] == 120.00, "el total debe cubrir los 12, no los 5 de la página"
    assert sum(c["monto"] for c in d["categorias"]) == 120.00


def test_toda_la_api_esta_documentada(aplicacion):
    """Un endpoint sin describir es un endpoint que nadie sabe usar.

    El generador falla si encuentra alguno, así que esta prueba lo detecta sin
    esperar al CI.
    """
    import json
    import re
    from pathlib import Path

    especificacion = json.loads(Path("docs/openapi.json").read_text(encoding="utf-8"))

    rutas_reales = set()
    for regla in aplicacion.url_map.iter_rules():
        if not str(regla).startswith("/api/v1/"):
            continue
        ruta = re.sub(r"<(?:int:)?(\w+)>", r"{\1}", str(regla)).replace("/api/v1", "")
        for metodo in regla.methods - {"HEAD", "OPTIONS"}:
            rutas_reales.add((metodo.lower(), ruta))

    documentadas = {(m, r) for r, ops in especificacion["paths"].items() for m in ops}

    faltan = rutas_reales - documentadas
    sobran = documentadas - rutas_reales
    assert not faltan, f"sin documentar: {sorted(faltan)}"
    assert not sobran, f"documentadas pero inexistentes: {sorted(sobran)}"

    sin_describir = [
        f"{m} {r}" for r, ops in especificacion["paths"].items()
        for m, o in ops.items() if o["summary"] == "(sin describir)"
    ]
    assert not sin_describir, f"sin descripción: {sin_describir}"
