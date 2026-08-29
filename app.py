# app.py
import json
import math
import os
from decimal import Decimal
from flask.json.provider import DefaultJSONProvider
from flask import (
    Flask,
    jsonify,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    session,
    g,
    abort,
)
from datetime import datetime, date, timedelta
from functools import wraps
import re

from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from flask_migrate import Migrate

from config import Config
from crypto_utils import indice_ciego
from models import (
    db,
    ClaveIdempotencia,
    InvitacionQuest,
    Quest,
    Sesion,
    TokenCorreo,
    Usuario,
    Movimiento,
    ParticipacionQuest,
    Insignia,
    UsuarioInsignia,
    CategoriaGasto,
    Gasto,
    Notificacion,
)

from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash  # noqa: F401 (compatibilidad)
from password_hashing import hashear_password, necesita_rehash, verificar_password
from ia.services.questy_engine import QuestyInput, evaluate_quest
from validators import (
    validar_password_nueva,
    validar_registro,
    validar_quest_form,
    validar_movimiento,
    validar_gasto,
)
import observabilidad
from api import register_api
from services import analisis
from services import gastos as gastos_svc
from services import metas as metas_svc
from services import movimientos as movimientos_svc
from services import insignias as insignias_svc
from services import puntos as puntos_svc
from services import rachas, rangos
import correo as correo_mod
import rate_limit
import tokens_correo
from auth_jwt import revocar_todas_las_sesiones

csrf = CSRFProtect()
migrate = Migrate()

# El control de intentos vive ahora en rate_limit.py, con el estado en Redis:
# el diccionario que había aquí no se compartía entre workers (cada uno daba
# sus propios 5 intentos) y no se limpiaba nunca (crecía sin límite con cada
# correo probado). Ver rate_limit.py para el detalle.
MAX_LOGIN_INTENTOS = rate_limit.MAX_INTENTOS
BLOQUEO_MINUTOS = rate_limit.BLOQUEO_SEGUNDOS // 60


# ----------------- Insignias: semillas y helpers -----------------
def seed_insignias():
    """Compatibilidad: el catálogo vive en services/insignias.py."""
    insignias_svc.sembrar()


RAREZA_COLORS = insignias_svc.COLOR_POR_RAREZA


def crear_notificacion(usuario, tipo, titulo, mensaje, icono=None, color=None, quest=None):
    """Crea una notificación persistida (evento real: meta completada,
    insignia nueva, aporte de un colaborador). Sin commit aquí; el caller
    es responsable, igual que otorgar_insignia."""
    notif = Notificacion(
        usuario_id=usuario.id,
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        icono=icono,
        color=color,
        quest_id=quest.id if quest is not None else None,
    )
    db.session.add(notif)
    return notif


def seed_insignias_si_faltan():
    """Siembra las insignias base. Es datos, no esquema: la ejecuta
    scripts/preparar_bd.py después de aplicar las migraciones, no el arranque
    de la aplicación. Idempotente."""
    seed_insignias()


class ProveedorJSONDinero(DefaultJSONProvider):
    """Serializa los importes Decimal como números JSON.

    Las columnas de dinero son Numeric y SQLAlchemy las devuelve como Decimal,
    que el serializador de Flask no sabe convertir. Se emiten como número —no
    como cadena— para no romper a los clientes que ya existen: la app móvil
    tipa estos campos como `number` (questcash_mobile/src/types).

    Es seguro: el defecto que corrige Numeric era el error ACUMULADO al sumar
    repetidamente sobre el saldo, y esa aritmética ahora ocurre en Decimal
    dentro de la base y de Python. Un importe suelto de dos decimales por
    debajo de 2^53 centavos viaja por un `double` de JSON sin perder nada.
    """

    @staticmethod
    def default(objeto):
        if isinstance(objeto, Decimal):
            return float(objeto)
        return DefaultJSONProvider.default(objeto)


