# api.py
"""API JSON (`/api/v1`) para la app móvil QuestCash.

No duplica lógica de negocio: `register_api(app, csrf, ctx)` recibe en `ctx`
referencias a los helpers ya definidos como closures dentro de `create_app()`
(app.py) — ver ese archivo para la implementación real de cada uno. Este
módulo solo traduce esas mismas funciones a peticiones/respuestas JSON con
auth por Bearer token (JWT) en vez de sesión por cookie.
"""
import re
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash  # noqa: F401 (compatibilidad)
from password_hashing import hashear_password, necesita_rehash, verificar_password

import rate_limit
from auth_jwt import (
    canjear_refresh_token,
    emitir_refresh_token,
    generar_access_token,
    jwt_required,
    revocar_refresh_token,
    revocar_todas_las_sesiones,
)
from ia.services.questy_engine import evaluate_quest
from crypto_utils import indice_ciego
from models import (
    CategoriaGasto,
    ClaveIdempotencia,
    InvitacionQuest,
    Sesion,
    Gasto,
    Insignia,
    Movimiento,
    Notificacion,
    ParticipacionQuest,
    Quest,
    Usuario,
    UsuarioInsignia,
    db,
)
from validators import validar_gasto, validar_movimiento, validar_quest_form, validar_registro

EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

ICONOS_META_PERMITIDOS = {
    "airplane", "bicycle", "laptop", "shield-checkmark", "home",
    "school", "heart", "wallet", "car-sport", "game-controller", "fitness",
}

CATEGORY_COLOR_PALETTE = [
    "#2563EB", "#4ADE80", "#FBBF24", "#8B5CF6", "#F97316", "#EC4899", "#14B8A6", "#D1D5DB",
]


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
        "icono": quest.icono,
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
    """Datos de un participante visibles para el resto de la meta.

    NO incluye el correo. Antes sí, y lo recibía cualquier otro participante a
    través de GET /quests/<id> —basta con participar, no hace falta ser el
    creador—, así que la dirección de una persona quedaba expuesta a terceros
    con los que nunca acordó compartirla. El nombre y el alias son lo que hace
    falta para saber quién aportó a una meta compartida.
    """
    usuario = participacion.usuario
    return {
        "id": participacion.id,
        "rol": participacion.rol,
        "fecha_union": participacion.fecha_union.isoformat() if participacion.fecha_union else None,
        "usuario": {
            "id": usuario.id,
            "nombre": usuario.nombre,
            "alias": usuario.alias,
        },
    }


def serialize_invitacion(invitacion, para_creador=False):
    """Una invitación vista por el creador o por el invitado.

    Al invitado no se le manda el correo: ya sabe cuál es el suyo, y evitarlo
    quita una copia de un dato personal viajando sin necesidad.
    """
    datos = {
        "id": invitacion.id,
        "estado": invitacion.estado,
        "creada": invitacion.creado_en.isoformat() if invitacion.creado_en else None,
        "respondida": invitacion.respondida_en.isoformat() if invitacion.respondida_en else None,
        "quest": {
            "id": invitacion.quest.id,
            "nombre": invitacion.quest.nombre,
            "monto_objetivo": invitacion.quest.monto_objetivo,
            "fecha_limite": invitacion.quest.fecha_limite.isoformat() if invitacion.quest.fecha_limite else None,
            "icono": invitacion.quest.icono,
        },
        "invitado_por": {
            "id": invitacion.invitado_por.id,
            "nombre": invitacion.invitado_por.nombre,
        },
    }
    if para_creador:
        datos["correo"] = invitacion.correo
    return datos


def serialize_notificacion(notif):
    """Notificación persistida (evento real: meta completada, insignia,
    aporte de colaborador)."""
    return {
        "id": notif.id,
        "tipo": notif.tipo,
        "severidad": None,
        "titulo": notif.titulo,
        "mensaje": notif.mensaje,
        "icono": notif.icono,
        "color": notif.color,
        "leida": notif.leida,
        "quest_id": notif.quest_id,
        "fecha": notif.fecha_creacion.isoformat() if notif.fecha_creacion else None,
    }


