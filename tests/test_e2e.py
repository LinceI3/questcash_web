"""Recorrido completo de un usuario, en el orden en que ocurre de verdad.

Registro → login → crear meta → registrar gasto → aportar → ver progreso →
consultar estadísticas → recibir la lectura de Questy.

Es la prueba que dice si el producto funciona como producto, no si cada pieza
funciona por separado.
"""
import datetime


def test_recorrido_completo(cliente):
    hoy = datetime.date.today()
    limite = (hoy + datetime.timedelta(days=120)).isoformat()

    # --- 1. Registro -------------------------------------------------------
    r = cliente.post("/api/v1/auth/register", json={
        "nombre": "Ana Ahorradora", "correo": "ana.e2e@questcash.com",
        "password": "ClaveSegura99", "password2": "ClaveSegura99",
    })
    assert r.status_code == 201
    assert r.get_json()["access_token"]

    # --- 2. Login ----------------------------------------------------------
    r = cliente.post("/api/v1/auth/login", json={
        "correo": "ana.e2e@questcash.com", "password": "ClaveSegura99",
    })
    assert r.status_code == 200
    sesion = r.get_json()
    cab = {"Authorization": f"Bearer {sesion['access_token']}"}
    assert sesion["rank_state"]["current_name"] == "Recluta del Ahorro"
    assert sesion["rank_state"]["level"] == 1

    # --- 3. Crear una meta -------------------------------------------------
    r = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Laptop nueva", "descripcion": "Para la escuela",
        "monto_objetivo": "15000.00", "fecha_limite": limite, "icono": "laptop",
    })
    assert r.status_code == 201
    creada = r.get_json()
    meta = creada["quest"]["id"]
    assert creada["quest"]["puntos_recompensa"] > 0, "Questy debe puntuar la meta"
    # Crear la primera meta otorga una insignia, y el cliente debe recibirla.
    assert any(e["type"] == "insignia" and e["codigo"] == "PRIMERA_META"
               for e in creada["events"])

    # --- 4. Registrar un gasto ---------------------------------------------
    r = cliente.post("/api/v1/gastos", headers=cab, json={
        "monto": "85.50", "descripcion": "Comida fuera", "categoria": "Comida",
        "metodo_pago": "tarjeta",
    })
    assert r.status_code == 201

    # --- 5. Aportar --------------------------------------------------------
    r = cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab, json={
        "tipo": "aporte", "monto": "1200.50", "nota": "Primera quincena",
        "categoria": "ahorro_programado",
    })
    assert r.status_code == 201
    tras_aporte = r.get_json()
    assert tras_aporte["quest"]["monto_actual"] == 1200.50
    assert tras_aporte["quest"]["estatus"] == "en_progreso"

    # --- 6. Ver el progreso ------------------------------------------------
    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    assert detalle["quest"]["progreso_porcentaje"] == 8   # 1200.50 de 15000
    assert detalle["es_creador"] is True
    assert detalle["questy_result"] is not None, "Questy debe evaluar la meta"

    # --- 7. Dashboard y estadísticas ---------------------------------------
    tablero = cliente.get("/api/v1/dashboard", headers=cab).get_json()
    assert len(tablero["quests"]) == 1
    assert tablero["total_actual"] == 1200.50
    assert tablero["total_objetivo"] == 15000.00

    gastos = cliente.get("/api/v1/gastos?period=month", headers=cab).get_json()
    assert gastos["total_periodo"] == 85.50
    assert any(c["nombre"] == "Comida" for c in gastos["categorias"])

    # --- 8. Questy ---------------------------------------------------------
    assert tablero["questy_dashboard"] is not None
    questy = detalle["questy_result"]
    assert questy["segmento"].startswith("jovenes_")
    assert questy["puntos_finales"] > 0
    assert questy["questy_message"], "Questy debe decir algo al usuario"

    # --- 9. Insignias y notificaciones -------------------------------------
    insignias = cliente.get("/api/v1/insignias", headers=cab).get_json()["insignias"]
    obtenidas = {i["codigo"] for i in insignias if i["obtenida"]}
    assert {"PRIMERA_META", "PRIMER_AHORRO"} <= obtenidas

    notifs = cliente.get("/api/v1/notificaciones", headers=cab).get_json()
    assert isinstance(notifs["notificaciones"], list)

    # --- 10. Cerrar sesión de verdad ---------------------------------------
    assert cliente.post("/api/v1/auth/logout",
                        json={"refresh_token": sesion["refresh_token"]}).status_code == 200
    assert cliente.post("/api/v1/auth/refresh",
                        json={"refresh_token": sesion["refresh_token"]}).status_code == 401


def test_completar_una_meta_otorga_los_puntos_una_sola_vez(cliente, crear_usuario, auth):
    """`puntos_otorgados` existe justo para esto: alcanzar el objetivo dos
    veces —aportando, retirando y volviendo a aportar— no debe pagar doble."""
    u = crear_usuario(); cab = auth(u["access"])
    limite = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    meta = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Pequeña", "monto_objetivo": "100.00", "fecha_limite": limite,
    }).get_json()["quest"]["id"]

    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "aporte", "monto": "100.00"})
    puntos = cliente.get("/api/v1/perfil", headers=cab).get_json()["user"]["puntos_totales"]
    assert puntos > 0

    detalle = cliente.get(f"/api/v1/quests/{meta}", headers=cab).get_json()
    assert detalle["quest"]["estatus"] == "completado"

    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "retiro", "monto": "50.00"})
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "aporte", "monto": "50.00"})

    assert cliente.get("/api/v1/perfil", headers=cab).get_json()["user"]["puntos_totales"] == puntos


def test_aportar_de_mas_no_pasa_del_objetivo(cliente, crear_usuario, auth):
    u = crear_usuario(); cab = auth(u["access"])
    limite = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    meta = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "Pequeña", "monto_objetivo": "100.00", "fecha_limite": limite,
    }).get_json()["quest"]["id"]

    r = cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                     json={"tipo": "aporte", "monto": "250.00"})
    assert r.status_code == 201
    # El excedente se trunca: es una decisión de producto discutible, pero es
    # la que está, y esta prueba la deja fijada por escrito.
    assert r.get_json()["quest"]["monto_actual"] == 100.00