def create_app():
    app = Flask(__name__)
    app.json = ProveedorJSONDinero(app)
    app.config.from_object(Config)

    # Detrás de un proxy inverso (el gateway Nginx, o el de Render), la
    # dirección que ve Flask es la del proxy, no la del usuario. Eso importa
    # porque el control de intentos de inicio de sesión agrupa por correo+IP:
    # con todas las peticiones llegando desde la misma IP, un atacante agota
    # los intentos de cualquier cuenta y de paso bloquea a los demás.
    #
    # ProxyFix hace que request.remote_addr y request.scheme salgan de
    # X-Forwarded-For / X-Forwarded-Proto. Va DESACTIVADO por omisión y se
    # activa con PROXY_FIX_HOPS=1: confiar en esas cabeceras sin un proxy
    # delante permitiría a cualquiera falsificar su IP enviándolas él mismo.
    saltos = int(os.environ.get("PROXY_FIX_HOPS", "0"))
    if saltos > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=saltos, x_proto=saltos, x_host=saltos)

    # Antes que nada: si algo falla al montar el resto, que quede registrado.
    observabilidad.init_app(app)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # ----------------- Cabeceras de seguridad -----------------
    #
    # Antes no se enviaba ninguna. Sin ellas, cualquier XSS futuro escala sin
    # fricción, la página se puede embeber en un iframe ajeno para engañar al
    # usuario, y el navegador adivina tipos de contenido que no debería.

    # Orígenes de los que la web carga hoy código y estilos. Se listan
    # explícitamente: cualquier otro queda bloqueado por el navegador.
    #
    # Ya no hay ningún origen externo: Bootstrap, sus iconos, three.js, GSAP y
    # vanilla-tilt se sirven desde static/vendor/. Eso cierra tres cosas de
    # golpe — el riesgo de que un CDN comprometido inyecte código en una app
    # financiera, la fuga de la IP de cada visitante a tres terceros no
    # declarados en ningún aviso de privacidad, y la dependencia de que esos
    # servicios sigan disponibles.
    #
    # 'unsafe-inline' sigue en script-src y style-src porque las plantillas
    # llevan bloques <script>, manejadores onclick y atributos style en línea.
    # Quitarlo exige moverlos a static/js/, y es lo único que falta para tener
    # una CSP estricta.
    CSP = "; ".join([
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self' data:",
        "img-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
    ])

    @app.after_request
    def cabeceras_de_seguridad(respuesta):
        respuesta.headers.setdefault("Content-Security-Policy", CSP)
        # No adivinar el tipo de contenido: evita que una imagen subida se
        # interprete como HTML o JavaScript.
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Redundante con frame-ancestors, pero lo entienden navegadores viejos.
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        # No filtrar la ruta completa al salir hacia un tercero.
        respuesta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # QuestCash no usa ninguna de estas capacidades.
        respuesta.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )

        # HSTS solo cuando la conexión ya es segura: enviarlo por HTTP no tiene
        # efecto, y activarlo en desarrollo sobre localhost dejaría el
        # navegador negándose a abrir http://localhost durante meses.
        if request.is_secure:
            respuesta.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return respuesta

    @app.context_processor
    def inject_csrf():
        # Permite usar {{ csrf_token() }} en las plantillas
        return dict(csrf_token=generate_csrf)

    # El escalafón y su aritmética viven en services/rangos.py: son funciones
    # puras y no tienen por qué estar dentro de una factory de Flask.
    PROFILE_RANKS = rangos.RANGOS
    obtener_rango_perfil = rangos.rango_de
    obtener_siguiente_rango_perfil = rangos.siguiente_rango
    calcular_estado_rango_perfil = rangos.estado

    def emitir_flash_logro(titulo, mensaje, extra=None):
        payload = {
            "title": titulo,
            "message": mensaje,
        }
        if extra:
            payload.update(extra)

        icono = payload.get("icono")
        if icono:
            icono_str = str(icono).strip()
            payload["icono"] = icono_str

            lower_icono = icono_str.lower()
            if lower_icono.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")):
                payload["icono_tipo"] = "imagen"
            else:
                payload["icono_tipo"] = "clase"
        else:
            payload["icono_tipo"] = None

        flash(payload, "achievement")

    def emitir_flash_subida_rango(estado_rango):
        if not estado_rango:
            return

        payload = {
            "title": "¡Subiste de rango!",
            "message": f"Ahora eres {estado_rango['current_name']}",
            "rank_name": estado_rango["current_name"],
            "rank_key": estado_rango["current_key"],
            "rank_color": estado_rango["current_color"],
            "rank_accent": estado_rango["current_accent"],
            "points": estado_rango["points"],
            "is_max_rank": estado_rango["is_max_rank"],
            "next_name": estado_rango.get("next_name"),
            "points_remaining": estado_rango.get("points_remaining", 0),
        }
        flash(payload, "rank_up")

    @app.context_processor
    def inject_rank_ui():
        if getattr(g, "usuario_actual", None) is None:
            return {
                "current_user_rank": None,
                "profile_ranks": PROFILE_RANKS,
            }

        estado_rango = calcular_estado_rango_perfil(
            getattr(g.usuario_actual, "puntos_totales", 0) or 0
        )
        return {
            "current_user_rank": estado_rango,
            "profile_ranks": PROFILE_RANKS,
        }

    # ----------------- Helpers de autenticación -----------------

    @app.before_request
    def cargar_usuario_actual():
        """Cargar el usuario logueado (si existe) en g.usuario_actual."""
        user_id = session.get("user_id")
        if user_id is None:
            g.usuario_actual = None
        else:
            g.usuario_actual = Usuario.query.get(user_id)

    def login_requerido(vista):
        """Decorator para proteger rutas que requieren login."""
        @wraps(vista)
        def wrapped_view(**kwargs):
            if g.usuario_actual is None:
                flash("Debes iniciar sesión para acceder a esta sección.", "warning")
                return redirect(url_for("login"))
            return vista(**kwargs)
        return wrapped_view

    # Helper: obtener todos los quests en los que participa el usuario (propios + colaborativos)
    # Efectos de interfaz que services/movimientos necesita disparar pero no
    # debe conocer: los avisos emergentes son cosa de la web.
    class _EfectosWeb(movimientos_svc.Efectos):
        emitir_flash_logro = staticmethod(lambda *a, **k: emitir_flash_logro(*a, **k))
        emitir_flash_subida_rango = staticmethod(lambda *a, **k: emitir_flash_subida_rango(*a, **k))
        crear_notificacion = staticmethod(lambda *a, **k: crear_notificacion(*a, **k))
        checar_insignias_por_evento = staticmethod(lambda *a, **k: checar_insignias_por_evento(*a, **k))

    _efectos_web = _EfectosWeb()

    def otorgar_puntos_por_completado(quest, events=None):
        return movimientos_svc.otorgar_puntos_por_completado(quest, events=events, efectos=_efectos_web)

    def otorgar_bonus_racha(usuario, rachas_antes, rachas_despues, events=None):
        return movimientos_svc.otorgar_bonus_racha(
            usuario, rachas_antes, rachas_despues, events=events, efectos=_efectos_web)

    def procesar_registro_movimiento(usuario, quest, tipo, monto_float, nota, categoria, events=None):
        return movimientos_svc.procesar_registro_movimiento(
            usuario, quest, tipo, monto_float, nota, categoria,
            events=events, efectos=_efectos_web)

    # ----------------- Lógica de negocio, en services/ -----------------
    #
    # Estas eran closures de casi mil líneas dentro de esta misma función. Se
    # mantienen los nombres locales para no reescribir las veintitantas vistas
    # que las usan, pero la implementación ya se puede importar y probar sin
    # levantar una aplicación Flask.
    obtener_quests_usuario = metas_svc.obtener_quests_usuario
    usuario_participa_en_quest = metas_svc.usuario_participa_en_quest
    bloquear_quest = metas_svc.bloquear_quest

    calcular_ingreso_mensual_usuario = analisis.calcular_ingreso_mensual_usuario
    calcular_gasto_mensual_usuario = analisis.calcular_gasto_mensual_usuario
    calcular_edad_usuario = analisis.calcular_edad_usuario
    contar_metas_completadas_usuario = analisis.contar_metas_completadas_usuario
    construir_questy_input = analisis.construir_questy_input
    humanizar_segmento_questy = analisis.humanizar_segmento_questy
    analizar_habitos_ahorro = analisis.analizar_habitos_ahorro
    resumen_gastos_para_ia = analisis.resumen_gastos_para_ia
    seleccionar_meta_prioritaria = analisis.seleccionar_meta_prioritaria
    generar_resumen_questy_usuario = analisis.generar_resumen_questy_usuario
    generar_consejos_financieros = analisis.generar_consejos_financieros
    simular_escenario_ahorro = analisis.simular_escenario_ahorro
    calcular_estadisticas = analisis.calcular_estadisticas
    generar_notificaciones = analisis.generar_notificaciones

    # ----------------- Notificaciones inteligentes -----------------

    # ----------------- Dificultad automática -----------------

    calcular_dificultad = puntos_svc.dificultad
    calcular_puntos_quest = puntos_svc.puntos_de_meta

    # ----------------- Rachas de ahorro: días consecutivos con aportes -----------------
    calcular_rachas_usuario = rachas.calcular_de_usuario

    def otorgar_insignia(codigo, usuario, events=None):
        """Delega en services/insignias. El aviso emergente es un efecto de la
        web, así que entra por callback y no ensucia el servicio."""
        def avisar(insignia):
            emitir_flash_logro(
                titulo="Logro desbloqueado",
                mensaje=insignia.nombre,
                extra={
                    "rareza": insignia.rareza,
                    "icono": insignia.icono,
                    "codigo": insignia.codigo,
                    "descripcion": insignia.descripcion,
                },
            )
        return insignias_svc.otorgar(
            codigo, usuario, events=events,
            al_otorgar=avisar, crear_notificacion=crear_notificacion,
        )

    def checar_insignias_por_evento(usuario, evento, quest=None, events=None):
        def avisar(insignia):
            emitir_flash_logro(
                titulo="Logro desbloqueado",
                mensaje=insignia.nombre,
                extra={
                    "rareza": insignia.rareza,
                    "icono": insignia.icono,
                    "codigo": insignia.codigo,
                    "descripcion": insignia.descripcion,
                },
            )
        return insignias_svc.revisar_evento(
            usuario, evento, quest=quest, events=events,
            al_otorgar=avisar, crear_notificacion=crear_notificacion,
        )

    # ----------------- Rutas de autenticación -----------------

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            correo = request.form.get("correo", "").strip().lower()
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")

            errores = validar_registro(nombre, correo, password, password2)

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("auth/register.html")

            nuevo_usuario = Usuario(
                nombre=nombre,
                password_hash=hashear_password(password),
            )
            # set_correo cifra el correo y calcula su índice ciego.
            nuevo_usuario.set_correo(correo)
            db.session.add(nuevo_usuario)
            db.session.commit()

            flash("Cuenta creada correctamente. Ahora inicia sesión ✨", "success")
            return redirect(url_for("login"))

        return render_template("auth/register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            correo = request.form.get("correo", "").strip().lower()
            password = request.form.get("password", "")

            ip = request.remote_addr or "unknown"

            bloqueo = rate_limit.segundos_de_bloqueo(correo, ip)
            if bloqueo:
                minutos_restantes = bloqueo // 60 + 1
                flash(
                    f"Has excedido el número de intentos. Intenta de nuevo en aproximadamente {minutos_restantes} minuto(s).",
                    "danger",
                )
                return render_template("auth/login.html")

            usuario = Usuario.por_correo(correo)

            if usuario and verificar_password(usuario.password_hash, password):
                # Login exitoso: se olvida todo lo anterior
                rate_limit.registrar_exito(correo, ip)

                # Si la cuenta traía un hash con parámetros antiguos, este es
                # el único momento en que existe la contraseña en claro:
                # se aprovecha para regenerarlo con la política vigente.
                if necesita_rehash(usuario.password_hash):
                    usuario.password_hash = hashear_password(password)
                    db.session.commit()

                session.clear()
                session["user_id"] = usuario.id
                flash(f"¡Bienvenido de nuevo, {usuario.nombre}!", "success")
                return redirect(url_for("dashboard"))
            else:
                faltan, bloqueado = rate_limit.registrar_fallo(correo, ip)
                if bloqueado:
                    flash(
                        "Demasiados intentos fallidos. Tu acceso se ha bloqueado temporalmente por unos minutos.",
                        "danger",
                    )
                else:
                    flash(
                        f"Correo o contraseña incorrectos. Intentos restantes antes de bloqueo: {faltan}.",
                        "danger",
                    )
                return render_template("auth/login.html")

        return render_template("auth/login.html")

    def eliminar_cuenta(usuario):
        """Borra la cuenta y todo lo que cuelga de ella, en orden.

        El borrado es real, no una marca de baja: es el derecho de cancelación,
        y una cuenta "dada de baja" que conserva los datos no lo satisface.

        El orden importa porque las cascadas del modelo colgaban de Quest, no
        de Usuario: borrar el usuario sin más habría dejado movimientos, gastos
        y notificaciones apuntando a un id inexistente.

        Las metas COLABORATIVAS de las que esta persona no es creadora NO se
        borran, y sus aportes tampoco: son movimientos de una meta que sigue
        viva y de la que otras personas dependen. Borrarlos descuadraría el
        saldo de terceros que no han pedido nada. Lo que se elimina es su
        participación y su vínculo con esos movimientos, reasignándolos a la
        meta en vez de a la persona.
        """
        # 1. Sesiones, tokens y claves de idempotencia: sin valor tras el borrado.
        Sesion.query.filter_by(usuario_id=usuario.id).delete(synchronize_session=False)
        TokenCorreo.query.filter_by(usuario_id=usuario.id).delete(synchronize_session=False)
        ClaveIdempotencia.query.filter_by(usuario_id=usuario.id).delete(synchronize_session=False)

        # 2. Invitaciones que envió y las que le enviaron a él.
        InvitacionQuest.query.filter_by(invitado_por_id=usuario.id).delete(synchronize_session=False)
        if usuario.correo_bi:
            InvitacionQuest.query.filter_by(correo_bi=usuario.correo_bi).delete(synchronize_session=False)

        # 3. Notificaciones, insignias y gastos: solo suyos, se van con él.
        Notificacion.query.filter_by(usuario_id=usuario.id).delete(synchronize_session=False)
        UsuarioInsignia.query.filter_by(usuario_id=usuario.id).delete(synchronize_session=False)
        Gasto.query.filter_by(usuario_id=usuario.id).delete(synchronize_session=False)

        # 4. Metas propias: al borrarlas caen en cascada sus movimientos y
        #    participaciones, incluidos los aportes de otros colaboradores.
        propias = Quest.query.filter_by(usuario_id=usuario.id).all()
        ids_propias = {q.id for q in propias}
        for quest in propias:
            db.session.delete(quest)

        # 5. Movimientos en metas AJENAS: se DESLIGAN, no se borran.
        #
        #    Borrarlos dejaría la meta compartida con un monto_actual que ya no
        #    cuadra con su historial de movimientos, y reduciría el progreso de
        #    personas que no han pedido nada. Poner usuario_id a NULL cumple el
        #    derecho de cancelación —el aporte deja de ser atribuible a nadie—
        #    sin descuadrar a terceros.
        consulta = Movimiento.query.filter(Movimiento.usuario_id == usuario.id)
        if ids_propias:
            consulta = consulta.filter(~Movimiento.quest_id.in_(ids_propias))
        consulta.update({"usuario_id": None}, synchronize_session=False)

        # 6. Participaciones en metas ajenas.
        ParticipacionQuest.query.filter_by(usuario_id=usuario.id).delete(synchronize_session=False)

        db.session.delete(usuario)

    def _url_app():
        """Base pública para los enlaces que van por correo.

        No se usa request.url_root: un enlace de recuperación construido con el
        Host que mandó el cliente permite envenenarlo apuntando a otro sitio.
        Se toma de la configuración del despliegue.
        """
        return os.environ.get("APP_URL", request.url_root).rstrip("/")

    @app.route("/recuperar", methods=["GET", "POST"])
    def recuperar_password():
        """Pide un enlace de recuperación.

        Responde SIEMPRE lo mismo, exista o no la cuenta. Antes no había forma
        de recuperar una contraseña: quien la olvidaba perdía la cuenta y todo
        su historial.
        """
        if request.method == "POST":
            correo_usuario = request.form.get("correo", "").strip().lower()
            ip = request.remote_addr or "unknown"

            # Limita el envío por correo+IP para que esto no sirva de
            # ametralladora de mensajes contra una dirección ajena.
            bloqueo = rate_limit.segundos_de_bloqueo(f"recuperar:{correo_usuario}", ip)
            if not bloqueo:
                usuario = Usuario.por_correo(correo_usuario)
                if usuario is not None:
                    crudo = tokens_correo.emitir(usuario, ip=ip)
                    db.session.commit()
                    enlace = f"{_url_app()}/recuperar/{crudo}"
                    correo_mod.enviar_recuperacion(
                        correo_usuario, enlace, tokens_correo.MINUTOS_VALIDEZ
                    )
                elif re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", correo_usuario or ""):
                    # Se manda un correo explicando que no hay cuenta. Es lo que
                    # permite dar la misma respuesta en pantalla sin dejar a
                    # nadie esperando un mensaje que nunca llega.
                    correo_mod.enviar_aviso_sin_cuenta(correo_usuario)
                rate_limit.registrar_fallo(f"recuperar:{correo_usuario}", ip)

            flash(
                "Si esa dirección tiene una cuenta en QuestCash, te enviamos un "
                "enlace para restablecer la contraseña. Revisa tu correo.",
                "info",
            )
            return redirect(url_for("login"))

        return render_template("auth/recuperar.html")

    @app.route("/recuperar/<token>", methods=["GET", "POST"])
    def restablecer_password(token):
        usuario, registro = tokens_correo.usuario_de(token)
        if usuario is None:
            flash(
                "Ese enlace ya no es válido. Puede que haya caducado o que ya se "
                "haya usado. Pide uno nuevo.",
                "danger",
            )
            return redirect(url_for("recuperar_password"))

        if request.method == "POST":
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")

            errores = validar_password_nueva(password, password2, usuario.nombre)
            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("auth/restablecer.html", token=token)

            usuario.password_hash = hashear_password(password)
            tokens_correo.consumir(registro)
            # Cambiar la contraseña cierra todas las sesiones: si alguien había
            # entrado con la contraseña vieja, deja de tener acceso ahora.
            revocar_todas_las_sesiones(usuario, "cambio_password")
            db.session.commit()

            correo_mod.enviar_password_cambiada(usuario.correo)
            session.clear()
            flash(
                "Tu contraseña se cambió y se cerraron todas las sesiones. "
                "Inicia sesión con la nueva.",
                "success",
            )
            return redirect(url_for("login"))

        return render_template("auth/restablecer.html", token=token)

    @app.route("/perfil/password", methods=["GET", "POST"])
    @login_requerido
    def cambiar_password():
        """Cambio de contraseña con sesión iniciada. Exige la actual."""
        if request.method == "POST":
            actual = request.form.get("password_actual", "")
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")

            errores = []
            if not verificar_password(g.usuario_actual.password_hash, actual):
                errores.append("La contraseña actual no es correcta.")
            errores += validar_password_nueva(password, password2, g.usuario_actual.nombre)

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("auth/cambiar_password.html")

            g.usuario_actual.password_hash = hashear_password(password)
            revocar_todas_las_sesiones(g.usuario_actual, "cambio_password")
            db.session.commit()
            correo_mod.enviar_password_cambiada(g.usuario_actual.correo)

            flash(
                "Contraseña actualizada. Se cerraron las sesiones abiertas en "
                "otros dispositivos.",
                "success",
            )
            return redirect(url_for("perfil"))

        return render_template("auth/cambiar_password.html")

    @app.route("/perfil/mis-datos")
    @login_requerido
    def exportar_mis_datos():
        """Descarga todo lo que QuestCash guarda de esta persona.

        Cubre el derecho de acceso y el de portabilidad: formato estructurado,
        legible y que el usuario puede llevarse.
        """
        usuario = g.usuario_actual
        datos = {
            "exportado": datetime.utcnow().isoformat(),
            "cuenta": {
                "nombre": usuario.nombre,
                "correo": usuario.correo,
                "alias": usuario.alias,
                "puntos_totales": usuario.puntos_totales,
                "fecha_registro": usuario.fecha_registro.isoformat() if usuario.fecha_registro else None,
            },
            "metas": [
                {"nombre": q.nombre, "descripcion": q.descripcion,
                 "monto_objetivo": str(q.monto_objetivo), "monto_actual": str(q.monto_actual),
                 "fecha_limite": q.fecha_limite.isoformat() if q.fecha_limite else None,
                 "estatus": q.estatus, "tipo": q.tipo}
                for q in obtener_quests_usuario(usuario)
            ],
            "movimientos": [
                {"tipo": m.tipo, "monto": str(m.monto), "nota": m.nota,
                 "categoria": m.categoria,
                 "fecha": m.fecha.isoformat() if m.fecha else None}
                for m in Movimiento.query.filter_by(usuario_id=usuario.id).all()
            ],
            "gastos": [
                {"monto": str(x.monto), "descripcion": x.descripcion,
                 "fecha": x.fecha.isoformat() if x.fecha else None,
                 "metodo_pago": x.metodo_pago,
                 "categoria": x.categoria.nombre if x.categoria else None}
                for x in Gasto.query.filter_by(usuario_id=usuario.id).all()
            ],
            "insignias": [
                {"codigo": ui.insignia.codigo, "nombre": ui.insignia.nombre,
                 "obtenida": ui.fecha_obtenida.isoformat() if ui.fecha_obtenida else None}
                for ui in UsuarioInsignia.query.filter_by(usuario_id=usuario.id).all()
            ],
        }
        respuesta = app.response_class(
            json.dumps(datos, ensure_ascii=False, indent=2, default=str),
            mimetype="application/json",
        )
        respuesta.headers["Content-Disposition"] = 'attachment; filename="questcash-mis-datos.json"'
        return respuesta

    @app.route("/perfil/eliminar", methods=["GET", "POST"])
    @login_requerido
    def eliminar_mi_cuenta():
        """Borra la cuenta. Exige la contraseña y escribir ELIMINAR.

        La contraseña porque el token o la cookie no bastan para algo
        irreversible; la palabra porque un clic accidental no debe destruir el
        historial financiero de nadie.
        """
        if request.method == "POST":
            password = request.form.get("password", "")
            confirmacion = request.form.get("confirmacion", "").strip().upper()

            errores = []
            if not verificar_password(g.usuario_actual.password_hash, password):
                errores.append("La contraseña no es correcta.")
            if confirmacion != "ELIMINAR":
                errores.append('Escribe ELIMINAR para confirmar.')

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("auth/eliminar_cuenta.html")

            eliminar_cuenta(g.usuario_actual)
            db.session.commit()
            session.clear()
            flash("Tu cuenta y todos tus datos se eliminaron.", "info")
            return redirect(url_for("login"))

        return render_template("auth/eliminar_cuenta.html")

    # ----------------- Salud -----------------
    #
    # Dos sondas distintas a propósito, porque responden preguntas distintas:
    #
    #   /health  ¿el proceso está vivo? No toca la base. Si esto falla, hay que
    #            reiniciar el contenedor.
    #   /ready   ¿puede atender tráfico? Comprueba la base. Si esto falla pero
    #            /health responde, el problema está fuera de la aplicación y
    #            reiniciarla no arregla nada.
    #
    # Confundirlas hace que un orquestador reinicie la aplicación en bucle
    # cuando lo que se cayó fue Postgres.

    @app.route("/health")
    def health():
        return jsonify({"estado": "vivo"})

    @app.route("/ready")
    def ready():
        detalles = {}
        listo = True

        try:
            db.session.execute(db.text("SELECT 1"))
            detalles["base_de_datos"] = "ok"
        except Exception as exc:
            detalles["base_de_datos"] = f"error: {type(exc).__name__}"
            listo = False

        try:
            import rate_limit
            almacen = rate_limit.almacen()
            detalles["estado_compartido"] = (
                "redis" if almacen.__class__.__name__ == "_AlmacenRedis" else "memoria"
            )
        except Exception as exc:
            detalles["estado_compartido"] = f"error: {type(exc).__name__}"
            # Sin Redis la aplicación sirve, pero el control de intentos deja
            # de compartirse: es degradación, no caída.

        return jsonify({"estado": "listo" if listo else "no listo", **detalles}), (200 if listo else 503)

    @app.route("/privacidad")
    def aviso_privacidad():
        """BORRADOR del aviso de privacidad. Ver la plantilla."""
        return render_template("legal/privacidad.html")

    @app.route("/terminos")
    def terminos():
        """BORRADOR de los términos y condiciones. Ver la plantilla."""
        return render_template("legal/terminos.html")

    @app.route("/logout")
    @login_requerido
    def logout():
        session.clear()
        flash("Sesión cerrada correctamente.", "info")
        return redirect(url_for("login"))

    # ----------------- Rutas principales -----------------

    @app.route("/")
    def home():
        if g.usuario_actual:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_requerido
    def dashboard():
        quests = obtener_quests_usuario(g.usuario_actual)

        quests.sort(key=lambda q: q.fecha_limite)

        # Núcleo lógico de Questy para dashboard
        resultados_ia = analizar_habitos_ahorro(g.usuario_actual)
        gastos_resumen = resumen_gastos_para_ia(g.usuario_actual)

        questy_panels = []
        quests_activos_dashboard = [q for q in quests if q.estatus not in ["cancelado", "completado"]]
        for q in quests_activos_dashboard[:3]:
            try:
                questy_input = construir_questy_input(g.usuario_actual, q)
                questy_result = evaluate_quest(questy_input).to_dict()
                questy_panels.append({
                    "quest": q,
                    "result": questy_result,
                    "segmento_legible": humanizar_segmento_questy(questy_result.get("segmento")),
                })
            except Exception:
                continue

        questy_home = generar_resumen_questy_usuario(
            g.usuario_actual,
            resultados_ia,
            gastos_resumen,
            questy_panels,
        )

        questy_dashboard = {
            "alerta_principal": questy_home.get("alerta_texto"),
            "accion_principal": questy_home.get("accion_texto"),
            "consejo_principal": questy_home.get("consejo_texto"),
            "meta_prioritaria": questy_home.get("meta_prioritaria"),
            "margen_redirigible": questy_home.get("margen_redirigible", 0.0),
            "tendencia_gasto": questy_home.get("tendencia_gasto"),
            "variacion_vs_mes_anterior": questy_home.get("variacion_vs_mes_anterior", 0.0),
            "porcentaje_ingreso_gastado": questy_home.get("porcentaje_ingreso_gastado", 0.0),
        }

        total_objetivo = float(sum(q.monto_objetivo for q in quests) or 0)
        total_actual = float(sum(q.monto_actual for q in quests) or 0)

        if total_objetivo > 0:
            progreso_global = int(total_actual / total_objetivo * 100)
        else:
            progreso_global = 0

        completados = [q for q in quests if q.progreso_porcentaje() >= 100 or q.estatus == "completado"]
        activos = [q for q in quests if q not in completados]

        quest_mas_cercano = quests[0] if quests else None

        movimientos_recientes = (
            Movimiento.query
            .filter_by(usuario_id=g.usuario_actual.id)
            .order_by(Movimiento.fecha.desc())
            .limit(5)
            .all()
        )

        notificaciones = generar_notificaciones(g.usuario_actual)

        # Calcular las rachas del usuario actual
        rachas = calcular_rachas_usuario(g.usuario_actual)

        return render_template(
            "dashboard.html",
            quests=quests,
            total_objetivo=total_objetivo,
            total_actual=total_actual,
            progreso_global=progreso_global,
            activos=activos,
            completados=completados,
            quest_mas_cercano=quest_mas_cercano,
            movimientos_recientes=movimientos_recientes,
            notificaciones=notificaciones,
            racha_actual=rachas["racha_actual"],
            mejor_racha=rachas["mejor_racha"],
            racha_ultimo_dia=rachas["ultimo_dia"],
            questy_dashboard=questy_dashboard,
            rank_state=calcular_estado_rango_perfil(getattr(g.usuario_actual, "puntos_totales", 0) or 0),
        )

    @app.route("/notificaciones")
    @login_requerido
    def ver_notificaciones():
        notificaciones = generar_notificaciones(g.usuario_actual)
        return render_template("notificaciones.html", notificaciones=notificaciones)
    @app.route("/ia", methods=["GET", "POST"])
    @login_requerido
    def asistente_ia():
        """
        Vista del asistente Questy:
        - GET: muestra análisis general, consejos y, si hay parámetros de simulación en la URL,
          recalcula el escenario.
        - POST: procesa el formulario del simulador y redirige (POST-Redirect-GET) para evitar
          el mensaje de reenvío de formulario al recargar.
        """
        resultados = analizar_habitos_ahorro(g.usuario_actual)
        consejos = generar_consejos_financieros(g.usuario_actual, resultados)
        resultado_simulador = None
        gastos_resumen = resumen_gastos_para_ia(g.usuario_actual)
        questy_panels = []
        quests_usuario = obtener_quests_usuario(g.usuario_actual)
        quests_activos = [q for q in quests_usuario if q.estatus not in ["cancelado", "completado"]]

        for q in quests_activos[:4]:
            try:
                questy_input = construir_questy_input(g.usuario_actual, q)
                questy_result = evaluate_quest(questy_input).to_dict()
                questy_panels.append({
                    "quest": q,
                    "result": questy_result,
                    "segmento_legible": humanizar_segmento_questy(questy_result.get("segmento")),
                })
            except Exception:
                continue

        questy_home = generar_resumen_questy_usuario(
            g.usuario_actual,
            resultados,
            gastos_resumen,
            questy_panels,
        )

        if request.method == "POST":
            # Leer datos del simulador
            quest_id_str = request.form.get("sim_quest_id", "").strip()
            monto_extra_str = request.form.get("sim_monto_extra", "").strip()
            frecuencia = request.form.get("sim_frecuencia", "diario").strip().lower()

            errores = []
            quest_id = None

            # Validar quest (solo ID aquí; acceso completo se revisa en GET)
            if not quest_id_str:
                errores.append("Debes seleccionar una meta para simular.")
            else:
                try:
                    quest_id = int(quest_id_str)
                except ValueError:
                    errores.append("Meta seleccionada no válida.")

            # Validar monto extra
            monto_extra = 0.0
            if not monto_extra_str:
                errores.append("Debes ingresar un monto extra para simular.")
            else:
                try:
                    monto_extra = float(monto_extra_str)
                    if monto_extra <= 0:
                        errores.append("El monto extra debe ser mayor a 0.")
                except ValueError:
                    errores.append("El monto extra debe ser un número válido.")

            # Validar frecuencia
            frecuencias_validas = {"diario", "semanal", "quincenal", "mensual"}
            if frecuencia not in frecuencias_validas:
                errores.append("Frecuencia no válida.")

            if errores:
                for e in errores:
                    flash(e, "danger")
                # Redirigimos sin parámetros para que el navegador ya no tenga un POST pendiente
                return redirect(url_for("asistente_ia"))
            else:
                # Redirigimos con parámetros en la URL para recalcular el escenario en GET
                return redirect(
                    url_for(
                        "asistente_ia",
                        sim_q=quest_id,
                        sim_m=monto_extra,
                        sim_f=frecuencia,
                    )
                )

        # --- GET: análisis normal + simulador opcional ---
        # Revisar si hay parámetros de simulación en la URL
        sim_q = request.args.get("sim_q")
        sim_m = request.args.get("sim_m")
        sim_f = request.args.get("sim_f", "diario").strip().lower()

        if sim_q and sim_m:
            try:
                quest_id = int(sim_q)
                monto_extra = float(sim_m)
                frecuencia = sim_f

                quest = Quest.query.get(quest_id)
                # Validar que la meta exista y que el usuario tenga acceso
                if quest and usuario_participa_en_quest(g.usuario_actual, quest):
                    resultado_simulador = simular_escenario_ahorro(
                        g.usuario_actual,
                        quest,
                        monto_extra,
                        frecuencia,
                    )
            except ValueError:
                # Si los parámetros vienen corruptos, simplemente ignoramos la simulación
                resultado_simulador = None

        return render_template(
            "ia.html",
            resumen=resultados["resumen_global"],
            analisis=resultados["analisis_por_quest"],
            recomendaciones=resultados["recomendaciones"],
            consejos_financieros=consejos,
            resultado_simulador=resultado_simulador,
            gastos_resumen=gastos_resumen,
            questy_panels=questy_panels,
            questy_home=questy_home,
            rank_state=calcular_estado_rango_perfil(getattr(g.usuario_actual, "puntos_totales", 0) or 0),
        )

    @app.route("/estadisticas")
    @login_requerido
    def ver_estadisticas():
        datos = calcular_estadisticas(g.usuario_actual)
        resultados_ia = analizar_habitos_ahorro(g.usuario_actual)

        return render_template(
            "estadisticas.html",
            resumen=datos["resumen"],
            serie_30=datos["serie_30_dias"],
            serie_metas=datos["serie_por_meta"],
            analisis=resultados_ia["analisis_por_quest"],
        )

    @app.route("/estadisticas/pdf")
    @login_requerido
    def exportar_estadisticas_pdf():
        """Vista imprimible para exportar estadísticas como PDF desde el navegador."""
        datos = calcular_estadisticas(g.usuario_actual)
        resultados_ia = analizar_habitos_ahorro(g.usuario_actual)
        gastos_resumen = resumen_gastos_para_ia(g.usuario_actual)
        rank_state = calcular_estado_rango_perfil(
            getattr(g.usuario_actual, "puntos_totales", 0) or 0
        )

        analisis_activos = [
            item for item in resultados_ia["analisis_por_quest"]
            if item["quest"].estatus not in ["cancelado", "completado"]
        ]

        meta_destacada = None
        if analisis_activos:
            meta_destacada = sorted(
                analisis_activos,
                key=lambda item: (
                    item.get("probabilidad_num", 0),
                    item.get("dias_restantes", 9999),
                    -item.get("faltante", 0),
                ),
            )[0]

        fecha_generacion = datetime.utcnow()

        return render_template(
            "estadisticas_pdf.html",
            usuario=g.usuario_actual,
            resumen=datos["resumen"],
            serie_30=datos["serie_30_dias"],
            serie_metas=datos["serie_por_meta"],
            analisis=resultados_ia["analisis_por_quest"],
            analisis_activos=analisis_activos,
            meta_destacada=meta_destacada,
            recomendaciones=resultados_ia["recomendaciones"],
            gastos_resumen=gastos_resumen,
            rank_state=rank_state,
            fecha_generacion=fecha_generacion,
        )

    def obtener_o_crear_categoria_gasto(nombre_raw, usuario=None):
        """Delega en services/gastos. Las categorías son del sistema o del
        usuario que las creó; ya no hay una tabla global escribible por todos."""
        return gastos_svc.obtener_o_crear(nombre_raw, usuario or g.usuario_actual)

    @app.route("/gastos")
    @login_requerido
    def listar_gastos():
        """Vista principal del módulo de gastos.
        Muestra los gastos del mes actual y el total gastado.
        """
        hoy = date.today()
        inicio_mes = hoy.replace(day=1)

        gastos = (
            Gasto.query
            .filter(
                Gasto.usuario_id == g.usuario_actual.id,
                Gasto.fecha >= inicio_mes,
                Gasto.fecha <= hoy,
            )
            .order_by(Gasto.fecha.desc())
            .all()
        )

        total_mes = float(sum(g.monto for g in gastos) or 0) if gastos else 0.0

        categorias = gastos_svc.visibles_para(g.usuario_actual)

        return render_template(
            "gastos/list.html",
            gastos=gastos,
            total_mes=total_mes,
            categorias=categorias,
        )

    @app.route("/gastos/nuevo", methods=["GET", "POST"])
    @login_requerido
    def nuevo_gasto():
        """Formulario rápido para registrar un gasto."""
        if request.method == "POST":
            monto_str = request.form.get("monto", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            fecha_str = request.form.get("fecha", "").strip()
            categoria_nombre = request.form.get("categoria", "").strip()
            metodo_pago = request.form.get("metodo_pago", "").strip()
            es_hormiga_flag = request.form.get("es_hormiga") == "on"

            errores, datos = validar_gasto(monto_str, descripcion, fecha_str)

            if errores:
                for e in errores:
                    flash(e, "danger")

                categorias = gastos_svc.visibles_para(g.usuario_actual)
                hoy_iso = date.today().strftime("%Y-%m-%d")
                return render_template(
                    "gastos/form.html",
                    categorias=categorias,
                    hoy_iso=hoy_iso,
                )

            # Obtener o crear categoría
            categoria = obtener_o_crear_categoria_gasto(categoria_nombre)

            # Heurística simple para marcar gasto hormiga
            es_hormiga = es_hormiga_flag
            if not es_hormiga_flag:
                nombre_cat = (categoria.nombre or "").lower()
                if datos["monto"] <= 100 and any(
                    x in nombre_cat
                    for x in ["comida", "caf", "snack", "antojo", "dulce"]
                ):
                    es_hormiga = True

            gasto = Gasto(
                usuario_id=g.usuario_actual.id,
                categoria_id=categoria.id,
                monto=datos["monto"],
                descripcion=datos["descripcion"] or None,
                fecha=datos["fecha"],
                metodo_pago=metodo_pago or None,
                es_hormiga=es_hormiga,
            )

            db.session.add(gasto)
            db.session.commit()

            flash("Gasto registrado correctamente 💸", "success")
            return redirect(url_for("listar_gastos"))

        # GET: cargar formulario
        categorias = gastos_svc.visibles_para(g.usuario_actual)
        hoy_iso = date.today().strftime("%Y-%m-%d")

        return render_template(
            "gastos/form.html",
            categorias=categorias,
            hoy_iso=hoy_iso,
        )
    # SALA DE TROFEOS / INSIGNIAS
    @app.route("/insignias")
    @login_requerido
    def mis_insignias():
        """
        Muestra la sala de trofeos sin duplicados y omitiendo las insignias viejas
        que no tienen icono 3D (las que aparecen con ícono roto).
        """

        # Todas las insignias de la BD
        todas_db = (
            Insignia.query
            .order_by(Insignia.rareza, Insignia.nombre)
            .all()
        )

        insignias_limpias = []
        codigos_vistos = set()

        for ins in todas_db:
            # 1) Saltar insignias antiguas sin icono 3D configurado
            if not ins.icono:
                continue

            # 2) Evitar duplicados por código (o por id si no tuviera código)
            codigo = ins.codigo or f"id-{ins.id}"
            if codigo in codigos_vistos:
                continue

            codigos_vistos.add(codigo)
            insignias_limpias.append(ins)

        # Insignias que ya tiene el usuario, pero solo contando las que existen en la sala actual
        rels = UsuarioInsignia.query.filter_by(usuario_id=g.usuario_actual.id).all()
        ids_disponibles = {ins.id for ins in insignias_limpias}
        obtenidas_ids = {
            r.insignia_id
            for r in rels
            if r.insignia_id in ids_disponibles
        }

        return render_template(
            "insignias.html",
            insignias=insignias_limpias,
            insignias_obtenidas_ids=obtenidas_ids,
        )

    # LISTAR QUESTS
    @app.route("/quests")
    @login_requerido
    def listar_quests():
        quests = obtener_quests_usuario(g.usuario_actual)
        quests.sort(key=lambda q: q.fecha_limite)
        return render_template("quests/list.html", quests=quests)

    # CREAR QUEST
    @app.route("/quests/nuevo", methods=["GET", "POST"])
    @login_requerido
    def crear_quest():
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            monto_objetivo = request.form.get("monto_objetivo", "").strip()
            monto_actual = request.form.get("monto_actual", "0").strip()
            fecha_limite = request.form.get("fecha_limite", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            es_colaborativo = request.form.get("es_colaborativo") == "on"
            tipo = "colaborativo" if es_colaborativo else "individual"

            errores, datos = validar_quest_form(
                nombre, monto_objetivo, monto_actual, fecha_limite, descripcion, tipo
            )

            if errores:
                for e in errores:
                    flash(e, "danger")
                hoy_iso = date.today().strftime("%Y-%m-%d")
                return render_template("quests/form.html", modo="crear", hoy_iso=hoy_iso)

            monto_objetivo_float = datos["monto_objetivo_float"]
            monto_actual_float = datos["monto_actual_float"]
            fecha_limite_date = datos["fecha_limite_date"]
            fecha_creacion = date.today()

            dificultad_calc = calcular_dificultad(
                monto_objetivo_float,
                fecha_limite_date,
                fecha_creacion=fecha_creacion,
            )

            puntos_base_calc = calcular_puntos_quest(
                monto_objetivo_float,
                fecha_limite_date,
                dificultad_calc,
                tipo,
                fecha_creacion=fecha_creacion,
            )

            nueva_quest = Quest(
                nombre=nombre,
                descripcion=descripcion,
                monto_objetivo=monto_objetivo_float,
                monto_actual=monto_actual_float,
                fecha_limite=fecha_limite_date,
                fecha_creacion=fecha_creacion,
                dificultad=dificultad_calc,
                estatus="pendiente",
                puntos_recompensa=puntos_base_calc,
                usuario_id=g.usuario_actual.id,
                es_colaborativo=es_colaborativo,
                tipo=tipo,
            )

            db.session.add(nueva_quest)
            db.session.flush()
            try:
                questy_input = construir_questy_input(g.usuario_actual, nueva_quest)
                questy_result = evaluate_quest(questy_input)
                nueva_quest.puntos_recompensa = questy_result.puntos_finales
            except Exception:
                nueva_quest.puntos_recompensa = puntos_base_calc

            participacion_creador = ParticipacionQuest(
                usuario_id=g.usuario_actual.id,
                quest_id=nueva_quest.id,
                rol="creador",
            )
            db.session.add(participacion_creador)

            # Insignia por primer reto creado (si aplica)
            checar_insignias_por_evento(g.usuario_actual, "primer_reto_creado")

            db.session.commit()

            flash("Reto de ahorro creado correctamente 🎯", "success")
            return redirect(url_for("listar_quests"))

        hoy_iso = date.today().strftime("%Y-%m-%d")
        return render_template("quests/form.html", modo="crear", hoy_iso=hoy_iso)

    # DETALLE QUEST
    @app.route("/quests/<int:quest_id>")
    @login_requerido
    def detalle_quest(quest_id):
        quest = Quest.query.get_or_404(quest_id)

        if not usuario_participa_en_quest(g.usuario_actual, quest):
            abort(403)

        es_creador = (quest.usuario_id == g.usuario_actual.id)

        participaciones = ParticipacionQuest.query.filter_by(quest_id=quest.id).all()

        questy_result = None
        try:
            questy_input = construir_questy_input(g.usuario_actual, quest)
            questy_result = evaluate_quest(questy_input).to_dict()
            questy_result["puntos_finales"] = int(quest.puntos_recompensa or 0)
        except Exception:
            questy_result = None

        return render_template(
            "quests/detail.html",
            quest=quest,
            es_creador=es_creador,
            participaciones=participaciones,
            questy_result=questy_result,
        )

    # EDITAR QUEST (solo creador)
    @app.route("/quests/<int:quest_id>/editar", methods=["GET", "POST"])
    @login_requerido
    def editar_quest(quest_id):
        quest = Quest.query.get_or_404(quest_id)

        if quest.usuario_id != g.usuario_actual.id:
            abort(403)
        hoy_iso = date.today().strftime("%Y-%m-%d")

        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            monto_objetivo = request.form.get("monto_objetivo", "").strip()
            monto_actual = request.form.get("monto_actual", "0").strip()
            fecha_limite = request.form.get("fecha_limite", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            es_colaborativo = request.form.get("es_colaborativo") == "on"
            tipo = "colaborativo" if es_colaborativo else "individual"
            cancelar = request.form.get("cancelar") == "on"

            errores, datos = validar_quest_form(
                nombre, monto_objetivo, monto_actual, fecha_limite, descripcion, tipo
            )

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("quests/form.html", modo="editar", quest=quest, hoy_iso=hoy_iso)

            monto_objetivo_float = datos["monto_objetivo_float"]
            monto_actual_float = datos["monto_actual_float"]
            fecha_limite_date = datos["fecha_limite_date"]
            fecha_creacion = quest.fecha_creacion or date.today()

            dificultad_calc = calcular_dificultad(
                monto_objetivo_float,
                fecha_limite_date,
                fecha_creacion=fecha_creacion,
            )

            puntos_base_calc = calcular_puntos_quest(
                monto_objetivo_float,
                fecha_limite_date,
                dificultad_calc,
                tipo,
                fecha_creacion=fecha_creacion,
            )

            quest.nombre = nombre
            quest.descripcion = descripcion
            quest.monto_objetivo = monto_objetivo_float
            quest.monto_actual = monto_actual_float
            quest.fecha_limite = fecha_limite_date
            quest.dificultad = dificultad_calc
            quest.puntos_recompensa = puntos_base_calc
            quest.es_colaborativo = es_colaborativo
            quest.tipo = tipo

            try:
                questy_input = construir_questy_input(g.usuario_actual, quest)
                questy_result = evaluate_quest(questy_input)
                quest.puntos_recompensa = questy_result.puntos_finales
            except Exception:
                quest.puntos_recompensa = puntos_base_calc

            # Cancelación manual
            if quest.estatus != "cancelado" and cancelar:
                quest.estatus = "cancelado"

            db.session.commit()
            flash("Reto de ahorro actualizado correctamente ✅", "success")
            return redirect(url_for("detalle_quest", quest_id=quest.id))

        return render_template("quests/form.html", modo="editar", quest=quest, hoy_iso=hoy_iso)

    # CANCELAR QUEST (solo creador)
    @app.route("/quests/<int:quest_id>/cancelar", methods=["GET", "POST"])
    @login_requerido
    def cancelar_quest(quest_id):
        quest = Quest.query.get_or_404(quest_id)

        # Solo el creador puede cancelar
        if quest.usuario_id != g.usuario_actual.id:
            abort(403)

        # Si aún no está cancelado ni completado, lo marcamos como cancelado
        if quest.estatus not in ["cancelado", "completado"]:
            quest.estatus = "cancelado"
            db.session.commit()
            flash("Reto de ahorro cancelado correctamente.", "info")
        else:
            flash("Este reto ya no se puede cancelar.", "warning")

        return redirect(url_for("detalle_quest", quest_id=quest.id))

    # ELIMINAR QUEST (solo creador)
    @app.route("/quests/<int:quest_id>/eliminar", methods=["GET", "POST"])
    @login_requerido
    def eliminar_quest(quest_id):
        quest = Quest.query.get_or_404(quest_id)

        if quest.usuario_id != g.usuario_actual.id:
            abort(403)

        if request.method == "POST":
            db.session.delete(quest)
            db.session.commit()
            flash("Reto de ahorro eliminado 🗑️", "warning")
            return redirect(url_for("listar_quests"))

        return render_template("quests/confirm_delete.html", quest=quest)

    # LISTAR MOVIMIENTOS DE UN QUEST
    @app.route("/quests/<int:quest_id>/movimientos")
    @login_requerido
    def listar_movimientos(quest_id):
        quest = Quest.query.get_or_404(quest_id)
        if not usuario_participa_en_quest(g.usuario_actual, quest):
            abort(403)

        movimientos = (
            Movimiento.query
            .filter_by(quest_id=quest.id)
            .order_by(Movimiento.fecha.desc())
            .all()
        )

        return render_template("movimientos/list.html", quest=quest, movimientos=movimientos)

    # CREAR MOVIMIENTO
    @app.route("/quests/<int:quest_id>/movimientos/nuevo", methods=["GET", "POST"])
    @login_requerido
    def nuevo_movimiento(quest_id):
        quest = Quest.query.get_or_404(quest_id)
        if not usuario_participa_en_quest(g.usuario_actual, quest):
            abort(403)

        if request.method == "POST":
            errores, datos = validar_movimiento(
                request.form.get("tipo", ""),
                request.form.get("monto", ""),
                request.form.get("nota", ""),
                request.form.get("categoria", "general"),
                quest,
            )

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("movimientos/form.html", quest=quest)

            procesar_registro_movimiento(
                g.usuario_actual, quest,
                datos["tipo"], datos["monto_float"], datos["nota"], datos["categoria"],
            )
            db.session.commit()

            flash("Movimiento registrado correctamente.", "success")
            return redirect(url_for("detalle_quest", quest_id=quest.id))

        return render_template("movimientos/form.html", quest=quest)

    # Alias para compatibilidad con plantillas antiguas:
    # permite usar url_for('crear_movimiento', quest_id=...)
    @app.route("/quests/<int:quest_id>/movimientos/crear", methods=["GET", "POST"])
    @login_requerido
    def crear_movimiento(quest_id):
        """Ruta completa para crear un movimiento (aporte/retiro) sin depender de nuevo_movimiento."""
        quest = Quest.query.get_or_404(quest_id)
        if not usuario_participa_en_quest(g.usuario_actual, quest):
            abort(403)

        if request.method == "POST":
            errores, datos = validar_movimiento(
                request.form.get("tipo", ""),
                request.form.get("monto", ""),
                request.form.get("nota", ""),
                request.form.get("categoria", "general"),
                quest,
            )

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("movimientos/form.html", quest=quest)

            procesar_registro_movimiento(
                g.usuario_actual, quest,
                datos["tipo"], datos["monto_float"], datos["nota"], datos["categoria"],
            )
            db.session.commit()

            flash("Movimiento registrado correctamente.", "success")
            return redirect(url_for("detalle_quest", quest_id=quest.id))

        return render_template("movimientos/form.html", quest=quest)

    # GESTIONAR COLABORADORES
    @app.route("/quests/<int:quest_id>/colaboradores", methods=["GET", "POST"])
    @login_requerido
    def gestionar_colaboradores(quest_id):
        quest = Quest.query.get_or_404(quest_id)

        # Sólo el creador puede gestionar colaboradores
        if quest.usuario_id != g.usuario_actual.id:
            abort(403)

        # Debe ser colaborativo
        if quest.tipo != "colaborativo":
            flash("Este reto no está configurado como colaborativo.", "warning")
            return redirect(url_for("detalle_quest", quest_id=quest.id))

        usuario_invitado = None

        if request.method == "POST":
            correo = request.form.get("correo", "").strip().lower()
            errores = []

            # 1) Requerido
            if not correo:
                errores.append("Debes ingresar un correo para invitar a un colaborador.")
            elif len(correo) > 150:
                errores.append("El correo es demasiado largo (máximo 150 caracteres).")
            else:
                # 2) Formato básico de email
                email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
                if not re.match(email_regex, correo):
                    errores.append("El correo no tiene un formato válido.")

            # 3) Reglas de negocio.
            #
            # NO se comprueba si la cuenta existe. Antes sí, y la respuesta
            # "No existe un usuario registrado con ese correo" convertía este
            # formulario en un oráculo para averiguar quién tiene cuenta en
            # QuestCash. La invitación se registra en los dos casos.
            bi = indice_ciego(correo)
            if not errores and bi == g.usuario_actual.correo_bi:
                errores.append("No puedes invitarte a ti mismo.")

            if not errores:
                ya_participa = (
                    ParticipacionQuest.query
                    .join(Usuario, ParticipacionQuest.usuario_id == Usuario.id)
                    .filter(ParticipacionQuest.quest_id == quest.id, Usuario.correo_bi == bi)
                    .first()
                )
                if ya_participa:
                    errores.append("Esa persona ya participa en este reto.")

            if errores:
                for e in errores:
                    flash(e, "danger")
            else:
                pendiente = InvitacionQuest.query.filter_by(
                    quest_id=quest.id, correo_bi=bi, estado=InvitacionQuest.PENDIENTE
                ).first()
                if pendiente is None:
                    invitacion = InvitacionQuest(
                        quest_id=quest.id, invitado_por_id=g.usuario_actual.id
                    )
                    invitacion.set_correo(correo)
                    db.session.add(invitacion)
                    db.session.commit()
                # Mismo mensaje exista o no la cuenta, y exista o no ya una
                # invitación pendiente: es lo que cierra la enumeración.
                flash(
                    "Invitación enviada. Aparecerá en el reto cuando la persona la acepte.",
                    "success",
                )

            return redirect(url_for("gestionar_colaboradores", quest_id=quest.id))

        participaciones = ParticipacionQuest.query.filter_by(quest_id=quest.id).all()
        invitaciones_pendientes = InvitacionQuest.query.filter_by(
            quest_id=quest.id, estado=InvitacionQuest.PENDIENTE
        ).order_by(InvitacionQuest.creado_en.desc()).all()
        return render_template(
            "quests/colaboradores.html",
            quest=quest,
            participaciones=participaciones,
            invitaciones_pendientes=invitaciones_pendientes,
        )

    @app.route("/perfil", methods=["GET", "POST"])
    @login_requerido
    def perfil():
        usuario = g.usuario_actual

        # Cargar preferencias actuales
        tema_actual = session.get("tema", "claro")

        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            alias = request.form.get("alias", "").strip()
            notif_ia = request.form.get("notif_ia") == "on"
            notif_fechas = request.form.get("notif_fechas") == "on"
            notif_progreso = request.form.get("notif_progreso") == "on"
            tema_nuevo = request.form.get("tema", "claro").strip()
            foto = request.files.get("foto")

            errores = []

            # Validar nombre
            if not nombre:
                errores.append("El nombre es obligatorio.")
            elif len(nombre) > 100:
                errores.append("El nombre es demasiado largo (máximo 100 caracteres).")

            # Validar alias
            if alias and len(alias) > 50:
                errores.append("El alias no puede superar 50 caracteres.")

            # Validar tema
            if tema_nuevo not in ["claro", "oscuro"]:
                errores.append("Tema inválido.")

            # Validar foto si se subió archivo
            if foto and foto.filename:
                filename = foto.filename.lower()
                ext = filename.rsplit(".", 1)[-1]
                if ext not in Config.ALLOWED_EXTENSIONS:
                    errores.append("Formato de imagen no permitido. Usa PNG, JPG o JPEG.")
                else:
                    # Guardar archivo con nombre único
                    import time
                    nuevo_nombre = f"user_{usuario.id}_{int(time.time())}.{ext}"
                    ruta = Config.UPLOAD_FOLDER

                    # Crear carpeta si no existe
                    import os
                    if not os.path.exists(ruta):
                        os.makedirs(ruta)

                    foto.save(os.path.join(ruta, nuevo_nombre))
                    usuario.foto_perfil = nuevo_nombre

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template(
                    "auth/perfil.html",
                    usuario=usuario,
                    tema_actual=tema_actual
                )

            # Guardar cambios
            usuario.nombre = nombre
            usuario.alias = alias
            usuario.notif_ia = notif_ia
            usuario.notif_fechas = notif_fechas
            usuario.notif_progreso = notif_progreso

            # Guardar tema en sesión
            session["tema"] = tema_nuevo

            db.session.commit()
            flash("Perfil actualizado correctamente 🎉", "success")
            return redirect(url_for("perfil"))

        return render_template(
            "auth/perfil.html",
            usuario=usuario,
            tema_actual=tema_actual
        )

    # ----------------- API JSON para la app móvil (/api/v1) -----------------
    api_ctx = {
        "PROFILE_RANKS": PROFILE_RANKS,
        "calcular_estado_rango_perfil": calcular_estado_rango_perfil,
        "calcular_estadisticas": calcular_estadisticas,
        "obtener_quests_usuario": obtener_quests_usuario,
        "usuario_participa_en_quest": usuario_participa_en_quest,
        "generar_notificaciones": generar_notificaciones,
        "calcular_dificultad": calcular_dificultad,
        "calcular_puntos_quest": calcular_puntos_quest,
        "checar_insignias_por_evento": checar_insignias_por_evento,
        "calcular_rachas_usuario": calcular_rachas_usuario,
        "construir_questy_input": construir_questy_input,
        "analizar_habitos_ahorro": analizar_habitos_ahorro,
        "resumen_gastos_para_ia": resumen_gastos_para_ia,
        "generar_resumen_questy_usuario": generar_resumen_questy_usuario,
        "humanizar_segmento_questy": humanizar_segmento_questy,
        "obtener_o_crear_categoria_gasto": obtener_o_crear_categoria_gasto,
        "eliminar_cuenta": eliminar_cuenta,
        "procesar_registro_movimiento": procesar_registro_movimiento,
        "MAX_LOGIN_INTENTOS": MAX_LOGIN_INTENTOS,
        "BLOQUEO_MINUTOS": BLOQUEO_MINUTOS,
    }
    register_api(app, csrf, api_ctx)

    # El esquema NO se toca al arrancar. Las migraciones son un paso
    # explícito del despliegue: `flask db upgrade`, que corre
    # scripts/preparar_bd.py desde wait-for-db.sh antes de levantar gunicorn.
    #
    # Antes aquí vivían db.create_all() + un ALTER TABLE best-effort. Eso no
    # dejaba historial, no se podía revertir ni revisar en un pull request, y
    # con varios workers los procesos competían ejecutando DDL a la vez.
    return app

app = create_app()

if __name__ == "__main__":
    # SERVIDOR DE DESARROLLO ÚNICAMENTE.
    #
    # En producción la aplicación la sirve gunicorn como `app:app` (ver
    # Dockerfile y docker-compose.segmentado.yml). El servidor de Werkzeug es
    # mono-hilo, no soporta carga real y —con debug activo— publica una consola
    # interactiva que ejecuta código Python arbitrario en el contenedor.
    #
    # Por eso el modo debug ya no viene activado por omisión: hay que pedirlo
    # explícitamente con FLASK_DEBUG=1, y solo en la máquina de desarrollo.
    #
    #     FLASK_DEBUG=1 PORT=5001 python app.py
    #
    # Se mantiene 0.0.0.0 por omisión para que la app móvil siga alcanzando
    # este servidor desde un teléfono de la red local durante el desarrollo.
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 5000)),
        debug=debug,
    )