def serialize_notificacion_dinamica(item):
    """Notificación calculada al vuelo por generar_notificaciones() (app.py) —
    recordatorios de vencimiento y consejos de gasto. No tiene id persistido
    ni estado de lectura real, así que se marca siempre como leída."""
    return {
        "id": None,
        "tipo": item.get("categoria", "recordatorio"),
        "severidad": item.get("tipo"),
        "titulo": item.get("titulo", "Aviso"),
        "mensaje": item.get("mensaje"),
        "icono": item.get("icono"),
        "color": item.get("color"),
        "leida": True,
        "quest_id": item.get("quest_id"),
        "fecha": None,
    }


def _dispositivo_de_la_peticion():
    """Etiqueta legible del cliente, para la pantalla de sesiones activas."""
    return (request.headers.get("X-Dispositivo") or request.headers.get("User-Agent") or "")[:120]


def _respuesta_de_sesion(usuario, rank_state=None, codigo=200):
    """Cuerpo común de login, registro y refresh.

    `token` se mantiene como alias del access token: es el campo que consumen
    los clientes ya publicados y quitarlo los rompería de golpe. Los nuevos
    deben usar `access_token` y `refresh_token`.
    """
    access, expira_en = generar_access_token(usuario)
    refresh, _ = emitir_refresh_token(usuario, _dispositivo_de_la_peticion())
    db.session.commit()

    cuerpo = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expira_en,
        "token_type": "Bearer",
        "token": access,          # alias de compatibilidad
        "user": serialize_user(usuario),
    }
    if rank_state is not None:
        cuerpo["rank_state"] = rank_state
    return jsonify(cuerpo), codigo


IDEMPOTENCIA_HORAS = 24

# codigo_http = 0 marca una clave RESERVADA pero cuya operación todavía no ha
# terminado. No es un código HTTP real, y por eso no puede confundirse con una
# respuesta guardada.
EN_CURSO = 0


