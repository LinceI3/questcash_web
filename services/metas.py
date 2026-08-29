# services/metas.py
"""Consultas y bloqueos sobre las metas de ahorro."""
from __future__ import annotations

from models import ParticipacionQuest, Quest


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

def bloquear_quest(quest_id):
    """Relee la meta tomando un bloqueo de fila hasta el fin de la transacción.

    `quest.monto_actual += monto` es leer-modificar-escribir. Sin bloqueo,
    dos aportes simultáneos sobre la misma meta —dos colaboradores a la vez,
    o un doble toque en el móvil— leen el mismo saldo de partida y el
    segundo pisa al primero: un aporte desaparece. En una meta cerca de
    completarse puede además otorgar los puntos de completado dos veces.

    SELECT ... FOR UPDATE hace que el segundo proceso espere a que el
    primero confirme, y entonces lea el saldo ya actualizado.

    En SQLite (desarrollo local) `with_for_update()` se ignora en silencio;
    no importa porque allí no hay concurrencia real.
    """
    return (
        Quest.query
        .filter_by(id=quest_id)
        # populate_existing() es imprescindible, no un adorno. Sin él,
        # SQLAlchemy ejecuta el SELECT ... FOR UPDATE —así que el bloqueo
        # SÍ se toma— pero devuelve la instancia que ya estaba en el mapa
        # de identidad de la sesión, con su monto_actual obsoleto, y
        # descarta los valores recién leídos. El resultado es que el
        # bloqueo no sirve de nada: cada proceso sigue sumando sobre el
        # saldo que leyó antes de esperar. Con 4 workers y 25 aportes
        # simultáneos se perdían 17.
        .populate_existing()
        .with_for_update()
        .first()
    )
