# services/analisis.py
"""Análisis financiero y lectura de Questy.

Todo esto vivía como closures dentro de `create_app()`: casi mil líneas de
reglas de negocio que no se podían importar ni probar sin levantar una
aplicación Flask entera.

Questy NO es un modelo de lenguaje. Es un motor determinista que segmenta al
usuario por ingreso y presión de gasto, lo compara con percentiles de ahorro de
la ENIGH y devuelve un multiplicador y un mensaje construido con plantillas.
Ningún dato del usuario sale hacia un tercero, y el costo marginal por usuario
es cero.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from ia.services.questy_engine import QuestyInput, evaluate_quest
from models import CategoriaGasto, Gasto, Movimiento, ParticipacionQuest, Quest, db
from services import rangos
from services.metas import obtener_quests_usuario

# `calcular_estado_rango_perfil` se llamaba así dentro de create_app.
calcular_estado_rango_perfil = rangos.estado


def calcular_ingreso_mensual_usuario(usuario):
    """Estimación simple del ingreso mensual del usuario.

    Prioridad:
    1) Campo explícito en Usuario si existe.
    2) Promedio mensual de aportes de los últimos 90 días.
    3) 0 como fallback.
    """
    ingreso_campo = getattr(usuario, "ingreso_mensual", None)
    if ingreso_campo is not None:
        try:
            ingreso_val = float(ingreso_campo)
            if ingreso_val >= 0:
                return ingreso_val
        except (TypeError, ValueError):
            pass

    hoy_dt = datetime.utcnow()
    hace_90 = hoy_dt - timedelta(days=90)
    movs_90 = (
        Movimiento.query
        .filter(
            Movimiento.usuario_id == usuario.id,
            Movimiento.tipo == "aporte",
            Movimiento.fecha >= hace_90,
        )
        .all()
    )
    total_90 = sum(float(m.monto or 0) for m in movs_90)
    if total_90 > 0:
        return round(total_90 / 3, 2)

    return 0.0

def calcular_gasto_mensual_usuario(usuario):
    """Obtiene el gasto mensual actual del usuario usando el módulo de gastos."""
    gastos_info = resumen_gastos_para_ia(usuario)
    return round(float(gastos_info.get("total_mes", 0.0) or 0.0), 2)

def calcular_edad_usuario(usuario):
    """Obtiene la edad del usuario si existe; usa 23 como fallback."""
    edad_attr = getattr(usuario, "edad", None)
    if edad_attr is not None:
        try:
            edad_val = int(edad_attr)
            if 18 <= edad_val <= 29:
                return edad_val
        except (TypeError, ValueError):
            pass
    return 23

def contar_metas_completadas_usuario(usuario):
    """Cuenta las metas completadas donde el usuario participa."""
    quests = obtener_quests_usuario(usuario)
    return sum(1 for q in quests if q.estatus == "completado")

def construir_questy_input(usuario, quest):
    """Construye el payload real para evaluar una meta con Questy."""
    hoy = date.today()
    dias_restantes = (quest.fecha_limite - hoy).days if quest.fecha_limite else 30
    if dias_restantes <= 0:
        dias_restantes = 1

    participaciones = ParticipacionQuest.query.filter_by(quest_id=quest.id).count()
    colaboradores = max(participaciones - 1, 0)

    total_points_before = int(getattr(usuario, "puntos_totales", 0) or 0)
    _estado_rango_perfil = calcular_estado_rango_perfil(total_points_before)
    completed_goals = contar_metas_completadas_usuario(usuario)
    age = calcular_edad_usuario(usuario)
    monthly_income = calcular_ingreso_mensual_usuario(usuario)
    monthly_expense = calcular_gasto_mensual_usuario(usuario)

    return QuestyInput(
        user_name=getattr(usuario, "nombre", "Usuario") or "Usuario",
        age=age,
        monthly_income=monthly_income,
        monthly_expense=monthly_expense,
        goal_name=quest.nombre,
        goal_amount=float(quest.monto_objetivo or 0),
        deadline_days=dias_restantes,
        collaborators=colaboradores,
        total_points_before=total_points_before,
        current_saved_amount=float(quest.monto_actual or 0),
        completed_goals=completed_goals,
    )

def humanizar_segmento_questy(segmento):
    """Convierte el segmento técnico en una etiqueta legible para UI."""
    if not segmento:
        return "Perfil joven"

    partes = str(segmento).split("_")
    if len(partes) < 3:
        return "Perfil joven"

    ingreso = partes[1]
    presion = partes[2]

    ingreso_map = {
        "bajo": "ingreso bajo",
        "medio": "ingreso medio",
        "alto": "ingreso alto",
    }

    # contemplar segmentos como medio_bajo / medio_alto
    if len(partes) >= 4 and partes[1] == "medio":
        ingreso = f"medio_{partes[2]}"
        presion = partes[3]

    ingreso_map.update({
        "medio_bajo": "ingreso medio-bajo",
        "medio_alto": "ingreso medio-alto",
    })

    presion_map = {
        "baja": "presión baja",
        "media": "presión media",
        "alta": "presión alta",
        "sin_dato": "presión sin dato",
    }

    ingreso_txt = ingreso_map.get(ingreso, ingreso.replace("_", "-"))
    presion_txt = presion_map.get(presion, presion.replace("_", " "))

    return f"Jóvenes con {ingreso_txt} y {presion_txt}"

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

    Devuelve métricas del mes actual y comparación contra el mes anterior.
    """
    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    fin_mes = hoy

    ultimo_dia_mes_anterior = inicio_mes - timedelta(days=1)
    inicio_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)

    gastos_mes = (
        Gasto.query
        .filter(
            Gasto.usuario_id == usuario.id,
            Gasto.fecha >= inicio_mes,
            Gasto.fecha <= fin_mes,
        )
        .all()
    )

    gastos_mes_anterior = (
        Gasto.query
        .filter(
            Gasto.usuario_id == usuario.id,
            Gasto.fecha >= inicio_mes_anterior,
            Gasto.fecha <= ultimo_dia_mes_anterior,
        )
        .all()
    )

    def acumular_metricas(gastos_lista):
        total = 0.0
        por_categoria = {}
        total_hormiga = 0.0
        hormiga_count = 0
        for gasto in gastos_lista:
            monto = float(gasto.monto or 0)
            total += monto

            try:
                cat_nombre = gasto.categoria.nombre if gasto.categoria else "Otros"
            except AttributeError:
                cat_nombre = "Otros"

            por_categoria[cat_nombre] = por_categoria.get(cat_nombre, 0.0) + monto

            if getattr(gasto, "es_hormiga", False):
                total_hormiga += monto
                hormiga_count += 1

        categoria_top = None
        categoria_top_monto = 0.0
        categoria_top_porcentaje = 0.0
        top_3 = []

        if por_categoria:
            categoria_top, categoria_top_monto = max(por_categoria.items(), key=lambda x: x[1])
            if total > 0:
                categoria_top_porcentaje = (categoria_top_monto / total) * 100
            top_3 = sorted(
                [
                    {
                        "nombre": nombre,
                        "monto": monto,
                        "porcentaje": ((monto / total) * 100) if total > 0 else 0.0,
                    }
                    for nombre, monto in por_categoria.items()
                ],
                key=lambda x: x["monto"],
                reverse=True,
            )[:3]

        return {
            "total": round(total, 2),
            "por_categoria": por_categoria,
            "categoria_top": categoria_top,
            "categoria_top_monto": round(categoria_top_monto, 2),
            "categoria_top_porcentaje": round(categoria_top_porcentaje, 2),
            "top_3": top_3,
            "total_hormiga": round(total_hormiga, 2),
            "hormiga_count": hormiga_count,
            "num_gastos": len(gastos_lista),
        }

    actual = acumular_metricas(gastos_mes)
    anterior = acumular_metricas(gastos_mes_anterior)

    total_mes = actual["total"]
    total_mes_anterior = anterior["total"]

    if total_mes_anterior > 0:
        variacion_vs_mes_anterior = ((total_mes - total_mes_anterior) / total_mes_anterior) * 100
    elif total_mes > 0:
        variacion_vs_mes_anterior = 100.0
    else:
        variacion_vs_mes_anterior = 0.0

    if variacion_vs_mes_anterior >= 10:
        tendencia_gasto = "subiendo"
    elif variacion_vs_mes_anterior <= -10:
        tendencia_gasto = "bajando"
    else:
        tendencia_gasto = "estable"

    dias_del_mes_transcurridos = max((fin_mes - inicio_mes).days + 1, 1)
    promedio_diario = total_mes / dias_del_mes_transcurridos if dias_del_mes_transcurridos > 0 else 0.0

    ingreso_estimado = calcular_ingreso_mensual_usuario(usuario)
    porcentaje_ingreso_gastado = ((total_mes / ingreso_estimado) * 100) if ingreso_estimado > 0 else 0.0

    # Margen redirigible conservador para recomendaciones:
    # 30% de gasto hormiga + 15% de la categoría principal.
    margen_redirigible = (actual["total_hormiga"] * 0.30) + (actual["categoria_top_monto"] * 0.15)
    margen_redirigible = round(margen_redirigible, 2)

    return {
        "total_mes": total_mes,
        "total_mes_anterior": total_mes_anterior,
        "variacion_vs_mes_anterior": round(variacion_vs_mes_anterior, 2),
        "tendencia_gasto": tendencia_gasto,
        "promedio_diario": round(promedio_diario, 2),
        "porcentaje_ingreso_gastado": round(porcentaje_ingreso_gastado, 2),
        "margen_redirigible": margen_redirigible,
        "por_categoria": actual["por_categoria"],
        "categoria_top": actual["categoria_top"],
        "categoria_top_monto": actual["categoria_top_monto"],
        "categoria_top_porcentaje": actual["categoria_top_porcentaje"],
        "top_3_categorias": actual["top_3"],
        "total_hormiga": actual["total_hormiga"],
        "hormiga_count": actual["hormiga_count"],
        "num_gastos": actual["num_gastos"],
    }

