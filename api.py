# api.py
"""API JSON (`/api/v1`) para la app móvil QuestCash.

No duplica lógica de negocio: `register_api(app, csrf, ctx)` recibe en `ctx`
referencias a los helpers ya definidos como closures dentro de `create_app()`
(app.py) — ver ese archivo para la implementación real de cada uno. Este
módulo solo traduce esas mismas funciones a peticiones/respuestas JSON con
auth por Bearer token (JWT) en vez de sesión por cookie.
"""
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from auth_jwt import generate_token, jwt_required
from ia.services.questy_engine import evaluate_quest
from models import (
    CategoriaGasto,
    Gasto,
    Insignia,
    Movimiento,
    ParticipacionQuest,
    Quest,
    Usuario,
    UsuarioInsignia,
    db,
)
from validators import validar_gasto, validar_movimiento, validar_quest_form, validar_registro

EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def serialize_user(usuario):
    return {
        "id": usuario.id,
        "nombre": usuario.nombre,
        "correo": usuario.correo,
        "alias": usuario.alias,
        "foto_perfil": usuario.foto_perfil,
        "puntos_totales": usuario.puntos_totales or 0,
        "fecha_registro": usuario.fecha_registro.isoformat() if usuario.fecha_registro else None,
        "notif_ia": usuario.notif_ia,
        "notif_fechas": usuario.notif_fechas,
        "notif_progreso": usuario.notif_progreso,
    }


def serialize_quest(quest):
    return {
        "id": quest.id,
        "nombre": quest.nombre,
        "descripcion": quest.descripcion,
        "monto_objetivo": quest.monto_objetivo,
        "monto_actual": quest.monto_actual,
        "fecha_limite": quest.fecha_limite.isoformat() if quest.fecha_limite else None,
        "fecha_creacion": quest.fecha_creacion.isoformat() if quest.fecha_creacion else None,
        "dificultad": quest.dificultad,
        "estatus": quest.estatus,
        "puntos_recompensa": quest.puntos_recompensa,
        "tipo": quest.tipo,
        "es_colaborativo": quest.es_colaborativo,
        "usuario_id": quest.usuario_id,
        "progreso_porcentaje": quest.progreso_porcentaje(),
    }


def serialize_movimiento(movimiento):
    return {
        "id": movimiento.id,
        "tipo": movimiento.tipo,
        "monto": movimiento.monto,
        "fecha": movimiento.fecha.isoformat() if movimiento.fecha else None,
        "nota": movimiento.nota,
        "categoria": movimiento.categoria,
        "usuario_id": movimiento.usuario_id,
        "quest_id": movimiento.quest_id,
    }


def serialize_gasto(gasto):
    return {
        "id": gasto.id,
        "monto": gasto.monto,
        "descripcion": gasto.descripcion,
        "fecha": gasto.fecha.isoformat() if gasto.fecha else None,
        "metodo_pago": gasto.metodo_pago,
        "es_hormiga": gasto.es_hormiga,
        "categoria": (
            {"id": gasto.categoria.id, "nombre": gasto.categoria.nombre}
            if gasto.categoria else None
        ),
    }


def serialize_insignia(insignia, obtenida, fecha_obtenida=None):
    return {
        "id": insignia.id,
        "codigo": insignia.codigo,
        "nombre": insignia.nombre,
        "descripcion": insignia.descripcion,
        "rareza": insignia.rareza,
        "icono": insignia.icono,
        "obtenida": obtenida,
        "fecha_obtenida": fecha_obtenida.isoformat() if fecha_obtenida else None,
    }


def serialize_participacion(participacion):
    return {
        "id": participacion.id,
        "rol": participacion.rol,
        "fecha_union": participacion.fecha_union.isoformat() if participacion.fecha_union else None,
        "usuario": {
            "id": participacion.usuario.id,
            "nombre": participacion.usuario.nombre,
            "correo": participacion.usuario.correo,
        },
    }


