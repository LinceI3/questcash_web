# services/movimientos.py
"""Registrar un aporte o retiro, y todo lo que eso desencadena.

Es el camino por el que pasa el dinero: crea el movimiento, actualiza el saldo
bajo bloqueo de fila, recalcula la recompensa, marca la meta como completada y
dispara puntos, insignias y bonus de racha.

Los efectos de INTERFAZ —los avisos emergentes de la web— no viven aquí. Entran
por el objeto `efectos`, igual que en services/insignias.py, para que la misma
función sirva a la vista HTML y a la API sin que ninguna arrastre las
dependencias de la otra. Sin `efectos`, las llamadas son inocuas.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ia.services.questy_engine import evaluate_quest
from models import Movimiento, ParticipacionQuest, Quest, db
from services import analisis, metas, rachas, rangos


class Efectos:
    """Efectos de interfaz que el servicio no debe conocer.

    Por omisión no hacen nada: así el servicio se puede llamar desde una prueba
    o desde un script sin montar Flask.
    """

    def emitir_flash_logro(self, *a, **k):
        pass

    def emitir_flash_subida_rango(self, *a, **k):
        pass

    def crear_notificacion(self, *a, **k):
        pass

    def checar_insignias_por_evento(self, *a, **k):
        pass


def otorgar_puntos_por_completado(quest, events=None, efectos=None):
    efectos = efectos or Efectos()
    """
    Reparte los puntos del reto entre todos los participantes
    (creador + colaboradores) cuando se completa, dispara insignias
    y avisa si algún usuario sube de rango.
    """
    if quest.puntos_otorgados or quest.puntos_recompensa <= 0:
        return

    def notificar_subida_rango(usuario, puntos_ganados):
        puntos_antes = int((getattr(usuario, "puntos_totales", 0) or 0) - puntos_ganados)
        if puntos_antes < 0:
            puntos_antes = 0

        rango_antes = rangos.estado(puntos_antes)
        rango_despues = rangos.estado(getattr(usuario, "puntos_totales", 0) or 0)

        if rango_antes["current_key"] != rango_despues["current_key"]:
            efectos.emitir_flash_subida_rango(rango_despues)
            if events is not None:
                events.append({
                    "type": "rank_up",
                    "rank_key": rango_despues["current_key"],
                    "rank_name": rango_despues["current_name"],
                    "rank_color": rango_despues["current_color"],
                    "rank_accent": rango_despues["current_accent"],
                    "points": rango_despues["points"],
                    "is_max_rank": rango_despues["is_max_rank"],
                    "next_name": rango_despues.get("next_name"),
                    "points_remaining": rango_despues.get("points_remaining", 0),
                })

    participaciones = ParticipacionQuest.query.filter_by(quest_id=quest.id).all()

    if not participaciones:
        # Solo el creador
        quest.usuario.puntos_totales += quest.puntos_recompensa
        notificar_subida_rango(quest.usuario, quest.puntos_recompensa)
        efectos.crear_notificacion(
            quest.usuario,
            tipo="meta_completada",
            titulo="¡Meta completada!",
            mensaje=f"Felicidades, completaste {quest.nombre}.",
            icono="trophy",
            color="#22C55E",
            quest=quest,
        )
        quest.puntos_otorgados = True
        # Insignias para el creador
        efectos.checar_insignias_por_evento(quest.usuario, "reto_completado", quest=quest, events=events)
        return

    num_participantes = len(participaciones)
    puntos_por_usuario = max(1, int(round(quest.puntos_recompensa / num_participantes)))

    for p in participaciones:
        p.usuario.puntos_totales += puntos_por_usuario
        notificar_subida_rango(p.usuario, puntos_por_usuario)
        efectos.crear_notificacion(
            p.usuario,
            tipo="meta_completada",
            titulo="¡Meta completada!",
            mensaje=f"Felicidades, completaste {quest.nombre}.",
            icono="trophy",
            color="#22C55E",
            quest=quest,
        )
        efectos.checar_insignias_por_evento(p.usuario, "reto_completado", quest=quest, events=events)

    quest.puntos_otorgados = True

def otorgar_bonus_racha(usuario, rachas_antes, rachas_despues, events=None, efectos=None):
    efectos = efectos or Efectos()
    """
    Asigna puntos extra cuando el usuario alcanza nuevas rachas de días consecutivos
    ahorrando. Solo se otorga bonus cuando la racha actual cruza ciertos umbrales.

    Si se pasa `events` (lista), se le agrega un dict estructurado por cada bonus
    otorgado, además del flash() de siempre — así los consumidores de la API JSON
    pueden devolver el evento sin depender del sistema de flash (session/HTML).
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
            efectos.emitir_flash_logro(
                titulo="Racha desbloqueada",
                mensaje=f"🔥 Alcanzaste {limite} días seguidos ahorrando y ganaste +{puntos} puntos QuestCash.",
                extra={
                    "streak_days": limite,
                    "points_bonus": puntos,
                },
            )
            if events is not None:
                events.append({
                    "type": "streak_bonus",
                    "streak_days": limite,
                    "points_bonus": puntos,
                })