def seleccionar_meta_prioritaria(resultados_ia):
    """Elige la meta activa que más urge por probabilidad y tiempo restante."""
    activos = [
        item for item in resultados_ia.get("analisis_por_quest", [])
        if item["quest"].estatus not in ["completado", "cancelado"]
    ]

    if not activos:
        return None

    def prioridad(item):
        prob = item.get("probabilidad_num", 0)
        dias_restantes = item.get("dias_restantes", 9999)
        faltante = item.get("faltante", 0)
        return (prob, dias_restantes, -faltante)

    return sorted(activos, key=prioridad)[0]

def generar_resumen_questy_usuario(usuario, resultados_ia, gastos_resumen, questy_panels):
    """Genera un resumen general para la vista de Questy con lectura útil y accionable."""
    resumen = resultados_ia.get("resumen_global", {})
    meta_prioritaria = seleccionar_meta_prioritaria(resultados_ia)

    metas_activas = resumen.get("activos", 0)
    metas_completadas = resumen.get("completados", 0)
    total_mes_gastos = float(gastos_resumen.get("total_mes", 0.0) or 0.0)
    total_mes_anterior = float(gastos_resumen.get("total_mes_anterior", 0.0) or 0.0)
    variacion_vs_mes_anterior = float(gastos_resumen.get("variacion_vs_mes_anterior", 0.0) or 0.0)
    tendencia_gasto = gastos_resumen.get("tendencia_gasto", "estable")
    promedio_diario = float(gastos_resumen.get("promedio_diario", 0.0) or 0.0)
    porcentaje_ingreso_gastado = float(gastos_resumen.get("porcentaje_ingreso_gastado", 0.0) or 0.0)
    margen_redirigible = float(gastos_resumen.get("margen_redirigible", 0.0) or 0.0)
    categoria_top = gastos_resumen.get("categoria_top")
    categoria_top_monto = float(gastos_resumen.get("categoria_top_monto", 0.0) or 0.0)
    categoria_top_porcentaje = float(gastos_resumen.get("categoria_top_porcentaje", 0.0) or 0.0)
    total_hormiga = float(gastos_resumen.get("total_hormiga", 0.0) or 0.0)
    hormiga_count = int(gastos_resumen.get("hormiga_count", 0) or 0)

    if metas_activas == 0:
        respuesta_rapida = (
            "Hoy no tienes metas activas. Un buen siguiente paso sería crear una meta pequeña "
            "para que Questy pueda empezar a medir tu ritmo y darte recomendaciones más precisas."
        )
    else:
        respuesta_rapida = (
            f"Hoy veo {metas_activas} meta(s) activa(s) y {metas_completadas} completada(s). "
            "Ya puedo darte una lectura más clara de tus prioridades y de cómo tus gastos afectan tu avance."
        )

    alerta_texto = None
    if meta_prioritaria:
        q = meta_prioritaria["quest"]
        prob = meta_prioritaria.get("probabilidad_num", 0)
        dias_restantes = meta_prioritaria.get("dias_restantes", 0)
        faltante = meta_prioritaria.get("faltante", 0)
        ahorro_diario = meta_prioritaria.get("ahorro_diario_recomendado", 0)

        if prob <= 40:
            alerta_texto = (
                f"La meta que más urge ahorita es '{q.nombre}': le quedan {dias_restantes} día(s), aún faltan "
                f"{faltante:,.0f} MXN y para mantener el ritmo ideal necesitarías cerca de {ahorro_diario:,.0f} MXN diarios."
            )
        elif total_mes_gastos > 0 and margen_redirigible > 0 and margen_redirigible >= ahorro_diario * 7:
            alerta_texto = (
                f"Tu meta prioritaria sigue siendo '{q.nombre}'. La buena noticia es que tu patrón de gasto actual deja un margen potencial "
                f"de unos {margen_redirigible:,.0f} MXN que podrías redirigir sin tocar todo tu consumo."
            )
        else:
            alerta_texto = (
                f"Tu meta con mayor prioridad actual es '{q.nombre}'. Todavía está en rango manejable, "
                "pero conviene no dejarla enfriarse."
            )
    elif metas_activas > 0:
        alerta_texto = "Tus metas activas no muestran alertas críticas por ahora."

    consejo_texto = None
    if total_mes_gastos > 0 and categoria_top:
        if categoria_top_porcentaje >= 35:
            consejo_texto = (
                f"Tu gasto dominante este mes está en '{categoria_top}' con aproximadamente {categoria_top_monto:,.0f} MXN, "
                f"lo que representa cerca del {categoria_top_porcentaje:,.0f}% de tus gastos del mes. "
                "Ese rubro es el primer lugar donde Questy buscaría margen para empujar tu meta principal."
            )
        else:
            consejo_texto = (
                f"Este mes llevas alrededor de {total_mes_gastos:,.0f} MXN en gastos, con un promedio diario de {promedio_diario:,.0f} MXN. "
                f"La categoría más fuerte por ahora es '{categoria_top}' con {categoria_top_monto:,.0f} MXN."
            )
    elif total_hormiga > 0:
        consejo_texto = (
            f"Llevas alrededor de {total_hormiga:,.0f} MXN en {hormiga_count} gasto(s) hormiga este mes. "
            "Incluso una parte de esa fuga podría convertirse en progreso real para tus metas."
        )
    else:
        consejo_texto = (
            "Aún necesito más gastos registrados para detectar patrones finos, pero ya puedo ayudarte con el ritmo de tus metas."
        )

    if total_mes_anterior > 0:
        consejo_texto += (
            f" Frente al mes anterior, tu gasto va {tendencia_gasto} ({variacion_vs_mes_anterior:+.0f}%)."
        )

    accion_texto = None
    if meta_prioritaria:
        q = meta_prioritaria["quest"]
        ahorro_diario = meta_prioritaria.get("ahorro_diario_recomendado", 0)
        ahorro_semanal = ahorro_diario * 7
        if margen_redirigible > 0:
            accion_texto = (
                f"Si quieres mejorar tu posición ahora mismo, enfócate en '{q.nombre}'. "
                f"Tu meta pide cerca de {ahorro_diario:,.0f} MXN diarios ({ahorro_semanal:,.0f} por semana) y hoy Questy estima un margen redirigible de unos {margen_redirigible:,.0f} MXN."
            )
        else:
            accion_texto = (
                f"Si quieres mejorar tu posición ahora mismo, enfócate en '{q.nombre}' y apunta a unos {ahorro_diario:,.0f} MXN diarios "
                "mientras siga abierta."
            )
    elif metas_activas == 0:
        accion_texto = "Tu mejor siguiente movimiento es crear una meta para que Questy empiece a acompañar tu progreso."
    else:
        accion_texto = "Tu mejor siguiente movimiento es mantener constancia con tus aportes esta semana."

    metas_resumen = []
    for panel in questy_panels[:4]:
        quest = panel["quest"]
        result = panel["result"]
        esfuerzo_mensual = float(result.get("monthly_goal_effort", 0.0) or 0.0)
        puntos_finales = result.get("puntos_finales", quest.puntos_recompensa or 0)

        if margen_redirigible > 0 and esfuerzo_mensual > 0:
            if margen_redirigible >= esfuerzo_mensual:
                lectura_extra = "Tu gasto actual deja un margen que podría cubrir por sí solo el esfuerzo mensual estimado."
            elif margen_redirigible >= (esfuerzo_mensual * 0.5):
                lectura_extra = "Tu patrón de gasto deja un margen parcial que sí podría acelerar esta meta si lo rediriges."
            else:
                lectura_extra = "Esta meta depende más de constancia en aportes que de recortar gasto reciente."
        else:
            lectura_extra = "Aún necesito más gasto registrado para cruzar esta meta con un patrón de consumo sólido."

        metas_resumen.append({
            "id": quest.id,
            "nombre": quest.nombre,
            "puntos_finales": puntos_finales,
            "dificultad": result.get("dificultad_label", "equilibrada"),
            "segmento_legible": panel.get("segmento_legible", humanizar_segmento_questy(result.get("segmento"))),
            "mensaje": result.get("questy_message"),
            "avance": round(float(quest.progreso_porcentaje()), 1),
            "lectura_gasto": lectura_extra,
            "esfuerzo_mensual": round(esfuerzo_mensual, 2),
        })

    return {
        "respuesta_rapida": respuesta_rapida,
        "alerta_texto": alerta_texto,
        "consejo_texto": consejo_texto,
        "accion_texto": accion_texto,
        "metas_resumen": metas_resumen,
        "meta_prioritaria": meta_prioritaria["quest"] if meta_prioritaria else None,
        "tendencia_gasto": tendencia_gasto,
        "variacion_vs_mes_anterior": variacion_vs_mes_anterior,
        "margen_redirigible": margen_redirigible,
        "porcentaje_ingreso_gastado": porcentaje_ingreso_gastado,
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

    total_30_dias = float(sum(m.monto for m in movimientos_recientes) or 0)
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
    # La simulación es una proyección aproximada, no un saldo: se trabaja
    # en float. Mezclarlo con el Decimal de la columna daría TypeError.
    objetivo = float(quest.monto_objetivo or 0)
    total_proyectado = float(quest.monto_actual or 0) + aportes_proyectados
    if total_proyectado > objetivo:
        total_proyectado = objetivo

    faltante = max(objetivo - total_proyectado, 0)

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

    total_ahorrado = float(sum(m.monto for m in movs_todos) or 0)
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
                "categoria": "recordatorio",
                "titulo": "Recordatorio",
                "icono": "alarm",
                "color": "#F97316",
                "quest_id": q.id,
                "mensaje": f"Tu reto '{q.nombre}' está por vencer en {dias_restantes} día(s) y llevas {progreso}% de avance."
            })

        # 2) Reto vencido sin completar
        if dias_restantes < 0 and progreso < 100:
            notificaciones.append({
                "tipo": "danger",
                "categoria": "recordatorio",
                "titulo": "Meta vencida",
                "icono": "alert-circle",
                "color": "#EF4444",
                "quest_id": q.id,
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
                "categoria": "recordatorio",
                "titulo": "Recordatorio",
                "icono": "time",
                "color": "#3B82F6",
                "quest_id": q.id,
                "mensaje": f"Aún no has registrado tu primer ahorro en el reto '{q.nombre}'."
            })
        elif ultimo_mov is not None and progreso < 100:
            dias_sin_mov = (datetime.utcnow() - ultimo_mov.fecha).days
            if dias_sin_mov >= 7:
                notificaciones.append({
                    "tipo": "info",
                    "categoria": "recordatorio",
                    "titulo": "Recordatorio",
                    "icono": "time",
                    "color": "#3B82F6",
                    "quest_id": q.id,
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
                    "categoria": "consejo_ia",
                    "titulo": "Questy consejo",
                    "icono": "sparkles",
                    "color": "#2563EB",
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
                        "categoria": "consejo_ia",
                        "titulo": "Questy consejo",
                        "icono": "sparkles",
                        "color": "#2563EB",
                        "mensaje": (
                            f"Este mes has gastado aproximadamente {categoria_top_monto:,.0f} MXN en '{categoria_top}', "
                            "lo que representa la mayor parte de tus gastos. Revisa si todos esos gastos son realmente necesarios."
                        ),
                    })

                # 6) Muchos gastos hormiga
                if total_hormiga >= 200 and hormiga_count >= 3:
                    notificaciones.append({
                        "tipo": "info",
                        "categoria": "consejo_ia",
                        "titulo": "Questy consejo",
                        "icono": "sparkles",
                        "color": "#2563EB",
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
                    ahorro_30 = float(sum(m.monto for m in movs_30) or 0)
                except Exception:
                    ahorro_30 = 0

                if total_mes > ahorro_30 and total_mes >= 1000 and ahorro_30 > 0:
                    notificaciones.append({
                        "tipo": "warning",
                        "categoria": "consejo_ia",
                        "titulo": "Questy consejo",
                        "icono": "sparkles",
                        "color": "#2563EB",
                        "mensaje": (
                            f"En este mes has gastado alrededor de {total_mes:,.0f} MXN, "
                            f"mientras que has ahorrado cerca de {ahorro_30:,.0f} MXN. "
                            "Quizá valga la pena revisar qué gastos podrías reducir para fortalecer tu ahorro."
                        ),
                    })

    return notificaciones
