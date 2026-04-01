import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"

segment_df = pd.read_csv(PROCESSED_DIR / "segment_summary.csv", low_memory=False)

RANKS = [
    (0, "Recluta"),
    (400, "Explorador"),
    (900, "Aventurero"),
    (1600, "Estratega"),
    (2600, "Veterano"),
    (4000, "Comandante"),
    (6000, "Maestro Ahorrador"),
    (8500, "Gran Maestro"),
    (12000, "Leyenda Quest"),
]

def estimate_income_level(monthly_income: float) -> str:
    if monthly_income < 6000:
        return "bajo"
    elif monthly_income < 12000:
        return "medio_bajo"
    elif monthly_income < 25000:
        return "medio_alto"
    return "alto"

def estimate_pressure(monthly_income: float, monthly_expense: float) -> str:
    if monthly_income <= 0:
        return "sin_dato"
    ratio = monthly_expense / monthly_income
    if ratio < 0.8:
        return "baja"
    elif ratio < 1.0:
        return "media"
    return "alta"

def build_segment(monthly_income: float, monthly_expense: float) -> str:
    level = estimate_income_level(monthly_income)
    pressure = estimate_pressure(monthly_income, monthly_expense)
    return f"jovenes_{level}_{pressure}"

def get_segment_stats(segmento: str):
    row = segment_df[segment_df["segmento_questy"] == segmento]
    if row.empty:
        return None
    return row.iloc[0].to_dict()

def calculate_base_points(goal_amount: float, deadline_days: int, collaborators: int) -> int:
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

    if deadline_days <= 30:
        deadline_score = 140
    elif deadline_days <= 90:
        deadline_score = 110
    elif deadline_days <= 180:
        deadline_score = 80
    else:
        deadline_score = 50

    collab_score = min(collaborators * 25, 100)

    return amount_score + deadline_score + collab_score

def calculate_context_multiplier(
    monthly_income: float,
    monthly_expense: float,
    goal_amount: float,
    deadline_days: int
):
    segmento = build_segment(monthly_income, monthly_expense)
    stats = get_segment_stats(segmento)

    if not stats:
        return {
            "segmento": segmento,
            "multiplier": 1.0,
            "difficulty_label": "estandar",
            "comparison_note": "Aún no hay benchmark suficiente para tu segmento."
        }

    ahorro_p50 = stats.get("ahorro_p50", 0) or 0
    ahorro_p75 = stats.get("ahorro_p75", 0) or 0

    months = max(deadline_days / 30, 1)
    monthly_goal_effort = goal_amount / months

    benchmark_monthly_saving = ahorro_p50 / 3 if ahorro_p50 else 0
    benchmark_monthly_high = ahorro_p75 / 3 if ahorro_p75 else 0

    if benchmark_monthly_saving <= 0:
        ratio = 1.0
    else:
        ratio = monthly_goal_effort / benchmark_monthly_saving

    if ratio < 0.8:
        multiplier = 0.92
        difficulty_label = "accesible"
    elif ratio < 1.15:
        multiplier = 1.00
        difficulty_label = "equilibrada"
    elif ratio < 1.50:
        multiplier = 1.12
        difficulty_label = "desafiante"
    else:
        multiplier = 1.25
        difficulty_label = "heroica"

    comparison_note = (
        f"Tu meta requiere alrededor de ${monthly_goal_effort:,.0f} al mes; "
        f"en tu segmento el ahorro de referencia ronda ${benchmark_monthly_saving:,.0f} mensuales."
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
    }

def calculate_final_points(base_points: int, multiplier: float) -> int:
    return round(base_points * multiplier)

def get_rank(total_points: int) -> str:
    current = "Recluta"
    for threshold, rank_name in RANKS:
        if total_points >= threshold:
            current = rank_name
    return current

def evaluate_trophies(
    total_points: int,
    completed_goals: int,
    consistency_days: int,
    current_saving_vs_segment: float
):
    trophies = []

    if completed_goals >= 1:
        trophies.append("Primer logro")
    if completed_goals >= 3:
        trophies.append("Cazador de metas")
    if completed_goals >= 5:
        trophies.append("Veterano del ahorro")

    if consistency_days >= 7:
        trophies.append("Paso firme")
    if consistency_days >= 30:
        trophies.append("Constancia de acero")

    if current_saving_vs_segment >= 1.0:
        trophies.append("Sobre la media")
    if current_saving_vs_segment >= 1.5:
        trophies.append("Fuera de serie")
    if current_saving_vs_segment >= 2.0:
        trophies.append("Rompedor de estadísticas")

    if total_points >= 6000:
        trophies.append("Maestro Ahorrador")
    if total_points >= 12000:
        trophies.append("Leyenda Quest")

    return trophies

def generate_questy_message(
    user_name: str,
    rank_name: str,
    final_points: int,
    context: dict,
    trophies: list[str]
):
    diff = context["difficulty_label"]

    if diff == "heroica":
        tone = (
            f"{user_name}, esta meta sí destaca: para tu contexto se considera una misión heroica. "
            f"Por eso gana {final_points} puntos y no una recompensa estándar."
        )
    elif diff == "desafiante":
        tone = (
            f"{user_name}, tu meta va por encima del esfuerzo promedio esperado en tu segmento. "
            f"Eso la vuelve una misión desafiante y eleva su valor a {final_points} puntos."
        )
    elif diff == "equilibrada":
        tone = (
            f"{user_name}, esta meta está bien calibrada para tu contexto actual. "
            f"Se mantiene en {final_points} puntos y te ayuda a progresar con equilibrio."
        )
    else:
        tone = (
            f"{user_name}, esta meta es accesible para tu contexto actual. "
            f"Aun así suma {final_points} puntos y puede ayudarte a ganar ritmo."
        )

    extra = ""
    if trophies:
        extra = f" Además, ya perfilas trofeos como: {', '.join(trophies[:3])}."

    return f"{tone} Tu rango actual es {rank_name}. {context['comparison_note']}{extra}"

def run_demo():
    user = {
        "user_name": "Armando",
        "monthly_income": 9000,
        "monthly_expense": 6500,
        "goal_amount": 8000,
        "deadline_days": 75,
        "collaborators": 1,
        "total_points_before": 1450,
        "completed_goals": 2,
        "consistency_days": 18,
        "current_saving_vs_segment": 1.35,
    }

    base_points = calculate_base_points(
        user["goal_amount"],
        user["deadline_days"],
        user["collaborators"]
    )

    context = calculate_context_multiplier(
        user["monthly_income"],
        user["monthly_expense"],
        user["goal_amount"],
        user["deadline_days"]
    )

    final_points = calculate_final_points(base_points, context["multiplier"])
    total_points_after = user["total_points_before"] + final_points
    rank_name = get_rank(total_points_after)

    trophies = evaluate_trophies(
        total_points_after,
        user["completed_goals"],
        user["consistency_days"],
        user["current_saving_vs_segment"]
    )

    questy_message = generate_questy_message(
        user["user_name"],
        rank_name,
        final_points,
        context,
        trophies
    )

    print("=== DEMO QUESTY ENGINE ===")
    print(f"Segmento: {context['segmento']}")
    print(f"Puntos base: {base_points}")
    print(f"Multiplicador contextual: {context['multiplier']}")
    print(f"Puntos finales: {final_points}")
    print(f"Puntos totales: {total_points_after}")
    print(f"Rango: {rank_name}")
    print(f"Trofeos: {trophies}")
    print("\nMensaje Questy:")
    print(questy_message)

if __name__ == "__main__":
    run_demo()