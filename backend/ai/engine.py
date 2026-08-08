from __future__ import annotations

from datetime import date, timedelta

from backend.models import Goal


def decompose_goal(goal: Goal, context: str | None, today: date) -> list[dict]:
    """Create an actionable plan locally so the feature works without a paid AI provider."""
    target = goal.target_date or (today + timedelta(days=90))
    total_days = max(14, (target - today).days)
    title = goal.title.strip()
    context_hint = f" с учётом: {context.strip()}" if context else ""
    templates = [
        f"Сформулировать измеримый результат для «{title}»{context_hint}",
        "Зафиксировать исходную точку и доступные ресурсы",
        "Выбрать один минимальный еженедельный ритуал",
        "Выполнить первый проверочный этап и собрать обратную связь",
        "Скорректировать план по фактическому темпу",
        "Завершить итоговый этап и зафиксировать результат",
    ]
    return [
        {"title": item, "order_index": index, "due_date": today + timedelta(days=round(total_days * (index + 1) / len(templates)))}
        for index, item in enumerate(templates)
    ]


def generate_recommendations(overload: dict, weakest_area: str | None, habit_rate: float) -> list[dict]:
    recommendations: list[dict] = []
    if overload["level"] == "high":
        recommendations.append({
            "kind": "overload", "title": "Снизить плотность дня",
            "body": overload["suggestion"], "action": "Открыть задачи на сегодня",
        })
    if habit_rate < 60:
        recommendations.append({
            "kind": "habits", "title": "Упростить одну привычку",
            "body": "Сделайте минимальную версию привычки настолько короткой, чтобы её можно было выполнить за две минуты.",
            "action": "Выбрать привычку",
        })
    if weakest_area:
        recommendations.append({
            "kind": "balance", "title": f"Поддержать сферу «{weakest_area}»",
            "body": "Добавьте на этой неделе одно небольшое действие именно для этой сферы — без перестройки всего расписания.",
            "action": "Создать задачу",
        })
    if not recommendations:
        recommendations.append({
            "kind": "focus", "title": "Защитить хороший ритм",
            "body": "Ваш план выглядит устойчиво. Забронируйте один 60-минутный блок на самую важную цель.",
            "action": "Добавить фокус-блок",
        })
    return recommendations