def register_api(app, csrf, ctx):
    api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

    PROFILE_RANKS = ctx["PROFILE_RANKS"]
    calcular_estado_rango_perfil = ctx["calcular_estado_rango_perfil"]
    obtener_quests_usuario = ctx["obtener_quests_usuario"]
    usuario_participa_en_quest = ctx["usuario_participa_en_quest"]
    generar_notificaciones = ctx["generar_notificaciones"]
    calcular_dificultad = ctx["calcular_dificultad"]
    calcular_puntos_quest = ctx["calcular_puntos_quest"]
    checar_insignias_por_evento = ctx["checar_insignias_por_evento"]
    calcular_rachas_usuario = ctx["calcular_rachas_usuario"]
    construir_questy_input = ctx["construir_questy_input"]
    analizar_habitos_ahorro = ctx["analizar_habitos_ahorro"]
    resumen_gastos_para_ia = ctx["resumen_gastos_para_ia"]
    generar_resumen_questy_usuario = ctx["generar_resumen_questy_usuario"]
    humanizar_segmento_questy = ctx["humanizar_segmento_questy"]
    obtener_o_crear_categoria_gasto = ctx["obtener_o_crear_categoria_gasto"]
    procesar_registro_movimiento = ctx["procesar_registro_movimiento"]
    intentos_login = ctx["intentos_login"]
    MAX_LOGIN_INTENTOS = ctx["MAX_LOGIN_INTENTOS"]
    BLOQUEO_MINUTOS = ctx["BLOQUEO_MINUTOS"]

    def _augment_rank_state(rank_state):
        """Añade `level`/`total_levels` (posición en PROFILE_RANKS) para que el
        cliente móvil pueda mapear el sistema de rangos a un "nivel" numérico
        sin tener que duplicar la tabla PROFILE_RANKS."""
        rank_state = dict(rank_state)
        idx = next(
            (i for i, r in enumerate(PROFILE_RANKS) if r["key"] == rank_state["current_key"]),
            0,
        )
        rank_state["level"] = idx + 1
        rank_state["total_levels"] = len(PROFILE_RANKS)
        return rank_state

    def _load_quest(quest_id):
        return Quest.query.get(quest_id)

    # ----------------- Auth -----------------

    @api_bp.route("/auth/register", methods=["POST"])
    def api_register():
        data = request.get_json(silent=True) or {}
        nombre = (data.get("nombre") or "").strip()
        correo = (data.get("correo") or "").strip().lower()
        password = data.get("password") or ""
        password2 = data.get("password2") or ""

        errores = validar_registro(nombre, correo, password, password2)
        if errores:
            return jsonify({"errors": errores}), 400

        usuario = Usuario(
            nombre=nombre,
            correo=correo,
            password_hash=generate_password_hash(password),
        )
        db.session.add(usuario)
        db.session.commit()

        token = generate_token(usuario.id)
        return jsonify({"token": token, "user": serialize_user(usuario)}), 201

    @api_bp.route("/auth/login", methods=["POST"])
    def api_login():
        data = request.get_json(silent=True) or {}
        correo = (data.get("correo") or "").strip().lower()
        password = data.get("password") or ""

        ip = request.remote_addr or "unknown"
        clave = f"{correo}|{ip}"
        ahora = datetime.utcnow()

        # Comparte el mismo estado de bloqueo que el login web (mismo dict en memoria),
        # para no abrir un segundo vector de fuerza bruta contra la misma cuenta.
        intento = intentos_login.get(clave)
        if intento and intento.get("bloqueado_hasta") and ahora < intento["bloqueado_hasta"]:
            restante = int((intento["bloqueado_hasta"] - ahora).total_seconds())
            return jsonify({"error": "locked", "retry_after_seconds": max(restante, 1)}), 429

        usuario = Usuario.query.filter_by(correo=correo).first()
        if usuario and check_password_hash(usuario.password_hash, password):
            intentos_login.pop(clave, None)
            token = generate_token(usuario.id)
            rank_state = _augment_rank_state(calcular_estado_rango_perfil(usuario.puntos_totales or 0))
            return jsonify({"token": token, "user": serialize_user(usuario), "rank_state": rank_state})

        intento = intentos_login.get(clave, {"intentos": 0, "bloqueado_hasta": None})
        intento["intentos"] = intento.get("intentos", 0) + 1
        if intento["intentos"] >= MAX_LOGIN_INTENTOS:
            intento["bloqueado_hasta"] = ahora + timedelta(minutes=BLOQUEO_MINUTOS)
        intentos_login[clave] = intento

        restantes = max(MAX_LOGIN_INTENTOS - intento["intentos"], 0)
        return jsonify({"error": "invalid_credentials", "attempts_remaining": restantes}), 401

    @api_bp.route("/auth/me", methods=["GET"])
    @jwt_required
    def api_me():
        usuario = g.api_usuario
        rank_state = _augment_rank_state(calcular_estado_rango_perfil(usuario.puntos_totales or 0))
        return jsonify({"user": serialize_user(usuario), "rank_state": rank_state})

    # ----------------- Dashboard -----------------

    @api_bp.route("/dashboard", methods=["GET"])
    @jwt_required
    def api_dashboard():
        usuario = g.api_usuario
        quests = obtener_quests_usuario(usuario)
        quests.sort(key=lambda q: q.fecha_limite)

        resultados_ia = analizar_habitos_ahorro(usuario)
        gastos_resumen = resumen_gastos_para_ia(usuario)

        # `generar_resumen_questy_usuario` (app.py) espera panel["quest"] como el
        # objeto Quest real, no como id — se arma así para esa llamada interna y
        # se serializa por separado para la respuesta JSON (ver questy_panels_json).
        questy_panels = []
        quests_activos_dashboard = [q for q in quests if q.estatus not in ["cancelado", "completado"]]
        for q in quests_activos_dashboard[:3]:
            try:
                questy_input = construir_questy_input(usuario, q)
                questy_result = evaluate_quest(questy_input).to_dict()
                questy_panels.append({
                    "quest": q,
                    "result": questy_result,
                    "segmento_legible": humanizar_segmento_questy(questy_result.get("segmento")),
                })
            except Exception:
                continue

        questy_home = generar_resumen_questy_usuario(usuario, resultados_ia, gastos_resumen, questy_panels)

        questy_panels_json = [
            {
                "quest_id": panel["quest"].id,
                "result": panel["result"],
                "segmento_legible": panel["segmento_legible"],
            }
            for panel in questy_panels
        ]

        # questy_home["meta_prioritaria"] es un objeto Quest crudo (no serializable);
        # se convierte a dict igual que el resto de las metas en la respuesta.
        meta_prioritaria_quest = questy_home.get("meta_prioritaria")
        questy_dashboard = {
            "alerta_principal": questy_home.get("alerta_texto"),
            "accion_principal": questy_home.get("accion_texto"),
            "consejo_principal": questy_home.get("consejo_texto"),
            "meta_prioritaria": serialize_quest(meta_prioritaria_quest) if meta_prioritaria_quest else None,
            "metas_resumen": questy_home.get("metas_resumen", []),
            "margen_redirigible": questy_home.get("margen_redirigible", 0.0),
            "tendencia_gasto": questy_home.get("tendencia_gasto"),
            "variacion_vs_mes_anterior": questy_home.get("variacion_vs_mes_anterior", 0.0),
            "porcentaje_ingreso_gastado": questy_home.get("porcentaje_ingreso_gastado", 0.0),
        }

        total_objetivo = sum(q.monto_objetivo for q in quests) or 0
        total_actual = sum(q.monto_actual for q in quests) or 0
        progreso_global = int(total_actual / total_objetivo * 100) if total_objetivo > 0 else 0

        completados = [q for q in quests if q.progreso_porcentaje() >= 100 or q.estatus == "completado"]
        activos = [q for q in quests if q not in completados]
        quest_mas_cercano = quests[0] if quests else None

        movimientos_recientes = (
            Movimiento.query
            .filter_by(usuario_id=usuario.id)
            .order_by(Movimiento.fecha.desc())
            .limit(5)
            .all()
        )

        notificaciones = generar_notificaciones(usuario)
        rachas = calcular_rachas_usuario(usuario)

        insignias_count = UsuarioInsignia.query.filter_by(usuario_id=usuario.id).count()

        return jsonify({
            "quests": [serialize_quest(q) for q in quests],
            "total_objetivo": total_objetivo,
            "total_actual": total_actual,
            "progreso_global": progreso_global,
            "activos": [serialize_quest(q) for q in activos],
            "completados": [serialize_quest(q) for q in completados],
            "quest_mas_cercano": serialize_quest(quest_mas_cercano) if quest_mas_cercano else None,
            "movimientos_recientes": [serialize_movimiento(m) for m in movimientos_recientes],
            "notificaciones": notificaciones,
            "racha_actual": rachas["racha_actual"],
            "mejor_racha": rachas["mejor_racha"],
            "questy_dashboard": questy_dashboard,
            "questy_panels": questy_panels_json,
            "insignias_count": insignias_count,
            "rank_state": _augment_rank_state(calcular_estado_rango_perfil(usuario.puntos_totales or 0)),
        })

    # ----------------- Quests -----------------

    @api_bp.route("/quests", methods=["GET"])
    @jwt_required
    def api_listar_quests():
        quests = obtener_quests_usuario(g.api_usuario)
        quests.sort(key=lambda q: q.fecha_limite)
        return jsonify({"quests": [serialize_quest(q) for q in quests]})

    @api_bp.route("/quests", methods=["POST"])
    @jwt_required
    def api_crear_quest():
        usuario = g.api_usuario
        data = request.get_json(silent=True) or {}
        nombre = (data.get("nombre") or "").strip()
        descripcion = (data.get("descripcion") or "").strip()
        monto_objetivo = str(data.get("monto_objetivo", "")).strip()
        monto_actual = str(data.get("monto_actual", "0")).strip()
        fecha_limite = (data.get("fecha_limite") or "").strip()
        es_colaborativo = bool(data.get("es_colaborativo"))
        tipo = "colaborativo" if es_colaborativo else "individual"

        errores, datos = validar_quest_form(
            nombre, monto_objetivo, monto_actual, fecha_limite, descripcion, tipo
        )
        if errores:
            return jsonify({"errors": errores}), 400

        fecha_creacion = date.today()
        dificultad_calc = calcular_dificultad(
            datos["monto_objetivo_float"], datos["fecha_limite_date"], fecha_creacion=fecha_creacion
        )
        puntos_base_calc = calcular_puntos_quest(
            datos["monto_objetivo_float"], datos["fecha_limite_date"], dificultad_calc, tipo,
            fecha_creacion=fecha_creacion,
        )

        nueva_quest = Quest(
            nombre=nombre,
            descripcion=descripcion,
            monto_objetivo=datos["monto_objetivo_float"],
            monto_actual=datos["monto_actual_float"],
            fecha_limite=datos["fecha_limite_date"],
            fecha_creacion=fecha_creacion,
            dificultad=dificultad_calc,
            estatus="pendiente",
            puntos_recompensa=puntos_base_calc,
            usuario_id=usuario.id,
            es_colaborativo=es_colaborativo,
            tipo=tipo,
        )
        db.session.add(nueva_quest)
        db.session.flush()

        try:
            questy_input = construir_questy_input(usuario, nueva_quest)
            questy_result = evaluate_quest(questy_input)
            nueva_quest.puntos_recompensa = questy_result.puntos_finales
        except Exception:
            nueva_quest.puntos_recompensa = puntos_base_calc

        db.session.add(ParticipacionQuest(usuario_id=usuario.id, quest_id=nueva_quest.id, rol="creador"))

        events = []
        checar_insignias_por_evento(usuario, "primer_reto_creado", events=events)

        db.session.commit()
        return jsonify({"quest": serialize_quest(nueva_quest), "events": events}), 201

    @api_bp.route("/quests/<int:quest_id>", methods=["GET"])
    @jwt_required
    def api_detalle_quest(quest_id):
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if not usuario_participa_en_quest(usuario, quest):
            return jsonify({"error": "forbidden"}), 403

        participaciones = ParticipacionQuest.query.filter_by(quest_id=quest.id).all()

        questy_result = None
        try:
            questy_input = construir_questy_input(usuario, quest)
            questy_result = evaluate_quest(questy_input).to_dict()
            questy_result["puntos_finales"] = int(quest.puntos_recompensa or 0)
        except Exception:
            questy_result = None

        return jsonify({
            "quest": serialize_quest(quest),
            "es_creador": quest.usuario_id == usuario.id,
            "participaciones": [serialize_participacion(p) for p in participaciones],
            "questy_result": questy_result,
        })

    @api_bp.route("/quests/<int:quest_id>", methods=["PUT"])
    @jwt_required
    def api_editar_quest(quest_id):
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if quest.usuario_id != usuario.id:
            return jsonify({"error": "forbidden"}), 403

        data = request.get_json(silent=True) or {}
        nombre = (data.get("nombre") or "").strip()
        descripcion = (data.get("descripcion") or "").strip()
        monto_objetivo = str(data.get("monto_objetivo", "")).strip()
        monto_actual = str(data.get("monto_actual", "0")).strip()
        fecha_limite = (data.get("fecha_limite") or "").strip()
        es_colaborativo = bool(data.get("es_colaborativo"))
        tipo = "colaborativo" if es_colaborativo else "individual"

        errores, datos = validar_quest_form(
            nombre, monto_objetivo, monto_actual, fecha_limite, descripcion, tipo
        )
        if errores:
            return jsonify({"errors": errores}), 400

        fecha_creacion = quest.fecha_creacion or date.today()
        dificultad_calc = calcular_dificultad(
            datos["monto_objetivo_float"], datos["fecha_limite_date"], fecha_creacion=fecha_creacion
        )
        puntos_base_calc = calcular_puntos_quest(
            datos["monto_objetivo_float"], datos["fecha_limite_date"], dificultad_calc, tipo,
            fecha_creacion=fecha_creacion,
        )

        quest.nombre = nombre
        quest.descripcion = descripcion
        quest.monto_objetivo = datos["monto_objetivo_float"]
        quest.monto_actual = datos["monto_actual_float"]
        quest.fecha_limite = datos["fecha_limite_date"]
        quest.dificultad = dificultad_calc
        quest.puntos_recompensa = puntos_base_calc
        quest.es_colaborativo = es_colaborativo
        quest.tipo = tipo

        try:
            questy_input = construir_questy_input(usuario, quest)
            questy_result = evaluate_quest(questy_input)
            quest.puntos_recompensa = questy_result.puntos_finales
        except Exception:
            quest.puntos_recompensa = puntos_base_calc

        db.session.commit()
        return jsonify({"quest": serialize_quest(quest)})

    @api_bp.route("/quests/<int:quest_id>/cancel", methods=["POST"])
    @jwt_required
    def api_cancelar_quest(quest_id):
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if quest.usuario_id != usuario.id:
            return jsonify({"error": "forbidden"}), 403

        if quest.estatus in ("cancelado", "completado"):
            return jsonify({"error": "cannot_cancel"}), 400

        quest.estatus = "cancelado"
        db.session.commit()
        return jsonify({"quest": serialize_quest(quest)})

    @api_bp.route("/quests/<int:quest_id>", methods=["DELETE"])
    @jwt_required
    def api_eliminar_quest(quest_id):
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if quest.usuario_id != usuario.id:
            return jsonify({"error": "forbidden"}), 403

        db.session.delete(quest)
        db.session.commit()
        return "", 204

    @api_bp.route("/quests/<int:quest_id>/movimientos", methods=["GET"])
    @jwt_required
    def api_listar_movimientos(quest_id):
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if not usuario_participa_en_quest(usuario, quest):
            return jsonify({"error": "forbidden"}), 403

        movimientos = (
            Movimiento.query
            .filter_by(quest_id=quest.id)
            .order_by(Movimiento.fecha.desc())
            .all()
        )
        return jsonify({"movimientos": [serialize_movimiento(m) for m in movimientos]})

    @api_bp.route("/quests/<int:quest_id>/movimientos", methods=["POST"])
    @jwt_required
    def api_crear_movimiento(quest_id):
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if not usuario_participa_en_quest(usuario, quest):
            return jsonify({"error": "forbidden"}), 403

        data = request.get_json(silent=True) or {}
        errores, datos = validar_movimiento(
            data.get("tipo", ""),
            str(data.get("monto", "")),
            data.get("nota", ""),
            data.get("categoria", "general"),
            quest,
        )
        if errores:
            return jsonify({"errors": errores}), 400

        events = []
        movimiento = procesar_registro_movimiento(
            usuario, quest, datos["tipo"], datos["monto_float"], datos["nota"], datos["categoria"],
            events=events,
        )
        db.session.commit()

        return jsonify({
            "movimiento": serialize_movimiento(movimiento),
            "quest": serialize_quest(quest),
            "events": events,
        }), 201

    @api_bp.route("/quests/<int:quest_id>/colaboradores", methods=["GET"])
    @jwt_required
    def api_listar_colaboradores(quest_id):
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if quest.usuario_id != usuario.id:
            return jsonify({"error": "forbidden"}), 403

        participaciones = ParticipacionQuest.query.filter_by(quest_id=quest.id).all()
        return jsonify({"participaciones": [serialize_participacion(p) for p in participaciones]})

    @api_bp.route("/quests/<int:quest_id>/colaboradores", methods=["POST"])
    @jwt_required
    def api_invitar_colaborador(quest_id):
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if quest.usuario_id != usuario.id:
            return jsonify({"error": "forbidden"}), 403
        if quest.tipo != "colaborativo":
            return jsonify({"error": "not_collaborative"}), 400

        data = request.get_json(silent=True) or {}
        correo = (data.get("correo") or "").strip().lower()

        errores = []
        if not correo:
            errores.append("Debes ingresar un correo para invitar a un colaborador.")
        elif len(correo) > 150:
            errores.append("El correo es demasiado largo (máximo 150 caracteres).")
        elif not re.match(EMAIL_REGEX, correo):
            errores.append("El correo no tiene un formato válido.")

        usuario_invitado = None
        if not errores:
            usuario_invitado = Usuario.query.filter_by(correo=correo).first()
            if not usuario_invitado:
                errores.append("No existe un usuario registrado con ese correo.")
            elif usuario_invitado.id == quest.usuario_id:
                errores.append("Tú ya eres el creador de este reto.")
            else:
                ya_participa = ParticipacionQuest.query.filter_by(
                    usuario_id=usuario_invitado.id, quest_id=quest.id
                ).first()
                if ya_participa:
                    errores.append("Ese usuario ya participa en este reto.")

        if errores:
            return jsonify({"errors": errores}), 400

        nueva_part = ParticipacionQuest(usuario_id=usuario_invitado.id, quest_id=quest.id, rol="colaborador")
        db.session.add(nueva_part)
        db.session.commit()

        return jsonify({"participacion": serialize_participacion(nueva_part)}), 201

    # ----------------- Gastos -----------------

    @api_bp.route("/gastos", methods=["GET"])
    @jwt_required
    def api_listar_gastos():
        usuario = g.api_usuario
        hoy = date.today()
        inicio_mes = hoy.replace(day=1)
        gastos = (
            Gasto.query
            .filter(Gasto.usuario_id == usuario.id, Gasto.fecha >= inicio_mes, Gasto.fecha <= hoy)
            .order_by(Gasto.fecha.desc())
            .all()
        )
        total_mes = sum(gasto.monto for gasto in gastos) or 0
        return jsonify({"gastos": [serialize_gasto(gasto) for gasto in gastos], "total_mes": total_mes})

    @api_bp.route("/gastos", methods=["POST"])
    @jwt_required
    def api_crear_gasto():
        usuario = g.api_usuario
        data = request.get_json(silent=True) or {}
        monto_str = str(data.get("monto", ""))
        descripcion = data.get("descripcion", "")
        fecha_str = data.get("fecha", "")
        categoria_nombre = (data.get("categoria") or "").strip()
        metodo_pago = (data.get("metodo_pago") or "").strip()
        es_hormiga_flag = bool(data.get("es_hormiga"))

        errores, datos = validar_gasto(monto_str, descripcion, fecha_str)
        if errores:
            return jsonify({"errors": errores}), 400

        categoria = obtener_o_crear_categoria_gasto(categoria_nombre)

        es_hormiga = es_hormiga_flag
        if not es_hormiga_flag:
            nombre_cat = (categoria.nombre or "").lower()
            if datos["monto"] <= 100 and any(
                x in nombre_cat for x in ["comida", "caf", "snack", "antojo", "dulce"]
            ):
                es_hormiga = True

        gasto = Gasto(
            usuario_id=usuario.id,
            categoria_id=categoria.id,
            monto=datos["monto"],
            descripcion=datos["descripcion"] or None,
            fecha=datos["fecha"],
            metodo_pago=metodo_pago or None,
            es_hormiga=es_hormiga,
        )
        db.session.add(gasto)
        db.session.commit()

        return jsonify({"gasto": serialize_gasto(gasto)}), 201

    # ----------------- Insignias -----------------

    @api_bp.route("/insignias", methods=["GET"])
    @jwt_required
    def api_listar_insignias():
        usuario = g.api_usuario
        todas_db = Insignia.query.order_by(Insignia.rareza, Insignia.nombre).all()

        insignias_limpias = []
        codigos_vistos = set()
        for ins in todas_db:
            if not ins.icono:
                continue
            codigo = ins.codigo or f"id-{ins.id}"
            if codigo in codigos_vistos:
                continue
            codigos_vistos.add(codigo)
            insignias_limpias.append(ins)

        rels = {
            r.insignia_id: r.fecha_obtenida
            for r in UsuarioInsignia.query.filter_by(usuario_id=usuario.id).all()
        }

        return jsonify({
            "insignias": [
                serialize_insignia(ins, ins.id in rels, rels.get(ins.id))
                for ins in insignias_limpias
            ]
        })

    # ----------------- Notificaciones -----------------

    @api_bp.route("/notificaciones", methods=["GET"])
    @jwt_required
    def api_notificaciones():
        return jsonify({"notificaciones": generar_notificaciones(g.api_usuario)})

    # ----------------- Perfil (solo lectura por ahora) -----------------

    @api_bp.route("/perfil", methods=["GET"])
    @jwt_required
    def api_perfil():
        usuario = g.api_usuario
        return jsonify({
            "user": serialize_user(usuario),
            "rank_state": _augment_rank_state(calcular_estado_rango_perfil(usuario.puntos_totales or 0)),
        })

    app.register_blueprint(api_bp)
    csrf.exempt(api_bp)