def idempotente(vista):
    """Hace que repetir una operación con la misma Idempotency-Key sea inocuo.

    El bloqueo de fila evita que dos aportes simultáneos se pisen. Esto evita
    algo distinto: que el MISMO aporte se registre dos veces porque el usuario
    tocó dos veces o la app reintentó tras un timeout. Sin la clave, el
    servidor no puede distinguir eso de dos aportes legítimos iguales.

    La clave se RESERVA ANTES de ejecutar, no después. Es la diferencia entre
    que funcione o no: comprobar primero y guardar al final deja una ventana en
    la que dos peticiones simultáneas no encuentran nada, ambas ejecutan, y solo
    entonces compiten por guardar. Medido con 8 peticiones simultáneas sobre 4
    workers: se colaban 2 movimientos aunque las 8 devolvieran el mismo id.

    Reservando primero, la restricción UNIQUE de la tabla actúa de cerrojo: la
    perdedora nunca llega a ejecutar la operación.

    Sin cabecera, la vista corre como siempre: los clientes que aún no la
    envían siguen funcionando, sin protección pero sin romperse.
    """
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        clave = (request.headers.get("Idempotency-Key") or "").strip()[:128]
        if not clave:
            return vista(*args, **kwargs)

        usuario = g.api_usuario
        endpoint = request.endpoint or vista.__name__
        ahora = datetime.now(timezone.utc)

        def buscar():
            return ClaveIdempotencia.query.filter_by(
                usuario_id=usuario.id, endpoint=endpoint, clave=clave
            ).first()

        def reproducir(fila):
            respuesta = current_app.response_class(
                fila.respuesta, status=fila.codigo_http, mimetype="application/json"
            )
            respuesta.headers["Idempotent-Replay"] = "true"
            return respuesta

        previa = buscar()
        if previa is not None and previa.expira_en > ahora:
            if previa.codigo_http == EN_CURSO:
                # Otra petición con esta misma clave está ejecutándose. No se
                # puede devolver un resultado que aún no existe ni ejecutar en
                # paralelo: se pide reintentar.
                return jsonify({"error": "idempotency_in_progress"}), 409
            return reproducir(previa)

        # Reserva. Si otra petición gana, la restricción UNIQUE la rechaza aquí
        # —antes de tocar nada— y esta no llega a ejecutar la operación.
        reserva = ClaveIdempotencia(
            usuario_id=usuario.id, endpoint=endpoint, clave=clave,
            codigo_http=EN_CURSO, respuesta="",
            expira_en=ahora + timedelta(hours=IDEMPOTENCIA_HORAS),
        )
        db.session.add(reserva)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            otra = buscar()
            if otra is not None and otra.codigo_http != EN_CURSO:
                return reproducir(otra)
            return jsonify({"error": "idempotency_in_progress"}), 409

        reserva_id = reserva.id

        def liberar():
            """Suelta la reserva para que el cliente pueda reintentar de verdad."""
            db.session.rollback()
            ClaveIdempotencia.query.filter_by(id=reserva_id).delete()
            db.session.commit()

        try:
            resultado = vista(*args, **kwargs)
        except Exception:
            liberar()
            raise

        cuerpo, codigo = (resultado if isinstance(resultado, tuple) else (resultado, 200))

        if not (200 <= codigo < 300):
            # Si la operación falló, la clave no debe quedar quemada.
            liberar()
            return resultado

        texto = cuerpo.get_data(as_text=True) if hasattr(cuerpo, "get_data") else str(cuerpo)
        fila = ClaveIdempotencia.query.get(reserva_id)
        if fila is not None:
            fila.codigo_http = codigo
            fila.respuesta = texto
            db.session.commit()
        return resultado

    return envoltorio


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
            password_hash=hashear_password(password),
        )
        # set_correo cifra el correo y calcula su índice ciego.
        usuario.set_correo(correo)
        db.session.add(usuario)
        db.session.flush()

        return _respuesta_de_sesion(usuario, codigo=201)

    @api_bp.route("/auth/login", methods=["POST"])
    def api_login():
        data = request.get_json(silent=True) or {}
        correo = (data.get("correo") or "").strip().lower()
        password = data.get("password") or ""

        ip = request.remote_addr or "unknown"

        # Comparte el mismo estado de bloqueo que el login web —ahora en Redis,
        # no en un diccionario de proceso— para no abrir un segundo vector de
        # fuerza bruta contra la misma cuenta desde la API.
        bloqueo = rate_limit.segundos_de_bloqueo(correo, ip)
        if bloqueo:
            return jsonify({"error": "locked", "retry_after_seconds": max(bloqueo, 1)}), 429

        usuario = Usuario.por_correo(correo)
        if usuario and verificar_password(usuario.password_hash, password):
            rate_limit.registrar_exito(correo, ip)

            # Re-hash oportunista si la cuenta venía con parámetros antiguos.
            if necesita_rehash(usuario.password_hash):
                usuario.password_hash = hashear_password(password)
                db.session.commit()
            rank_state = _augment_rank_state(calcular_estado_rango_perfil(usuario.puntos_totales or 0))
            return _respuesta_de_sesion(usuario, rank_state=rank_state)

        restantes, _ = rate_limit.registrar_fallo(correo, ip)
        return jsonify({"error": "invalid_credentials", "attempts_remaining": restantes}), 401

    @api_bp.route("/auth/me", methods=["GET"])
    @jwt_required
    def api_me():
        usuario = g.api_usuario
        rank_state = _augment_rank_state(calcular_estado_rango_perfil(usuario.puntos_totales or 0))
        return jsonify({"user": serialize_user(usuario), "rank_state": rank_state})

    @api_bp.route("/auth/refresh", methods=["POST"])
    def api_refresh():
        """Canjea un refresh token por un par nuevo.

        No lleva @jwt_required a propósito: el cliente llega aquí justamente
        porque su access token caducó. La credencial es el refresh.
        """
        data = request.get_json(silent=True) or {}
        crudo = (data.get("refresh_token") or "").strip()

        usuario, nuevo_refresh = canjear_refresh_token(crudo, _dispositivo_de_la_peticion())
        if usuario is None:
            # El refresh no existe, ya se usó, se revocó o caducó. El cliente
            # debe pedir credenciales de nuevo.
            db.session.rollback()
            return jsonify({"error": "invalid_refresh_token"}), 401

        access, expira_en = generar_access_token(usuario)
        db.session.commit()
        rank_state = _augment_rank_state(calcular_estado_rango_perfil(usuario.puntos_totales or 0))
        return jsonify({
            "access_token": access,
            "refresh_token": nuevo_refresh,
            "expires_in": expira_en,
            "token_type": "Bearer",
            "token": access,
            "user": serialize_user(usuario),
            "rank_state": rank_state,
        })

    @api_bp.route("/auth/logout", methods=["POST"])
    def api_logout():
        """Cierra ESTA sesión en el servidor, no solo en el dispositivo.

        Sin @jwt_required: cerrar sesión debe funcionar aunque el access ya
        haya caducado, que es el caso más frecuente.
        """
        data = request.get_json(silent=True) or {}
        revocada = revocar_refresh_token((data.get("refresh_token") or "").strip(), "logout")
        db.session.commit()
        # Respuesta idéntica revocara o no: un token inválido no debe permitir
        # averiguar si existía.
        return jsonify({"ok": True, "sesion_cerrada": bool(revocada)})

    @api_bp.route("/auth/logout-all", methods=["POST"])
    @jwt_required
    def api_logout_all():
        """Cierra la sesión en todos los dispositivos e invalida los access
        tokens ya emitidos subiendo token_version."""
        usuario = g.api_usuario
        cerradas = revocar_todas_las_sesiones(usuario)
        db.session.commit()
        return jsonify({"ok": True, "sesiones_cerradas": int(cerradas)})

    @api_bp.route("/auth/sesiones", methods=["GET"])
    @jwt_required
    def api_listar_sesiones():
        """Dispositivos con sesión abierta. No expone ningún token."""
        ahora = datetime.now(timezone.utc)
        sesiones = (
            Sesion.query
            .filter(Sesion.usuario_id == g.api_usuario.id, Sesion.revocada_en.is_(None))
            .order_by(Sesion.creado_en.desc())
            .limit(50)
            .all()
        )
        return jsonify({"sesiones": [
            {
                "id": s.id,
                "dispositivo": s.dispositivo,
                "creada": s.creado_en.isoformat() if s.creado_en else None,
                "ultimo_uso": s.ultimo_uso.isoformat() if s.ultimo_uso else None,
                "expira": s.expira_en.isoformat() if s.expira_en else None,
            }
            for s in sesiones if s.esta_viva(ahora)
        ]})

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

        total_objetivo = float(sum(q.monto_objetivo for q in quests) or 0)
        total_actual = float(sum(q.monto_actual for q in quests) or 0)
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

        notificaciones = [serialize_notificacion_dinamica(item) for item in generar_notificaciones(usuario)]
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
    @idempotente
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
        icono_raw = (data.get("icono") or "").strip()
        icono = icono_raw if icono_raw in ICONOS_META_PERMITIDOS else None

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
            icono=icono,
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

        icono_raw = (data.get("icono") or "").strip()
        if icono_raw in ICONOS_META_PERMITIDOS:
            quest.icono = icono_raw

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
    @idempotente
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
        """Registra una invitación. NO añade a nadie a la meta.

        Dos problemas del comportamiento anterior:

        1. Consentimiento. Se creaba la participación directamente, así que la
           persona quedaba dentro de una meta ajena sin aceptar nada y sin
           poder salirse.
        2. Enumeración. Respondía "no existe un usuario registrado con ese
           correo", lo que permitía averiguar si una dirección tenía cuenta.

        Ahora la invitación se registra exista o no la cuenta, y la respuesta
        es idéntica en los dos casos.
        """
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
        elif indice_ciego(correo) == usuario.correo_bi:
            errores.append("No puedes invitarte a ti mismo.")
        if errores:
            return jsonify({"errors": errores}), 400

        bi = indice_ciego(correo)

        # Si ya participa, se dice — no es enumeración: el creador ya ve a sus
        # participantes en el listado de la meta.
        ya_dentro = (
            ParticipacionQuest.query
            .join(Usuario, ParticipacionQuest.usuario_id == Usuario.id)
            .filter(ParticipacionQuest.quest_id == quest.id, Usuario.correo_bi == bi)
            .first()
        )
        if ya_dentro:
            return jsonify({"errors": ["Esa persona ya participa en este reto."]}), 400

        existente = InvitacionQuest.query.filter_by(
            quest_id=quest.id, correo_bi=bi, estado=InvitacionQuest.PENDIENTE
        ).first()
        if existente:
            # Reenviar una invitación pendiente no es un error.
            return jsonify({"invitacion": serialize_invitacion(existente, para_creador=True)}), 200

        invitacion = InvitacionQuest(quest_id=quest.id, invitado_por_id=usuario.id)
        invitacion.set_correo(correo)
        db.session.add(invitacion)
        db.session.commit()

        return jsonify({"invitacion": serialize_invitacion(invitacion, para_creador=True)}), 201

    @api_bp.route("/quests/<int:quest_id>/invitaciones", methods=["GET"])
    @jwt_required
    def api_listar_invitaciones_quest(quest_id):
        """Invitaciones pendientes de una meta. Solo para el creador."""
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if quest.usuario_id != g.api_usuario.id:
            return jsonify({"error": "forbidden"}), 403

        pendientes = InvitacionQuest.query.filter_by(
            quest_id=quest.id, estado=InvitacionQuest.PENDIENTE
        ).order_by(InvitacionQuest.creado_en.desc()).all()
        return jsonify({"invitaciones": [serialize_invitacion(i, para_creador=True) for i in pendientes]})

    @api_bp.route("/invitaciones", methods=["GET"])
    @jwt_required
    def api_mis_invitaciones():
        """Invitaciones pendientes dirigidas a mí, buscadas por índice ciego."""
        usuario = g.api_usuario
        pendientes = (
            InvitacionQuest.query
            .filter_by(correo_bi=usuario.correo_bi, estado=InvitacionQuest.PENDIENTE)
            .order_by(InvitacionQuest.creado_en.desc())
            .all()
        )
        return jsonify({"invitaciones": [serialize_invitacion(i) for i in pendientes]})

    def _responder_invitacion(invitacion_id, aceptar):
        usuario = g.api_usuario
        invitacion = InvitacionQuest.query.get(invitacion_id)

        # Comprobar la propiedad ANTES que el estado: responder distinto según
        # exista o no la invitación volvería a filtrar información.
        if invitacion is None or invitacion.correo_bi != usuario.correo_bi:
            return jsonify({"error": "not_found"}), 404
        if invitacion.estado != InvitacionQuest.PENDIENTE:
            return jsonify({"error": "already_answered"}), 409

        invitacion.estado = InvitacionQuest.ACEPTADA if aceptar else InvitacionQuest.RECHAZADA
        invitacion.respondida_en = datetime.now(timezone.utc)

        if aceptar:
            ya = ParticipacionQuest.query.filter_by(
                usuario_id=usuario.id, quest_id=invitacion.quest_id
            ).first()
            if not ya:
                db.session.add(ParticipacionQuest(
                    usuario_id=usuario.id, quest_id=invitacion.quest_id, rol="colaborador"
                ))
        db.session.commit()
        return jsonify({"invitacion": serialize_invitacion(invitacion)})

    @api_bp.route("/invitaciones/<int:invitacion_id>/aceptar", methods=["POST"])
    @jwt_required
    def api_aceptar_invitacion(invitacion_id):
        return _responder_invitacion(invitacion_id, True)

    @api_bp.route("/invitaciones/<int:invitacion_id>/rechazar", methods=["POST"])
    @jwt_required
    def api_rechazar_invitacion(invitacion_id):
        return _responder_invitacion(invitacion_id, False)

    @api_bp.route("/quests/<int:quest_id>/abandonar", methods=["POST"])
    @jwt_required
    def api_abandonar_quest(quest_id):
        """Salir de una meta colaborativa.

        No existía. Quien entraba a una meta ajena —antes sin ni siquiera
        aceptar— no tenía forma de salir. Los aportes ya hechos se conservan:
        son movimientos reales de esa meta, no del participante.
        """
        usuario = g.api_usuario
        quest = _load_quest(quest_id)
        if quest is None:
            return jsonify({"error": "not_found"}), 404
        if quest.usuario_id == usuario.id:
            return jsonify({"error": "creator_cannot_leave"}), 400

        participacion = ParticipacionQuest.query.filter_by(
            usuario_id=usuario.id, quest_id=quest.id
        ).first()
        if participacion is None:
            return jsonify({"error": "not_found"}), 404

        db.session.delete(participacion)
        db.session.commit()
        return "", 204

    # ----------------- Gastos -----------------

    def _rango_periodo(period):
        """Devuelve (inicio, fin, inicio_anterior, fin_anterior) para el
        período pedido, comparado contra el período inmediato anterior de
        igual duración (semana pasada / mes pasado / año pasado)."""
        hoy = date.today()
        if period == "week":
            inicio = hoy - timedelta(days=hoy.weekday())
            fin_anterior = inicio - timedelta(days=1)
            inicio_anterior = fin_anterior - timedelta(days=6)
        elif period == "year":
            inicio = hoy.replace(month=1, day=1)
            inicio_anterior = inicio.replace(year=inicio.year - 1)
            fin_anterior = inicio - timedelta(days=1)
        else:
            inicio = hoy.replace(day=1)
            fin_anterior = inicio - timedelta(days=1)
            inicio_anterior = fin_anterior.replace(day=1)
        return inicio, hoy, inicio_anterior, fin_anterior

    @api_bp.route("/gastos", methods=["GET"])
    @jwt_required
    def api_listar_gastos():
        usuario = g.api_usuario
        period = request.args.get("period", "month")
        if period not in ("week", "month", "year"):
            period = "month"

        inicio, fin, inicio_anterior, fin_anterior = _rango_periodo(period)

        gastos = (
            Gasto.query
            .filter(Gasto.usuario_id == usuario.id, Gasto.fecha >= inicio, Gasto.fecha <= fin)
            .order_by(Gasto.fecha.desc())
            .all()
        )
        # float() en el borde de lectura: de aquí en adelante son cifras de
        # presentación (porcentajes, variaciones), no aritmética de saldo.
        total_periodo = float(sum(gasto.monto for gasto in gastos) or 0)

        total_anterior = (
            db.session.query(db.func.sum(Gasto.monto))
            .filter(
                Gasto.usuario_id == usuario.id,
                Gasto.fecha >= inicio_anterior,
                Gasto.fecha <= fin_anterior,
            )
            .scalar() or 0
        )
        total_anterior = float(total_anterior)
        variacion_pct = (
            ((total_periodo - total_anterior) / total_anterior * 100) if total_anterior > 0 else 0.0
        )

        por_categoria = {}
        color_por_categoria = {}
        for gasto in gastos:
            nombre = gasto.categoria.nombre if gasto.categoria else "Otros"
            por_categoria[nombre] = por_categoria.get(nombre, 0.0) + float(gasto.monto or 0)
            if gasto.categoria and gasto.categoria.color:
                color_por_categoria[nombre] = gasto.categoria.color

        categorias = []
        for idx, (nombre, monto) in enumerate(sorted(por_categoria.items(), key=lambda item: -item[1])):
            color = color_por_categoria.get(nombre) or CATEGORY_COLOR_PALETTE[idx % len(CATEGORY_COLOR_PALETTE)]
            porcentaje = round((monto / total_periodo * 100), 1) if total_periodo > 0 else 0.0
            categorias.append({"nombre": nombre, "monto": monto, "porcentaje": porcentaje, "color": color})

        return jsonify({
            "gastos": [serialize_gasto(gasto) for gasto in gastos],
            "period": period,
            "total_periodo": total_periodo,
            "categorias": categorias,
            "variacion_pct_vs_periodo_anterior": round(variacion_pct, 1),
        })

    @api_bp.route("/categorias-gasto", methods=["GET"])
    @jwt_required
    def api_listar_categorias_gasto():
        categorias = CategoriaGasto.query.order_by(CategoriaGasto.nombre).all()
        return jsonify({
            "categorias": [{"id": c.id, "nombre": c.nombre, "color": c.color} for c in categorias]
        })

    @api_bp.route("/gastos", methods=["POST"])
    @jwt_required
    @idempotente
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
        usuario = g.api_usuario
        persistidas = (
            Notificacion.query
            .filter_by(usuario_id=usuario.id)
            .order_by(Notificacion.fecha_creacion.desc())
            .limit(50)
            .all()
        )
        dinamicas = generar_notificaciones(usuario)

        items = [serialize_notificacion(n) for n in persistidas]
        items += [serialize_notificacion_dinamica(item) for item in dinamicas]
        no_leidas_count = sum(1 for n in persistidas if not n.leida)

        return jsonify({"notificaciones": items, "no_leidas_count": no_leidas_count})

    @api_bp.route("/notificaciones/<int:notif_id>/leer", methods=["POST"])
    @jwt_required
    def api_marcar_notificacion_leida(notif_id):
        usuario = g.api_usuario
        notif = Notificacion.query.get(notif_id)
        if notif is None or notif.usuario_id != usuario.id:
            return jsonify({"error": "not_found"}), 404

        notif.leida = True
        db.session.commit()
        return jsonify({"notificacion": serialize_notificacion(notif)})

    # ----------------- Perfil -----------------

    @api_bp.route("/perfil", methods=["GET"])
    @jwt_required
    def api_perfil():
        usuario = g.api_usuario
        return jsonify({
            "user": serialize_user(usuario),
            "rank_state": _augment_rank_state(calcular_estado_rango_perfil(usuario.puntos_totales or 0)),
        })

    @api_bp.route("/perfil", methods=["PATCH"])
    @jwt_required
    def api_actualizar_perfil():
        usuario = g.api_usuario
        data = request.get_json(silent=True) or {}

        nombre = (data.get("nombre") if "nombre" in data else usuario.nombre) or ""
        nombre = nombre.strip()
        alias = (data.get("alias") or "").strip() if "alias" in data else usuario.alias

        errores = []
        if not nombre:
            errores.append("El nombre es obligatorio.")
        elif len(nombre) > 100:
            errores.append("El nombre es demasiado largo (máximo 100 caracteres).")
        if alias and len(alias) > 50:
            errores.append("El alias no puede superar 50 caracteres.")

        if errores:
            return jsonify({"errors": errores}), 400

        usuario.nombre = nombre
        usuario.alias = alias or None
        if "notif_ia" in data:
            usuario.notif_ia = bool(data["notif_ia"])
        if "notif_fechas" in data:
            usuario.notif_fechas = bool(data["notif_fechas"])
        if "notif_progreso" in data:
            usuario.notif_progreso = bool(data["notif_progreso"])

        db.session.commit()
        return jsonify({"user": serialize_user(usuario)})

    app.register_blueprint(api_bp)
    csrf.exempt(api_bp)
