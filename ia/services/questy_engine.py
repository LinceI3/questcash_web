from __future__ import annotations

from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
SEGMENT_SUMMARY_PATH = PROCESSED_DIR / "segment_summary.csv"


@dataclass
class QuestyInput:
    user_name: str
    age: int
    monthly_income: float
    monthly_expense: float
    goal_name: str
    goal_amount: float
    deadline_days: int
    collaborators: int
    total_points_before: int = 0
    current_saved_amount: float = 0.0
    completed_goals: int = 0


@dataclass
class QuestyResult:
    segmento: str
    puntos_base: int
    multiplicador_contextual: float
    puntos_finales: int
    puntos_totales: int
    rango_actual: str | None
    dificultad_label: str
    comparison_note: str
    benchmark_monthly_saving: float
    benchmark_monthly_high: float
    monthly_goal_effort: float
    ratio_vs_segment: float
    benchmark_is_reliable: bool
    progress_ratio: float
    progress_percent: float
    status_label: str
    questy_message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=1)
def load_segment_summary() -> pd.DataFrame:
    if not SEGMENT_SUMMARY_PATH.exists():
        raise FileNotFoundError(
            f"No existe {SEGMENT_SUMMARY_PATH}. "
            "Ejecuta primero: python ia/scripts/build_segment_summary.py"
        )
    return pd.read_csv(SEGMENT_SUMMARY_PATH, low_memory=False)


def estimate_income_level(monthly_income: float) -> str:
    if monthly_income < 6000:
        return "bajo"
    if monthly_income < 12000:
        return "medio_bajo"
    if monthly_income < 25000:
        return "medio_alto"
    return "alto"


def estimate_pressure(monthly_income: float, monthly_expense: float) -> str:
    if monthly_income <= 0:
        return "sin_dato"

    ratio = monthly_expense / monthly_income

    if ratio < 0.8:
        return "baja"
    if ratio < 1.0:
        return "media"
    return "alta"


def build_segment(age: int, monthly_income: float, monthly_expense: float) -> str:
    # La edad queda disponible para reglas futuras más finas,
    # pero el benchmark actual se alinea con ingreso + presión.
    level = estimate_income_level(monthly_income)
    pressure = estimate_pressure(monthly_income, monthly_expense)
    return f"jovenes_{level}_{pressure}"


def get_segment_stats(segmento: str) -> Optional[Dict[str, Any]]:
    df = load_segment_summary()
    row = df[df["segmento_questy"] == segmento]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def calculate_base_points(goal_amount: float, deadline_days: int, collaborators: int) -> int:
    # Puntos por monto
    if goal_amount < 1000:
        amount_score = 80
    elif goal_amount < 3000:
        amount_score = 140
    elif goal_amount < 7000:
        amount_score = 220
    elif goal_amount < 15000:
        amount_score = 320
    else:
        amount_score = 450

    # Puntos por plazo: menor plazo = mayor dificultad
    if deadline_days <= 30:
        deadline_score = 140
    elif deadline_days <= 90:
        deadline_score = 110
    elif deadline_days <= 180:
        deadline_score = 80
    else:
        deadline_score = 50

    # Puntos por colaboración
    collab_score = min(max(collaborators, 0) * 25, 100)

    return amount_score + deadline_score + collab_score


def calculate_context_multiplier(
    age: int,
    monthly_income: float,
    monthly_expense: float,
    goal_amount: float,
    deadline_days: int,
) -> Dict[str, Any]:
    segmento = build_segment(age, monthly_income, monthly_expense)
    stats = get_segment_stats(segmento)

    if not stats:
        return {
            "segmento": segmento,
            "multiplier": 1.00,
            "difficulty_label": "equilibrada",
            "comparison_note": "Aún no hay benchmark suficiente para tu segmento.",
            "benchmark_monthly_saving": 0.0,
            "benchmark_monthly_high": 0.0,
            "monthly_goal_effort": max(goal_amount / max(deadline_days / 30, 1), 0),
            "ratio_vs_segment": 1.0,
            "benchmark_is_reliable": False,
        }

    ahorro_p50 = float(stats.get("ahorro_p50", 0) or 0)
    ahorro_p75 = float(stats.get("ahorro_p75", 0) or 0)

    months = max(deadline_days / 30, 1)
    monthly_goal_effort = goal_amount / months

    # ENIGH está en trimestral; lo llevamos a mensual aproximado
    benchmark_monthly_saving = ahorro_p50 / 3 if ahorro_p50 else 0.0
    benchmark_monthly_high = ahorro_p75 / 3 if ahorro_p75 else 0.0

    benchmark_is_reliable = benchmark_monthly_saving > 0

    if not benchmark_is_reliable:
        ratio = 1.0
    else:
        ratio = monthly_goal_effort / benchmark_monthly_saving

    # Aquí ya NO castigamos puntos. Solo bonificamos según mérito contextual.
    if ratio < 0.8:
        multiplier = 1.00
        difficulty_label = "accesible"
    elif ratio < 1.15:
        multiplier = 1.08
        difficulty_label = "equilibrada"
    elif ratio < 1.50:
        multiplier = 1.16
        difficulty_label = "desafiante"
    else:
        multiplier = 1.28
        difficulty_label = "heroica"

    if benchmark_is_reliable:
        comparison_note = (
            f"Tu meta requiere alrededor de ${monthly_goal_effort:,.0f} al mes; "
            f"en perfiles comparables el ahorro mensual de referencia ronda ${benchmark_monthly_saving:,.0f}."
        )
    else:
        comparison_note = (
            f"Tu meta requiere alrededor de ${monthly_goal_effort:,.0f} al mes. "
            "Todavía no tengo una referencia positiva suficientemente clara para tu segmento, "
            "así que estoy usando una lectura contextual conservadora."
        )

    return {
        "segmento": segmento,
        "multiplier": multiplier,
        "difficulty_label": difficulty_label,
        "comparison_note": comparison_note,
        "benchmark_monthly_saving": benchmark_monthly_saving,
        "benchmark_monthly_high": benchmark_monthly_high,
        "monthly_goal_effort": monthly_goal_effort,
        "ratio_vs_segment": ratio,
        "benchmark_is_reliable": benchmark_is_reliable,
    }


