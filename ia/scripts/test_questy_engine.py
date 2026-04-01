from ia.services.questy_engine import QuestyInput, evaluate_quest


data = QuestyInput(
    user_name="Armando",
    age=23,
    monthly_income=9000,
    monthly_expense=6500,
    goal_name="Viaje",
    goal_amount=8000,
    deadline_days=75,
    collaborators=1,
    total_points_before=1450,
    current_saved_amount=2600,
    completed_goals=2,
)

result = evaluate_quest(data)

print("=== QUESTY RESULT ===")
for k, v in result.to_dict().items():
    print(f"{k}: {v}")