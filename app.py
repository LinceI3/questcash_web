# app.py
import math
from flask import (
    Flask,
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

from config import Config
from models import (
    db,
    Quest,
    Usuario,
    Movimiento,
    ParticipacionQuest,
    Insignia,
    UsuarioInsignia,
    CategoriaGasto,
    Gasto,
)

from werkzeug.security import generate_password_hash, check_password_hash


csrf = CSRFProtect()

# ----------------- Control de intentos de login (anti fuerza bruta) -----------------
MAX_LOGIN_INTENTOS = 5
BLOQUEO_MINUTOS = 5
intentos_login = {}  # clave: correo+ip, valor: {"intentos": int, "bloqueado_hasta": datetime}


# ----------------- Insignias: semillas y helpers -----------------
def seed_insignias():
    """Crea un set básico de insignias si no existen."""
    base = [
        {
            "codigo": "PRIMER_AHORRO",
            "nombre": "Primer ahorro registrado",
            "descripcion": "Registraste tu primer aporte de ahorro.",
            "rareza": "común",
            "icono": "primer_ahorro.png",
        },
        {
            "codigo": "PRIMERA_META",
            "nombre": "Primera meta creada",
            "descripcion": "Creaste tu primera meta en QuestCash.",
            "rareza": "rara",
            "icono": "Primera_meta.png",
        },
        {
            "codigo": "PRIMER_RETO",
            "nombre": "Primer reto completado",
            "descripcion": "Completaste tu primer reto de ahorro.",
            "rareza": "épica",
            "icono": "primer_reto.png",
        },
        {
            "codigo": "AHORRO_1000",
            "nombre": "Has ahorrado $1,000 MXN",
            "descripcion": "Alcanzaste un total acumulado de $1,000 MXN.",
            "rareza": "legendaria",
            "icono": "Ahorro_1000.png",
        },
        {
            "codigo": "META_A_TIEMPO",
            "nombre": "Meta cumplida a tiempo",
            "descripcion": "Completaste un reto antes o justo en la fecha límite.",
            "rareza": "mítica",
            "icono": "Meta_tiempo.png",
        },
    ]

    for data in base:
        if not Insignia.query.filter_by(codigo=data["codigo"]).first():
            db.session.add(Insignia(**data))
    db.session.commit()
    ahorro = Insignia.query.filter_by(codigo="AHORRO_1000").first()
    if ahorro and ahorro.icono != "Ahorro_1000.png":
        ahorro.icono = "Ahorro_1000.png"
        db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    csrf.init_app(app)

    @app.context_processor
    def inject_csrf():
        # Permite usar {{ csrf_token() }} en las plantillas
        return dict(csrf_token=generate_csrf)

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
    def obtener_quests_usuario(usuario):
        # Propios (creador)
        quests_propios = Quest.query.filter_by(usuario_id=usuario.id).all()

        # Colaborativos donde es colaborador (incluye creador si lo registramos también)
        quests_colab = (
            Quest.query
            .join(ParticipacionQuest)
            .filter(ParticipacionQuest.usuario_id == usuario.id)
            .all()
        )

        # Quitar duplicados
        quests_dict = {q.id: q for q in quests_propios}
        for q in quests_colab:
            quests_dict.setdefault(q.id, q)

        return list(quests_dict.values())

    # Helper: verificar ownership / participación (creador o colaborador)
    def usuario_participa_en_quest(usuario, quest):
        if quest.usuario_id == usuario.id:
            return True
        participacion = ParticipacionQuest.query.filter_by(
            usuario_id=usuario.id,
            quest_id=quest.id
        ).first()
        return participacion is not None

    # ----------------- Notificaciones inteligentes -----------------

    def generar_notificaciones(usuario):
        notificaciones = []
        hoy = date.today()

        quests = obtener_quests_usuario(usuario)

        for q in quests:
            dias_restantes = (q.fecha_limite - hoy).days
            progreso = q.progreso_porcentaje()

            # 1) Reto por vencer pronto
            if 0 <= dias_restantes <= 7 and progreso < 80:
                notificaciones.append({
                    "tipo": "warning",
                    "mensaje": f"Tu reto '{q.nombre}' está por vencer en {dias_restantes} día(s) y llevas {progreso}% de avance."
                })

            # 2) Reto vencido sin completar
            if dias_restantes < 0 and progreso < 100:
                notificaciones.append({
                    "tipo": "danger",
                    "mensaje": f"Tu reto '{q.nombre}' ya venció y no alcanzaste el monto objetivo."
                })

            # 3) Reto sin movimientos del usuario actual
            ultimo_mov = (
                Movimiento.query
                .filter_by(quest_id=q.id, usuario_id=usuario.id)
                .order_by(Movimiento.fecha.desc())
                .first()
            )

            if ultimo_mov is None and progreso == 0:
                notificaciones.append({
                    "tipo": "info",
                    "mensaje": f"Aún no has registrado tu primer ahorro en el reto '{q.nombre}'."
                })
            elif ultimo_mov is not None and progreso < 100:
                dias_sin_mov = (datetime.utcnow() - ultimo_mov.fecha).days
                if dias_sin_mov >= 7:
                    notificaciones.append({
                        "tipo": "info",
                        "mensaje": f"Llevas {dias_sin_mov} día(s) sin registrar movimientos en '{q.nombre}'."
                    })

        # ----------------- Notificaciones basadas en gastos / control de gastos -----------------
        # Solo generamos estas si el usuario tiene activadas las notificaciones de IA (si el campo existe)
        notif_ia_activo = getattr(usuario, "notif_ia", True)

        if notif_ia_activo:
            try:
                gastos_info = resumen_gastos_para_ia(usuario)
            except Exception:
                gastos_info = None

            if gastos_info:
                total_mes = gastos_info.get("total_mes", 0.0) or 0.0
                categoria_top = gastos_info.get("categoria_top")
                categoria_top_monto = gastos_info.get("categoria_top_monto", 0.0) or 0.0
                total_hormiga = gastos_info.get("total_hormiga", 0.0) or 0.0
                hormiga_count = gastos_info.get("hormiga_count", 0) or 0

                # 4) Sin gastos registrados en el mes
                if total_mes == 0:
                    notificaciones.append({
                        "tipo": "info",
                        "mensaje": (
                            "Aún no has registrado gastos en tu módulo de control de gastos este mes. "
                            "Si empiezas a registrar tus consumos, Questy podrá ayudarte a detectar gastos hormiga."
                        ),
                    })
                else:
                    # 5) Una categoría domina tus gastos del mes
                    if categoria_top and categoria_top_monto >= 0.5 * total_mes and total_mes >= 500:
                        notificaciones.append({
                            "tipo": "warning",
                            "mensaje": (
                                f"Este mes has gastado aproximadamente {categoria_top_monto:,.0f} MXN en '{categoria_top}', "
                                "lo que representa la mayor parte de tus gastos. Revisa si todos esos gastos son realmente necesarios."
                            ),
                        })

                    # 6) Muchos gastos hormiga
                    if total_hormiga >= 200 and hormiga_count >= 3:
                        notificaciones.append({
                            "tipo": "info",
                            "mensaje": (
                                f"Llevas {hormiga_count} gasto(s) hormiga por un total de ~{total_hormiga:,.0f} MXN este mes. "
                                "Si recortas aunque sea una parte y la conviertes en aportes a tus retos, podrías acelerar tus metas."
                            ),
                        })

                    # 7) Gasto muy alto en el mes (alerta suave)
                    # Umbral simple: si el usuario tiene metas activas y el gasto del mes supera el ahorro total del mes
                    # se puede sugerir revisar prioridades.
                    try:
                        # Ahorro (aportes) de los últimos 30 días
                        hoy_dt = datetime.utcnow()
                        hace_30 = hoy_dt - timedelta(days=30)
                        movs_30 = (
                            Movimiento.query
                            .filter(
                                Movimiento.usuario_id == usuario.id,
                                Movimiento.tipo == "aporte",
                                Movimiento.fecha >= hace_30,
                            )
                            .all()
                        )
                        ahorro_30 = sum(m.monto for m in movs_30)
                    except Exception:
                        ahorro_30 = 0

                    if total_mes > ahorro_30 and total_mes >= 1000 and ahorro_30 > 0:
                        notificaciones.append({
                            "tipo": "warning",
                            "mensaje": (
                                f"En este mes has gastado alrededor de {total_mes:,.0f} MXN, "
                                f"mientras que has ahorrado cerca de {ahorro_30:,.0f} MXN. "
                                "Quizá valga la pena revisar qué gastos podrías reducir para fortalecer tu ahorro."
                            ),
                        })

        return notificaciones

    # ----------------- Dificultad automática -----------------

    def calcular_dificultad(monto_objetivo, fecha_limite, fecha_creacion=None):
        if fecha_creacion is None:
            fecha_creacion = date.today()

        if not monto_objetivo or monto_objetivo <= 0:
            return "desconocida"

        dias_plazo = (fecha_limite - fecha_creacion).days
        if dias_plazo <= 0:
            dias_plazo = 1

        ahorro_por_dia = monto_objetivo / dias_plazo

        if ahorro_por_dia < 50:
            return "fácil"
        elif ahorro_por_dia < 150:
            return "media"
        else:
            return "difícil"

    # ----------------- Puntos (fórmula tipo Apple Fitness) -----------------

    def calcular_puntos_quest(monto_objetivo, fecha_limite, dificultad, tipo, fecha_creacion=None):
        if fecha_creacion is None:
            fecha_creacion = date.today()

        if not monto_objetivo or monto_objetivo <= 0:
            return 0

        dias_plazo = (fecha_limite - fecha_creacion).days
        if dias_plazo <= 0:
            dias_plazo = 1

        # 1) Score por monto
        monto_seguro = max(monto_objetivo, 1)
        score_monto = math.log10(monto_seguro) * 25

        # 2) Score por plazo
        score_plazo = (30 / dias_plazo) * 30
        score_plazo = min(score_plazo, 60)

        # 3) Score por dificultad
        dificultad_txt = (dificultad or "").lower()
        if "dificil" in dificultad_txt or "difícil" in dificultad_txt:
            score_riesgo = 20
        elif "media" in dificultad_txt:
            score_riesgo = 10
        else:
            score_riesgo = 0

        # 4) Extra por colaborativo
        score_extra = 15 if tipo == "colaborativo" else 0

        puntos = score_monto + score_plazo + score_riesgo + score_extra

        return max(5, int(round(puntos)))

    def otorgar_puntos_por_completado(quest):
        """
        Reparte los puntos del reto entre todos los participantes
        (creador + colaboradores) cuando se completa y dispara insignias.
        """
        if quest.puntos_otorgados or quest.puntos_recompensa <= 0:
            return

        participaciones = ParticipacionQuest.query.filter_by(quest_id=quest.id).all()

        if not participaciones:
            # Solo el creador
            quest.usuario.puntos_totales += quest.puntos_recompensa
            quest.puntos_otorgados = True
            # Insignias para el creador
            checar_insignias_por_evento(quest.usuario, "reto_completado", quest=quest)
            return

        num_participantes = len(participaciones)
        puntos_por_usuario = max(1, int(round(quest.puntos_recompensa / num_participantes)))

        for p in participaciones:
            p.usuario.puntos_totales += puntos_por_usuario
            checar_insignias_por_evento(p.usuario, "reto_completado", quest=quest)

        quest.puntos_otorgados = True

    def analizar_habitos_ahorro(usuario):
        """Calcula métricas por usuario y por reto:
        - ritmo real de ahorro
        - ritmo necesario para llegar
        - probabilidad estimada de completar
        - recomendaciones por reto
        """
        hoy = date.today()
        quests = obtener_quests_usuario(usuario)

        resumen_global = {
            "total_quests": len(quests),
            "activos": 0,
            "completados": 0,
            "cancelados": 0,
        }

        analisis_por_quest = []
        recomendaciones = []

        for q in quests:
            if q.estatus == "cancelado":
                resumen_global["cancelados"] += 1
            elif q.estatus == "completado":
                resumen_global["completados"] += 1
            else:
                resumen_global["activos"] += 1

            dias_totales = (q.fecha_limite - q.fecha_creacion).days or 1
            dias_transcurridos = (hoy - q.fecha_creacion).days
            if dias_transcurridos <= 0:
                dias_transcurridos = 1

            ritmo_necesario = q.monto_objetivo / dias_totales
            ritmo_real = q.monto_actual / dias_transcurridos

            # Probabilidad estimada simple (0-100)
            if ritmo_necesario <= 0:
                prob = 0
                nivel = "baja"
            else:
                ratio = ritmo_real / ritmo_necesario
                if ratio >= 1.1:
                    prob = 90
                    nivel = "alta"
                elif ratio >= 0.7:
                    prob = 60
                    nivel = "media"
                else:
                    prob = 30
                    nivel = "baja"

            faltante = max(q.monto_objetivo - q.monto_actual, 0)
            dias_restantes = (q.fecha_limite - hoy).days
            if dias_restantes <= 0:
                ahorro_diario_recomendado = faltante if faltante > 0 else 0
            else:
                ahorro_diario_recomendado = faltante / dias_restantes

            analisis_por_quest.append({
                "quest": q,
                "dias_totales": dias_totales,
                "dias_transcurridos": dias_transcurridos,
                "dias_restantes": dias_restantes,
                "ritmo_necesario": ritmo_necesario,
                "ritmo_real": ritmo_real,
                "probabilidad_num": prob,
                "probabilidad_nivel": nivel,
                "faltante": faltante,
                "ahorro_diario_recomendado": ahorro_diario_recomendado,
            })

            # Reglas simples de recomendación
            if q.estatus not in ["completado", "cancelado"]:
                if nivel == "baja" and dias_restantes > 0:
                    recomendaciones.append({
                        "tipo": "warning",
                        "texto": (
                            f"Tu reto '{q.nombre}' va por debajo del ritmo necesario. "
                            f"Te convendría aportar ~{ahorro_diario_recomendado:,.0f} MXN diarios para alcanzarlo."
                        ),
                    })
                if nivel == "alta" and dias_restantes > 0:
                    recomendaciones.append({
                        "tipo": "success",
                        "texto": (
                            f"Vas muy bien en '{q.nombre}'. Si mantienes tu ritmo, "
                            f"es muy probable que alcances la meta."
                        ),
                    })
                if dias_restantes <= 7 and faltante > 0:
                    recomendaciones.append({
                        "tipo": "danger",
                        "texto": (
                            f"A tu reto '{q.nombre}' le quedan pocos días y aún te faltan "
                            f"{faltante:,.0f} MXN para lograrlo."
                        ),
                    })

        return {
            "resumen_global": resumen_global,
            "analisis_por_quest": analisis_por_quest,
            "recomendaciones": recomendaciones,
        }

    def resumen_gastos_para_ia(usuario):
        """Resume los gastos del usuario para que Questy pueda dar mejores recomendaciones.

        Devuelve:
            {
                "total_mes": float,
                "por_categoria": {nombre: monto},
                "categoria_top": str | None,
                "categoria_top_monto": float,
                "total_hormiga": float,
                "hormiga_count": int,
            }
        """
        hoy = date.today()
        inicio_mes = hoy.replace(day=1)

        gastos = (
            Gasto.query
            .filter(
                Gasto.usuario_id == usuario.id,
                Gasto.fecha >= inicio_mes,
                Gasto.fecha <= hoy,
            )
            .all()
        )

        if not gastos:
            return {
                "total_mes": 0.0,
                "por_categoria": {},
                "categoria_top": None,
                "categoria_top_monto": 0.0,
                "total_hormiga": 0.0,
                "hormiga_count": 0,
            }

        total_mes = 0.0
        por_categoria = {}
        total_hormiga = 0.0
        hormiga_count = 0

        for g in gastos:
            monto = float(g.monto or 0)
            total_mes += monto

            # Nombre legible de categoría (si existe relación)
            try:
                cat_nombre = g.categoria.nombre if g.categoria else "Otros"
            except AttributeError:
                cat_nombre = "Otros"

            por_categoria[cat_nombre] = por_categoria.get(cat_nombre, 0.0) + monto

            if getattr(g, "es_hormiga", False):
                total_hormiga += monto
                hormiga_count += 1

        categoria_top = None
        categoria_top_monto = 0.0
        if por_categoria:
            categoria_top, categoria_top_monto = max(
                por_categoria.items(), key=lambda x: x[1]
            )

        return {
            "total_mes": total_mes,
            "por_categoria": por_categoria,
            "categoria_top": categoria_top,
            "categoria_top_monto": categoria_top_monto,
            "total_hormiga": total_hormiga,
            "hormiga_count": hormiga_count,
        }


    def generar_consejos_financieros(usuario, resultados_ia):
        """Genera una lista de consejos financieros personalizados usando el análisis de IA y movimientos recientes."""
        resumen = resultados_ia["resumen_global"]
        analisis = resultados_ia["analisis_por_quest"]

        consejos = []

        # 1) Si no tiene metas activas
        if resumen["activos"] == 0:
            consejos.append({
                "tipo": "info",
                "titulo": "Sin metas activas",
                "texto": (
                    "Actualmente no tienes metas activas. Te convendría crear al menos una meta de ahorro, "
                    "por ejemplo un fondo de emergencia o una meta a corto plazo."
                ),
            })

        # 2) Si tiene varias metas canceladas
        if resumen["cancelados"] >= 2:
            consejos.append({
                "tipo": "warning",
                "titulo": "Metas canceladas",
                "texto": (
                    "Has cancelado varias metas. Tal vez estás fijando montos o fechas demasiado exigentes. "
                    "Considera metas más pequeñas o plazos un poco más largos."
                ),
            })

        # 3) Consejos por cada reto activo según probabilidad y ritmo
        for item in analisis:
            q = item["quest"]
            if q.estatus in ["completado", "cancelado"]:
                continue

            prob = item["probabilidad_num"]
            faltante = item["faltante"]
            dias_restantes = item["dias_restantes"]
            ahorro_diario = item["ahorro_diario_recomendado"]

            if prob <= 40 and dias_restantes > 0 and faltante > 0:
                consejos.append({
                    "tipo": "danger",
                    "titulo": f"Meta en riesgo: {q.nombre}",
                    "texto": (
                        f"Tu meta '{q.nombre}' tiene una probabilidad baja de cumplirse con tu ritmo actual. "
                        f"Te faltan aproximadamente {faltante:,.0f} MXN y te convendría ahorrar unos "
                        f"{ahorro_diario:,.0f} MXN diarios para alcanzarla a tiempo."
                    ),
                })
            elif 40 < prob < 80 and dias_restantes > 0 and faltante > 0:
                consejos.append({
                    "tipo": "warning",
                    "titulo": f"Puedes mejorar en: {q.nombre}",
                    "texto": (
                        f"Vas a medio camino con '{q.nombre}'. Si aumentas un poco tus depósitos y ahorras alrededor de "
                        f"{ahorro_diario:,.0f} MXN al día, tus probabilidades de éxito aumentarán bastante."
                    ),
                })
            elif prob >= 80 and faltante > 0:
                consejos.append({
                    "tipo": "success",
                    "titulo": f"Vas muy bien en: {q.nombre}",
                    "texto": (
                        f"Tu meta '{q.nombre}' va muy bien encaminada. Si mantienes tu ritmo actual, es muy probable que la cumplas. "
                        "No bajes la guardia y sigue registrando tus avances."
                    ),
                })

        # 4) Consejo basado en movimientos de los últimos 30 días
        hoy = datetime.utcnow()
        hace_30 = hoy - timedelta(days=30)

        movimientos_recientes = (
            Movimiento.query
            .filter(
                Movimiento.usuario_id == usuario.id,
                Movimiento.fecha >= hace_30,
                Movimiento.tipo == "aporte",
            )
            .all()
        )

        total_30_dias = sum(m.monto for m in movimientos_recientes)
        if movimientos_recientes:
            ahorro_diario_promedio = total_30_dias / 30
            consejos.append({
                "tipo": "info",
                "titulo": "Tu ritmo de ahorro reciente",
                "texto": (
                    f"En los últimos 30 días has ahorrado aproximadamente {total_30_dias:,.0f} MXN "
                    f"(unos {ahorro_diario_promedio:,.0f} MXN diarios en promedio). "
                    "Puedes usar este dato para definir metas más realistas y sostenibles."
                ),
            })
        else:
            consejos.append({
                "tipo": "info",
                "titulo": "Aún no has registrado ahorros recientes",
                "texto": (
                    "No has registrado aportes en los últimos 30 días. Intenta comenzar con un pequeño hábito, "
                    "aunque sea una cantidad pequeña pero constante."
                ),
            })

        return consejos

    def simular_escenario_ahorro(usuario, quest, monto_extra, frecuencia):
        """
        Simula un escenario de ahorro extra para un quest concreto.
        Calcula si con un monto adicional y una frecuencia dada se alcanzaría la meta,
        y cómo cambiaría la probabilidad de éxito.
        """
        hoy = date.today()
        dias_restantes = (quest.fecha_limite - hoy).days
        if dias_restantes < 0:
            dias_restantes = 0

        # Cálculo de ritmo actual vs necesario
        dias_totales = (quest.fecha_limite - quest.fecha_creacion).days or 1
        dias_transcurridos = (hoy - quest.fecha_creacion).days
        if dias_transcurridos <= 0:
            dias_transcurridos = 1

        ritmo_necesario = quest.monto_objetivo / dias_totales
        ritmo_real = quest.monto_actual / dias_transcurridos

        # Extra de ahorro convertido a "por día" según frecuencia
        frecuencia = (frecuencia or "diario").lower()
        if frecuencia == "diario":
            extra_diario = monto_extra
        elif frecuencia == "semanal":
            extra_diario = monto_extra / 7.0
        elif frecuencia == "quincenal":
            extra_diario = monto_extra / 15.0
        elif frecuencia == "mensual":
            extra_diario = monto_extra / 30.0
        else:
            extra_diario = 0.0

        aportes_proyectados = extra_diario * dias_restantes
        total_proyectado = quest.monto_actual + aportes_proyectados
        if total_proyectado > quest.monto_objetivo:
            total_proyectado = quest.monto_objetivo

        faltante = max(quest.monto_objetivo - total_proyectado, 0)

        # Probabilidad actual (misma lógica que en analizar_habitos_ahorro)
        if ritmo_necesario <= 0:
            prob_actual = 0
            nivel_actual = "baja"
        else:
            ratio_actual = ritmo_real / ritmo_necesario
            if ratio_actual >= 1.1:
                prob_actual = 90
                nivel_actual = "alta"
            elif ratio_actual >= 0.7:
                prob_actual = 60
                nivel_actual = "media"
            else:
                prob_actual = 30
                nivel_actual = "baja"

        # Probabilidad en el escenario con extra_diario
        ritmo_escenario = ritmo_real + extra_diario
        if ritmo_necesario <= 0:
            prob_escenario = prob_actual
            nivel_escenario = nivel_actual
        else:
            ratio_esc = ritmo_escenario / ritmo_necesario
            if ratio_esc >= 1.1:
                prob_escenario = 90
                nivel_escenario = "alta"
            elif ratio_esc >= 0.7:
                prob_escenario = 60
                nivel_escenario = "media"
            else:
                prob_escenario = 30
                nivel_escenario = "baja"

        alcanza_meta = total_proyectado >= quest.monto_objetivo

        return {
            "quest": quest,
            "dias_restantes": dias_restantes,
            "extra_diario": extra_diario,
            "aportes_proyectados": aportes_proyectados,
            "total_proyectado": total_proyectado,
            "faltante": faltante,
            "alcanza_meta": alcanza_meta,
            "prob_actual": prob_actual,
            "prob_escenario": prob_escenario,
            "nivel_actual": nivel_actual,
            "nivel_escenario": nivel_escenario,
            "frecuencia": frecuencia,
            "monto_extra": monto_extra,
        }

    def calcular_estadisticas(usuario):
        """Calcula datos agregados para las gráficas de estadísticas de ahorro."""
        hoy = date.today()
        hace_30 = hoy - timedelta(days=30)

        # Aportes de los últimos 30 días
        movs_30 = (
            Movimiento.query
            .filter(
                Movimiento.usuario_id == usuario.id,
                Movimiento.tipo == "aporte",
                Movimiento.fecha >= hace_30,
            )
            .order_by(Movimiento.fecha.asc())
            .all()
        )

        aportes_por_dia = {}
        for m in movs_30:
            dia = m.fecha.date().isoformat()
            aportes_por_dia[dia] = aportes_por_dia.get(dia, 0) + m.monto

        labels_fechas = list(aportes_por_dia.keys())
        data_montos = list(aportes_por_dia.values())

        # Ahorro total por meta (todas las metas, todo el historial)
        movs_todos = (
            Movimiento.query
            .filter(
                Movimiento.usuario_id == usuario.id,
                Movimiento.tipo == "aporte",
            ).all()
        )

        total_ahorrado = sum(m.monto for m in movs_todos)
        num_aportes = len(movs_todos)

        ahorro_por_quest = {}
        for m in movs_todos:
            q = m.quest
            if not q:
                continue
            ahorro_por_quest[q.nombre] = ahorro_por_quest.get(q.nombre, 0) + m.monto

        labels_quests = list(ahorro_por_quest.keys())
        data_quests = list(ahorro_por_quest.values())

        meta_top_nombre = None
        meta_top_monto = 0
        if ahorro_por_quest:
            meta_top_nombre, meta_top_monto = max(ahorro_por_quest.items(), key=lambda x: x[1])

        # Resumen de metas
        quests = obtener_quests_usuario(usuario)
        activos = sum(1 for q in quests if q.estatus not in ["completado", "cancelado"])
        completados = sum(1 for q in quests if q.estatus == "completado")

        resumen = {
            "total_ahorrado": total_ahorrado,
            "num_aportes": num_aportes,
            "meta_top_nombre": meta_top_nombre,
            "meta_top_monto": meta_top_monto,
            "metas_activas": activos,
            "metas_completadas": completados,
        }

        return {
            "resumen": resumen,
            "serie_30_dias": {
                "labels": labels_fechas,
                "data": data_montos,
            },
            "serie_por_meta": {
                "labels": labels_quests,
                "data": data_quests,
            },
        }




    # ----------------- Rachas de ahorro: días consecutivos con aportes -----------------
    def calcular_rachas_usuario(usuario):
        """
        Calcula la racha actual de días con aportes y la mejor racha histórica
        para un usuario, usando únicamente movimientos de tipo 'aporte'.
        La racha se mide en días consecutivos con al menos un aporte.
        """
        # Obtener todos los aportes del usuario ordenados por fecha ascendente
        movs = (
            Movimiento.query
            .filter(
                Movimiento.usuario_id == usuario.id,
                Movimiento.tipo == "aporte",
            )
            .order_by(Movimiento.fecha.asc())
            .all()
        )

        if not movs:
            return {
                "racha_actual": 0,
                "mejor_racha": 0,
                "ultimo_dia": None,
            }

        # Usar solo la parte de fecha (sin horas) y evitar días duplicados
        dias_unicos = sorted({m.fecha.date() for m in movs})

        racha_actual = 0
        mejor_racha = 0
        ultimo_dia = None

        for d in dias_unicos:
            if ultimo_dia is None:
                # Primer día con aporte
                racha_actual = 1
            else:
                diferencia = (d - ultimo_dia).days
                if diferencia == 1:
                    # Día inmediatamente siguiente: se extiende la racha
                    racha_actual += 1
                elif diferencia > 1:
                    # Hubo un corte de al menos un día sin aporte: racha nueva
                    racha_actual = 1
                # Si diferencia == 0 no debería ocurrir porque usamos set(), pero lo ignoramos

            if racha_actual > mejor_racha:
                mejor_racha = racha_actual

            ultimo_dia = d

        # La racha actual es la racha del último bloque de días consecutivos;
        # mejor_racha es el máximo histórico.
        return {
            "racha_actual": racha_actual,
            "mejor_racha": mejor_racha,
            "ultimo_dia": ultimo_dia,
        }


    def otorgar_bonus_racha(usuario, rachas_antes, rachas_despues):
        """
        Asigna puntos extra cuando el usuario alcanza nuevas rachas de días consecutivos
        ahorrando. Solo se otorga bonus cuando la racha actual cruza ciertos umbrales.
        """
        if not rachas_antes or not rachas_despues:
            return

        racha_antes = rachas_antes.get("racha_actual", 0) or 0
        racha_despues = rachas_despues.get("racha_actual", 0) or 0

        # Si la racha no aumentó, no hay bonus
        if racha_despues <= racha_antes:
            return

        # Umbrales de racha y puntos asociados
        thresholds = [
            (3, 15),
            (7, 40),
            (14, 80),
            (30, 200),
        ]

        for limite, puntos in thresholds:
            # Se otorga el bonus si se cruza el umbral (por ejemplo, de 2 a 3,
            # o de 6 a 7, etc.). Si ya se tenía una racha mayor en el pasado,
            # no importa: se volverá a recompensar solo al cruzar de nuevo el límite.
            if racha_antes < limite <= racha_despues:
                usuario.puntos_totales += puntos
                flash(
                    f"🔥 ¡Lograste una racha de {limite} días seguidos ahorrando! "
                    f"Has ganado +{puntos} puntos QuestCash.",
                    "success",
                )


    def otorgar_insignia(codigo, usuario):
        """Otorga una insignia al usuario si no la tenía ya."""
        insignia = Insignia.query.filter_by(codigo=codigo).first()
        if not insignia:
            return

        ya = UsuarioInsignia.query.filter_by(
            usuario_id=usuario.id,
            insignia_id=insignia.id
        ).first()

        if ya:
            return

        nueva = UsuarioInsignia(
            usuario_id=usuario.id,
            insignia_id=insignia.id,
        )
        db.session.add(nueva)
        # Sin commit aquí; se hará en la vista que llama
        flash(f"¡Nuevo logro desbloqueado! {insignia.nombre} 🎖️", "success")

    def checar_insignias_por_evento(usuario, evento, quest=None):
        """Evalúa y otorga insignias según un evento usando los códigos nuevos."""

        # 1) Primer ahorro registrado
        if evento == "primer_movimiento":
            total_movs = Movimiento.query.filter_by(usuario_id=usuario.id, tipo="aporte").count()
            if total_movs == 1:
                otorgar_insignia("PRIMER_AHORRO", usuario)

            # Insignia de ahorro total de $1000 o más
            total_ahorrado = (
                db.session.query(db.func.sum(Movimiento.monto))
                .filter_by(usuario_id=usuario.id, tipo="aporte")
                .scalar() or 0
            )
            if total_ahorrado >= 1000:
                otorgar_insignia("AHORRO_1000", usuario)

        # 2) Primera meta creada
        elif evento == "primer_reto_creado":
            total_quests = Quest.query.filter_by(usuario_id=usuario.id).count()
            if total_quests == 1:
                otorgar_insignia("PRIMERA_META", usuario)

        # 3) Primer reto completado
        elif evento == "reto_completado" and quest is not None:
            # Siempre otorgar la épica
            otorgar_insignia("PRIMER_RETO", usuario)

            # Meta cumplida a tiempo (antes o justo en fecha límite)
            if quest.fecha_limite and quest.monto_actual >= quest.monto_objetivo:
                hoy = date.today()
                if hoy <= quest.fecha_limite:
                    otorgar_insignia("META_A_TIEMPO", usuario)

    # ----------------- Rutas de autenticación -----------------

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            correo = request.form.get("correo", "").strip().lower()
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")

            errores = []

            # Validaciones básicas de requeridos
            if not nombre:
                errores.append("El nombre es obligatorio.")
            if not correo:
                errores.append("El correo es obligatorio.")
            if not password:
                errores.append("La contraseña es obligatoria.")
            if password != password2:
                errores.append("Las contraseñas no coinciden.")

            # Longitudes máximas
            if nombre and len(nombre) > 100:
                errores.append("El nombre es demasiado largo (máximo 100 caracteres).")
            if correo and len(correo) > 150:
                errores.append("El correo es demasiado largo (máximo 150 caracteres).")
            if password and len(password) > 128:
                errores.append("La contraseña es demasiado larga (máximo 128 caracteres).")

            # Validación estricta de formato de correo
            if correo:
                email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
                if not re.match(email_regex, correo):
                    errores.append("El correo no tiene un formato válido.")

                # Validación extra de dominio/TLD (modo 'estricto')
                allowed_tlds = (
                    ".com",
                    ".mx",
                    ".com.mx",
                    ".org",
                    ".net",
                    ".edu",
                    ".gob.mx",
                )
                if not any(correo.endswith(tld) for tld in allowed_tlds):
                    errores.append(
                        "El dominio de correo no está permitido. Usa un correo con dominio común (.com, .mx, .org, .net, .edu, .gob.mx)."
                    )

            # Reglas de contraseña fuerte
            if password:
                if len(password) < 8:
                    errores.append("La contraseña debe tener al menos 8 caracteres.")
                if not any(c.islower() for c in password):
                    errores.append("La contraseña debe incluir al menos una letra minúscula.")
                if not any(c.isupper() for c in password):
                    errores.append("La contraseña debe incluir al menos una letra mayúscula.")
                if not any(c.isdigit() for c in password):
                    errores.append("La contraseña debe incluir al menos un número.")

                # No permitir que la contraseña sea igual al nombre o al correo
                if nombre and password.lower() == nombre.lower():
                    errores.append("La contraseña no puede ser igual a tu nombre.")
                if correo and password.lower() == correo.lower():
                    errores.append("La contraseña no puede ser igual a tu correo.")

            # Verificar si ya existe usuario con ese correo
            if correo and not errores:
                existente = Usuario.query.filter_by(correo=correo).first()
                if existente:
                    errores.append("Ya existe una cuenta registrada con ese correo.")

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("auth/register.html")

            nuevo_usuario = Usuario(
                nombre=nombre,
                correo=correo,
                password_hash=generate_password_hash(password),
            )
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

            # Clave para controlar intentos por correo + IP
            ip = request.remote_addr or "unknown"
            clave_intento = f"{correo}|{ip}"

            ahora = datetime.utcnow()
            datos_intento = intentos_login.get(clave_intento)

            # Verificar si está bloqueado temporalmente
            if datos_intento and datos_intento.get("bloqueado_hasta") and ahora < datos_intento["bloqueado_hasta"]:
                minutos_restantes = int((datos_intento["bloqueado_hasta"] - ahora).total_seconds() // 60) + 1
                flash(
                    f"Has excedido el número de intentos. Intenta de nuevo en aproximadamente {minutos_restantes} minuto(s).",
                    "danger",
                )
                return render_template("auth/login.html")

            usuario = Usuario.query.filter_by(correo=correo).first()

            if usuario and check_password_hash(usuario.password_hash, password):
                # Login exitoso: limpiar intentos fallidos
                intentos_login.pop(clave_intento, None)

                session.clear()
                session["user_id"] = usuario.id
                flash(f"¡Bienvenido de nuevo, {usuario.nombre}!", "success")
                return redirect(url_for("dashboard"))
            else:
                # Login fallido: incrementar contador
                if not datos_intento:
                    datos_intento = {"intentos": 0, "bloqueado_hasta": None}

                datos_intento["intentos"] += 1

                if datos_intento["intentos"] >= MAX_LOGIN_INTENTOS:
                    datos_intento["bloqueado_hasta"] = ahora + timedelta(minutes=BLOQUEO_MINUTOS)
                    flash(
                        "Demasiados intentos fallidos. Tu acceso se ha bloqueado temporalmente por unos minutos.",
                        "danger",
                    )
                else:
                    faltan = MAX_LOGIN_INTENTOS - datos_intento["intentos"]
                    flash(
                        f"Correo o contraseña incorrectos. Intentos restantes antes de bloqueo: {faltan}.",
                        "danger",
                    )

                intentos_login[clave_intento] = datos_intento
                return render_template("auth/login.html")

        return render_template("auth/login.html")

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

        total_objetivo = sum(q.monto_objetivo for q in quests) or 0
        total_actual = sum(q.monto_actual for q in quests) or 0

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
        )

    @app.route("/estadisticas")
    @login_requerido
    def ver_estadisticas():
        datos = calcular_estadisticas(g.usuario_actual)
        return render_template(
            "estadisticas.html",
            resumen=datos["resumen"],
            serie_30=datos["serie_30_dias"],
            serie_metas=datos["serie_por_meta"],
        )

    def obtener_o_crear_categoria_gasto(nombre_raw):
        """ 
        Normaliza el nombre de categoría y la crea si no existe.
        Las categorías son globales (compartidas entre usuarios).
        """
        nombre = (nombre_raw or "").strip()
        if not nombre:
            nombre = "Otros"

        # Normalizar para que se vea bonito en UI
        nombre = nombre.capitalize()

        categoria = CategoriaGasto.query.filter_by(nombre=nombre).first()
        if not categoria:
            categoria = CategoriaGasto(nombre=nombre)
            db.session.add(categoria)
            db.session.commit()
        return categoria

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

        total_mes = sum(g.monto for g in gastos) if gastos else 0

        categorias = CategoriaGasto.query.order_by(CategoriaGasto.nombre).all()

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

            errores = []

            # Validar monto
            try:
                monto = float(monto_str)
                if monto <= 0:
                    errores.append("El monto del gasto debe ser mayor a 0.")
                if monto > 1_000_000_000:
                    errores.append("El monto del gasto es demasiado grande.")
            except ValueError:
                errores.append("El monto del gasto no es válido.")

            # Validar fecha (opcional, por defecto hoy)
            if fecha_str:
                try:
                    fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                except ValueError:
                    errores.append("La fecha no tiene un formato válido (AAAA-MM-DD).")
                    fecha = date.today()
            else:
                fecha = date.today()

            # Validar descripción
            if descripcion and len(descripcion) > 200:
                errores.append("La descripción no puede superar 200 caracteres.")

            if errores:
                for e in errores:
                    flash(e, "danger")

                categorias = CategoriaGasto.query.order_by(CategoriaGasto.nombre).all()
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
                if monto <= 100 and any(
                    x in nombre_cat
                    for x in ["comida", "caf", "snack", "antojo", "dulce"]
                ):
                    es_hormiga = True

            gasto = Gasto(
                usuario_id=g.usuario_actual.id,
                categoria_id=categoria.id,
                monto=monto,
                descripcion=descripcion or None,
                fecha=fecha,
                metodo_pago=metodo_pago or None,
                es_hormiga=es_hormiga,
            )

            db.session.add(gasto)
            db.session.commit()

            flash("Gasto registrado correctamente 💸", "success")
            return redirect(url_for("listar_gastos"))

        # GET: cargar formulario
        categorias = CategoriaGasto.query.order_by(CategoriaGasto.nombre).all()
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

            errores = []

            if not nombre:
                errores.append("El nombre del reto es obligatorio.")
            if not monto_objetivo:
                errores.append("El monto objetivo es obligatorio.")
            if not fecha_limite:
                errores.append("La fecha límite es obligatoria.")

            try:
                monto_objetivo_float = float(monto_objetivo)
                if monto_objetivo_float <= 0:
                    errores.append("El monto objetivo debe ser mayor a 0.")
            except ValueError:
                errores.append("El monto objetivo debe ser un número válido.")

            try:
                monto_actual_float = float(monto_actual) if monto_actual else 0.0
                if monto_actual_float < 0:
                    errores.append("El monto actual no puede ser negativo.")
            except ValueError:
                errores.append("El monto actual debe ser un número válido.")

            try:
                fecha_limite_date = datetime.strptime(fecha_limite, "%Y-%m-%d").date()
            except ValueError:
                errores.append("La fecha límite no tiene un formato válido (AAAA-MM-DD).")

            if tipo not in ["individual", "colaborativo"]:
                errores.append("Tipo de reto no válido.")

            # Validaciones adicionales de negocio para montos, texto y fechas
            if nombre and len(nombre) > 100:
                errores.append("El nombre del reto es demasiado largo (máximo 100 caracteres).")

            if descripcion and len(descripcion) > 500:
                errores.append("La descripción es demasiado larga (máximo 500 caracteres).")

            # Validar montos máximos y coherencia entre monto actual y objetivo
            if "monto_objetivo_float" in locals():
                if monto_objetivo_float > 1_000_000_000:
                    errores.append("El monto objetivo es demasiado grande.")
            if "monto_actual_float" in locals() and "monto_objetivo_float" in locals():
                if monto_actual_float > monto_objetivo_float:
                    errores.append("El monto actual no puede ser mayor que el monto objetivo.")

            # Validar fechas: no en el pasado y no excesivamente lejanas
            if "fecha_limite_date" in locals():
                hoy = date.today()
                if fecha_limite_date < hoy:
                    errores.append("La fecha límite no puede ser anterior a hoy.")
                max_fecha = hoy + timedelta(days=365 * 10)
                if fecha_limite_date > max_fecha:
                    errores.append("La fecha límite es demasiado lejana (máximo 10 años desde hoy).")

            if errores:
                for e in errores:
                    flash(e, "danger")
                hoy_iso = date.today().strftime("%Y-%m-%d")
                return render_template("quests/form.html", modo="crear", hoy_iso=hoy_iso)

            fecha_creacion = date.today()

            dificultad_calc = calcular_dificultad(
                monto_objetivo_float,
                fecha_limite_date,
                fecha_creacion=fecha_creacion,
            )

            puntos_calc = calcular_puntos_quest(
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
                puntos_recompensa=puntos_calc,
                usuario_id=g.usuario_actual.id,
                es_colaborativo=es_colaborativo,
                tipo=tipo,
            )

            db.session.add(nueva_quest)
            db.session.flush()

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

        return render_template(
            "quests/detail.html",
            quest=quest,
            es_creador=es_creador,
            participaciones=participaciones,
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

            errores = []

            if not nombre:
                errores.append("El nombre del reto es obligatorio.")
            if not monto_objetivo:
                errores.append("El monto objetivo es obligatorio.")
            if not fecha_limite:
                errores.append("La fecha límite es obligatoria.")

            try:
                monto_objetivo_float = float(monto_objetivo)
                if monto_objetivo_float <= 0:
                    errores.append("El monto objetivo debe ser mayor a 0.")
            except ValueError:
                errores.append("El monto objetivo debe ser un número válido.")

            try:
                monto_actual_float = float(monto_actual) if monto_actual else 0.0
                if monto_actual_float < 0:
                    errores.append("El monto actual no puede ser negativo.")
            except ValueError:
                errores.append("El monto actual debe ser un número válido.")

            try:
                fecha_limite_date = datetime.strptime(fecha_limite, "%Y-%m-%d").date()
            except ValueError:
                errores.append("La fecha límite no tiene un formato válido (AAAA-MM-DD).")

            if tipo not in ["individual", "colaborativo"]:
                errores.append("Tipo de reto no válido.")

            # Validaciones adicionales de negocio para montos, texto y fechas
            if nombre and len(nombre) > 100:
                errores.append("El nombre del reto es demasiado largo (máximo 100 caracteres).")

            if descripcion and len(descripcion) > 500:
                errores.append("La descripción es demasiado larga (máximo 500 caracteres).")

            # Validar montos máximos y coherencia entre monto actual y objetivo
            if "monto_objetivo_float" in locals():
                if monto_objetivo_float > 1_000_000_000:
                    errores.append("El monto objetivo es demasiado grande.")
            if "monto_actual_float" in locals() and "monto_objetivo_float" in locals():
                if monto_actual_float > monto_objetivo_float:
                    errores.append("El monto actual no puede ser mayor que el monto objetivo.")

            # Validar fechas: no en el pasado y no excesivamente lejanas
            if "fecha_limite_date" in locals():
                hoy = date.today()
                if fecha_limite_date < hoy:
                    errores.append("La fecha límite no puede ser anterior a hoy.")
                max_fecha = hoy + timedelta(days=365 * 10)
                if fecha_limite_date > max_fecha:
                    errores.append("La fecha límite es demasiado lejana (máximo 10 años desde hoy).")

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("quests/form.html", modo="editar", quest=quest, hoy_iso=hoy_iso)

            fecha_creacion = quest.fecha_creacion or date.today()

            dificultad_calc = calcular_dificultad(
                monto_objetivo_float,
                fecha_limite_date,
                fecha_creacion=fecha_creacion,
            )

            puntos_calc = calcular_puntos_quest(
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
            quest.puntos_recompensa = puntos_calc
            quest.es_colaborativo = es_colaborativo
            quest.tipo = tipo

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
            # Racha antes de registrar el nuevo movimiento
            rachas_antes = calcular_rachas_usuario(g.usuario_actual)

            # Stricter sanitized version for reading form fields
            tipo = request.form.get("tipo", "").strip().lower()
            monto = request.form.get("monto", "").strip()
            nota = request.form.get("nota", "").strip()
            categoria = request.form.get("categoria", "general").strip().lower()

            # Sanitización adicional
            if nota and len(nota) > 500:
                nota = nota[:500]

            # Improved stricter validation block
            errores = []

            # Validar tipo estrictamente
            if tipo not in ["aporte", "retiro"]:
                errores.append("Tipo de movimiento no válido.")

            # Validar monto estrictamente
            try:
                monto_float = float(monto)
                if monto_float <= 0:
                    errores.append("El monto debe ser mayor a 0.")
                if monto_float > 1_000_000_000:
                    errores.append("El monto es demasiado grande.")
            except (TypeError, ValueError):
                errores.append("Monto inválido.")

            # Validar longitud de nota
            if nota and len(nota) > 500:
                errores.append("La nota no puede superar 500 caracteres.")

            # Normalizar categoría (opcional, por si viene vacía)
            categorias_validas = {
                "general",
                "salario",
                "ahorro_programado",
                "extra",
                "comida",
                "transporte",
                "entretenimiento",
                "viaje",
                "regalos",
                "salud",
                "otros",
            }
            if not categoria:
                categoria = "general"
            elif categoria not in categorias_validas:
                categoria = "otros"

            # Validar retiros
            if not errores and tipo == "retiro":
                if monto_float > quest.monto_actual:
                    errores.append("No puedes retirar más de lo que tienes ahorrado en este reto.")
                if quest.estatus == "completado":
                    errores.append("No puedes retirar en un reto ya completado.")

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("movimientos/form.html", quest=quest)

            movimiento = Movimiento(
                tipo=tipo,
                monto=monto_float,
                nota=nota,
                categoria=categoria,
                usuario_id=g.usuario_actual.id,
                quest_id=quest.id,
            )
            db.session.add(movimiento)

            if tipo == "aporte":
                quest.monto_actual += monto_float
            else:
                quest.monto_actual -= monto_float

            # Actualizar estatus automáticamente
            if quest.estatus == "pendiente" and tipo == "aporte":
                quest.estatus = "en_progreso"

            if quest.monto_actual >= quest.monto_objetivo and quest.estatus != "cancelado":
                if quest.estatus != "completado":
                    quest.estatus = "completado"
                    otorgar_puntos_por_completado(quest)

            # Insignia por primer movimiento (si aplica)
            checar_insignias_por_evento(g.usuario_actual, "primer_movimiento")

            # Bonus por racha solo para aportes
            if tipo == "aporte":
                # Asegurar que el movimiento actual esté en la sesión al recalcular
                db.session.flush()
                rachas_despues = calcular_rachas_usuario(g.usuario_actual)
                otorgar_bonus_racha(g.usuario_actual, rachas_antes, rachas_despues)

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
            # Racha antes de registrar el nuevo movimiento
            rachas_antes = calcular_rachas_usuario(g.usuario_actual)

            # Stricter sanitized version for reading form fields
            tipo = request.form.get("tipo", "").strip().lower()
            monto = request.form.get("monto", "").strip()
            nota = request.form.get("nota", "").strip()
            categoria = request.form.get("categoria", "general").strip().lower()

            # Sanitización adicional
            if nota and len(nota) > 500:
                nota = nota[:500]

            # Improved stricter validation block
            errores = []

            # Validar tipo estrictamente
            if tipo not in ["aporte", "retiro"]:
                errores.append("Tipo de movimiento no válido.")

            # Validar monto estrictamente
            try:
                monto_float = float(monto)
                if monto_float <= 0:
                    errores.append("El monto debe ser mayor a 0.")
                if monto_float > 1_000_000_000:
                    errores.append("El monto es demasiado grande.")
            except (TypeError, ValueError):
                errores.append("Monto inválido.")

            # Validar longitud de nota
            if nota and len(nota) > 500:
                errores.append("La nota no puede superar 500 caracteres.")

            # Normalizar categoría (opcional, por si viene vacía)
            categorias_validas = {
                "general",
                "salario",
                "ahorro_programado",
                "extra",
                "comida",
                "transporte",
                "entretenimiento",
                "viaje",
                "regalos",
                "salud",
                "otros",
            }
            if not categoria:
                categoria = "general"
            elif categoria not in categorias_validas:
                categoria = "otros"

            # Validar retiros
            if not errores and tipo == "retiro":
                if monto_float > quest.monto_actual:
                    errores.append("No puedes retirar más de lo que tienes ahorrado en este reto.")
                if quest.estatus == "completado":
                    errores.append("No puedes retirar en un reto ya completado.")

            if errores:
                for e in errores:
                    flash(e, "danger")
                return render_template("movimientos/form.html", quest=quest)

            movimiento = Movimiento(
                tipo=tipo,
                monto=monto_float,
                nota=nota,
                categoria=categoria,
                usuario_id=g.usuario_actual.id,
                quest_id=quest.id,
            )
            db.session.add(movimiento)

            if tipo == "aporte":
                quest.monto_actual += monto_float
            else:
                quest.monto_actual -= monto_float

            # Actualizar estatus automáticamente
            if quest.estatus == "pendiente" and tipo == "aporte":
                quest.estatus = "en_progreso"

            if quest.monto_actual >= quest.monto_objetivo and quest.estatus != "cancelado":
                if quest.estatus != "completado":
                    quest.estatus = "completado"
                    otorgar_puntos_por_completado(quest)

            # Insignia por primer movimiento (si aplica)
            checar_insignias_por_evento(g.usuario_actual, "primer_movimiento")

            # Bonus por racha solo para aportes
            if tipo == "aporte":
                db.session.flush()
                rachas_despues = calcular_rachas_usuario(g.usuario_actual)
                otorgar_bonus_racha(g.usuario_actual, rachas_antes, rachas_despues)

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

            # 3) Validar existencia en la base de datos y reglas de negocio
            if not errores:
                usuario_invitado = Usuario.query.filter_by(correo=correo).first()
                if not usuario_invitado:
                    errores.append("No existe un usuario registrado con ese correo.")
                elif usuario_invitado.id == quest.usuario_id:
                    errores.append("Tú ya eres el creador de este reto.")
                else:
                    ya_participa = ParticipacionQuest.query.filter_by(
                        usuario_id=usuario_invitado.id,
                        quest_id=quest.id
                    ).first()
                    if ya_participa:
                        errores.append("Ese usuario ya participa en este reto.")

            if errores:
                for e in errores:
                    flash(e, "danger")
            else:
                nueva_part = ParticipacionQuest(
                    usuario_id=usuario_invitado.id,
                    quest_id=quest.id,
                    rol="colaborador",
                )
                db.session.add(nueva_part)
                db.session.commit()
                flash(f"Se ha añadido a {usuario_invitado.nombre} como colaborador.", "success")

            return redirect(url_for("gestionar_colaboradores", quest_id=quest.id))

        participaciones = ParticipacionQuest.query.filter_by(quest_id=quest.id).all()
        return render_template(
            "quests/colaboradores.html",
            quest=quest,
            participaciones=participaciones
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

    # Crear tablas + insignias base al finalizar la configuración de la app
    with app.app_context():
        db.create_all()
        seed_insignias()
    return app

app = create_app()
if __name__ == "__main__":
    
    app.run(debug=True)