def calculate_final_points(base_points: int, multiplier: float) -> int:
    return round(base_points * multiplier)


def calculate_progress_ratio(current_saved_amount: float, goal_amount: float) -> float:
    if goal_amount <= 0:
        return 0.0
    ratio = current_saved_amount / goal_amount
    return max(0.0, min(ratio, 1.5))


def get_status_label(progress_ratio: float, ratio_vs_segment: float) -> str:
    if progress_ratio >= 1.0:
        return "meta_completada"
    if progress_ratio >= 0.75 and ratio_vs_segment >= 1.0:
        return "avance_solido"
    if progress_ratio >= 0.40:
        return "avance_estable"
    return "inicio_mision"


def generate_questy_message(data: QuestyInput, context: Dict[str, Any]) -> str:
    diff = context["difficulty_label"]
    effort = context["monthly_goal_effort"]
    benchmark = context["benchmark_monthly_saving"]
    benchmark_is_reliable = context.get("benchmark_is_reliable", True)

    if diff == "heroica":
        opener = (
            f"{data.user_name}, tu reto \"{data.goal_name}\" entra en la categoría heroica. "
            f"Para un perfil como el tuyo exige bastante más que el ahorro típico de referencia."
        )
    elif diff == "desafiante":
        opener = (
            f"{data.user_name}, tu reto \"{data.goal_name}\" está por encima del esfuerzo promedio esperado en tu segmento. "
            f"Es una misión desafiante y por eso vale más puntos."
        )
    elif diff == "equilibrada":
        opener = (
            f"{data.user_name}, tu reto \"{data.goal_name}\" está bien calibrado para tu contexto actual. "
            f"Tiene buen valor y mantiene una progresión sana."
        )
    else:
        opener = (
            f"{data.user_name}, tu reto \"{data.goal_name}\" es accesible para tu contexto actual. "
            f"Eso lo vuelve una buena misión para avanzar con constancia."
        )

    progress_ratio = calculate_progress_ratio(data.current_saved_amount, data.goal_amount)
    progress_percent = round(progress_ratio * 100, 1)

    if progress_ratio >= 1.0:
        progress_line = (
            f"Ya alcanzaste el 100% de la meta, así que esta misión debería quedar marcada como completada."
        )
    elif progress_ratio >= 0.75:
        progress_line = (
            f"Llevas {progress_percent}% de avance, así que ya estás en la parte final del recorrido."
        )
    elif progress_ratio >= 0.40:
        progress_line = (
            f"Llevas {progress_percent}% de avance, lo cual indica que ya construiste una base sólida."
        )
    else:
        progress_line = (
            f"Llevas {progress_percent}% de avance; todavía estás en la fase de arranque, pero ya sumas progreso real."
        )

    if benchmark_is_reliable:
        comparison_line = (
            f"Tu meta pide cerca de ${effort:,.0f} al mes, mientras que el ahorro mensual de referencia para perfiles comparables ronda ${benchmark:,.0f}."
        )
    else:
        comparison_line = (
            f"Tu meta pide cerca de ${effort:,.0f} al mes. "
            "Por ahora estoy usando una referencia contextual conservadora porque tu segmento aún no muestra una base positiva suficientemente clara."
        )

    closing = ""

    return f"{opener} {progress_line} {comparison_line} {closing}".strip()


def evaluate_quest(data: QuestyInput) -> QuestyResult:
    base_points = calculate_base_points(
        goal_amount=data.goal_amount,
        deadline_days=data.deadline_days,
        collaborators=data.collaborators,
    )

    context = calculate_context_multiplier(
        age=data.age,
        monthly_income=data.monthly_income,
        monthly_expense=data.monthly_expense,
        goal_amount=data.goal_amount,
        deadline_days=data.deadline_days,
    )

    final_points = calculate_final_points(base_points, context["multiplier"])
    total_points = data.total_points_before + final_points

    progress_ratio = calculate_progress_ratio(
        current_saved_amount=data.current_saved_amount,
        goal_amount=data.goal_amount,
    )
    progress_percent = round(progress_ratio * 100, 1)
    status_label = get_status_label(progress_ratio, context["ratio_vs_segment"])

    questy_message = generate_questy_message(
        data=data,
        context=context,
    )

    return QuestyResult(
        segmento=context["segmento"],
        puntos_base=base_points,
        multiplicador_contextual=context["multiplier"],
        puntos_finales=final_points,
        puntos_totales=total_points,
        rango_actual=None,
        dificultad_label=context["difficulty_label"],
        comparison_note=context["comparison_note"],
        benchmark_monthly_saving=context["benchmark_monthly_saving"],
        benchmark_monthly_high=context["benchmark_monthly_high"],
        monthly_goal_effort=context["monthly_goal_effort"],
        ratio_vs_segment=context["ratio_vs_segment"],
        benchmark_is_reliable=context.get("benchmark_is_reliable", True),
        progress_ratio=progress_ratio,
        progress_percent=progress_percent,
        status_label=status_label,
        questy_message=questy_message,
    )