def procesar_registro_movimiento(usuario, quest, tipo, monto_float, nota, categoria, events=None, efectos=None):
    efectos = efectos or Efectos()
    """Registra un movimiento (aporte/retiro) sobre una meta: crea el Movimiento,
    actualiza monto/estatus de la meta, recalcula la recompensa vía IA (con
    fallback) y dispara premios (puntos, insignias, racha).

    Comparte la lógica antes duplicada entre `nuevo_movimiento` y su alias
    `crear_movimiento`, y la reutiliza también la API JSON. No hace commit;
    el caller es responsable de eso.
    """
    # Bloqueo de la fila ANTES de leer el saldo: a partir de aquí ningún
    # otro proceso puede modificar esta meta hasta que se confirme la
    # transacción. Se relee la instancia bloqueada para no operar sobre una
    # copia con datos ya obsoletos.
    bloqueada = metas.bloquear_quest(quest.id)
    if bloqueada is not None:
        quest = bloqueada

    rachas_antes = rachas.calcular_de_usuario(usuario)

    movimiento = Movimiento(
        tipo=tipo,
        monto=monto_float,
        nota=nota,
        categoria=categoria,
        usuario_id=usuario.id,
        quest_id=quest.id,
    )
    db.session.add(movimiento)

    if tipo == "aporte":
        quest.monto_actual += monto_float
    else:
        quest.monto_actual -= monto_float

    # Avisar a los demás colaboradores (no a quien aportó) cuando el
    # movimiento es un aporte a una meta colaborativa.
    if tipo == "aporte" and quest.tipo == "colaborativo":
        otros_participantes = (
            ParticipacionQuest.query
            .filter(ParticipacionQuest.quest_id == quest.id, ParticipacionQuest.usuario_id != usuario.id)
            .all()
        )
        for participacion in otros_participantes:
            efectos.crear_notificacion(
                participacion.usuario,
                tipo="aporte_colaborador",
                titulo="Aporte recibido",
                mensaje=f"{usuario.nombre} aportó ${monto_float:,.0f} a {quest.nombre}.",
                icono="people-circle",
                color="#16A34A",
                quest=quest,
            )

    # Recalcular la recompensa contextual del reto antes de evaluar si se completa.
    # Así, los puntos que se muestran y los que realmente se otorgan salen de la misma fuente.
    try:
        questy_input = analisis.construir_questy_input(usuario, quest)
        questy_result = evaluate_quest(questy_input)
        quest.puntos_recompensa = int(questy_result.puntos_finales or 0)
    except Exception:
        pass

    # Actualizar estatus automáticamente
    if quest.monto_actual >= quest.monto_objetivo and quest.estatus != "cancelado":
        quest.monto_actual = quest.monto_objetivo
        if quest.estatus != "completado":
            quest.estatus = "completado"
            otorgar_puntos_por_completado(quest, events=events, efectos=efectos)
    elif quest.monto_actual > 0 and quest.estatus == "pendiente":
        quest.estatus = "en_progreso"

    # Insignia por primer movimiento (si aplica)
    efectos.checar_insignias_por_evento(usuario, "primer_movimiento", events=events)

    # Bonus por racha solo para aportes
    if tipo == "aporte":
        # Asegurar que el movimiento actual esté en la sesión al recalcular
        db.session.flush()
        rachas_despues = rachas.calcular_de_usuario(usuario)
        otorgar_bonus_racha(usuario, rachas_antes, rachas_despues, events=events, efectos=efectos)

    return movimiento
