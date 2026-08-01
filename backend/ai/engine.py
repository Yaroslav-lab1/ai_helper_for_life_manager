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


def compose_chat_reply(message: str, context: dict, name: str) -> str:
    lower = message.lower()
    tasks = context.get("open_tasks", 0)
    events = context.get("events_today", 0)
    overload = context.get("overload", "low")
    selected_date = context.get("selected_date", "сегодня")
    free_minutes = context.get("free_minutes", 0)
    energy = context.get("energy", 0)
    peak = context.get("energy_peak", "10:00")
    if any(word in lower for word in ("план", "сегодня", "успеть")):
        return (
            f"{name}, на {selected_date} у вас {events} событий, {tasks} открытых задач и около {free_minutes // 60} ч {free_minutes % 60} мин свободных окон. "
            f"Прогноз энергии — {energy}/100, пик около {peak}. Предлагаю выбрать один обязательный результат и защитить 45–60 минут фокуса в этом окне. "
            "Остальные задачи разделите на короткие действия до 20 минут и то, что можно спокойно перенести."
        )
    if any(word in lower for word in ("сложн", "концентрац", "фокус")):
        return f"Лучшее окно для сложной задачи на {selected_date} начинается около {peak}: прогноз энергии {energy}/100. Перед ним оставьте 15 минут без встреч, а сам блок ограничьте 60–90 минутами."
    if any(word in lower for word in ("тренир", "спорт", "движ")):
        return f"На {selected_date} доступно примерно {free_minutes // 60} ч свободного времени. Для тренировки лучше выбрать вечернее окно после 18:00: оно поддержит восстановление и не займёт пик концентрации около {peak}."
    if any(word in lower for word in ("встреч", "созвон")):
        return f"На {selected_date} в календаре {events} событий. При уровне нагрузки «{overload}» новые встречи лучше ставить после 15:00 и сохранять не менее 20 минут между блоками."
    if any(word in lower for word in ("устал", "перегруз", "выгор")):
        note = "Нагрузка действительно выглядит высокой." if overload == "high" else "Явного пика нагрузки в данных нет, но ваше ощущение важнее метрики."
        return f"{note} На ближайшие два часа оставьте только одну необходимую задачу, уберите уведомления и запланируйте короткое восстановление. Что сейчас можно безболезненно отменить или перенести?"
    if any(word in lower for word in ("цель", "начать", "мотивац")):
        return "Выберите самый маленький наблюдаемый шаг, который займёт не больше 15 минут. После него не оценивайте всю цель — оцените только, стал ли следующий шаг понятнее. Я могу помочь сформулировать такой шаг для конкретной цели."
    return (
        f"Я сопоставил ваш вопрос с текущим планом: {tasks} открытых задач, {events} событий сегодня, уровень нагрузки — {overload}. "
        "Сейчас полезнее всего уточнить желаемый результат и ближайшее ограничение. Опишите, что должно измениться к концу дня, и я предложу конкретный порядок действий."
    )
