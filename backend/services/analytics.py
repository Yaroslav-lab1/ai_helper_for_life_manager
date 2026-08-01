from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.models import BalanceAssessment, Event, Goal, Habit, Task, User
from backend.services.habits import streak_stats
from backend.services.time import day_bounds_utc, in_timezone, now_for, today_for


def _timezone_name(db: Session, user_id: int) -> str:
    return db.scalar(select(User.timezone).where(User.id == user_id)) or "UTC"


def day_bounds(day: date, timezone_name: str = "UTC") -> tuple[datetime, datetime]:
    return day_bounds_utc(day, timezone_name)


def overload_for_user(
    db: Session, user_id: int, day: date | None = None, timezone_name: str | None = None
) -> dict:
    timezone_name = timezone_name or _timezone_name(db, user_id)
    day = day or today_for(timezone_name)
    start, end = day_bounds(day, timezone_name)
    events = db.scalars(
        select(Event).where(Event.user_id == user_id, Event.start_at < end, Event.end_at > start)
    ).all()
    tasks = db.scalars(
        select(Task).where(Task.user_id == user_id, Task.status.in_(["todo", "in_progress"]))
    ).all()
    scheduled = sum(max(0, int((event.end_at - event.start_at).total_seconds() / 60)) for event in events)
    due_tasks = [task for task in tasks if task.due_at and task.due_at < end]
    urgent = [task for task in due_tasks if task.priority in {"urgent", "high"}]
    due_minutes = sum(task.estimate_minutes for task in due_tasks)
    score = min(100, round((scheduled + due_minutes) / 7.2 + len(urgent) * 8))
    signals: list[str] = []
    if scheduled >= 360:
        signals.append(f"В календаре уже {scheduled // 60} ч {scheduled % 60} мин встреч")
    if len(due_tasks) >= 5:
        signals.append(f"На сегодня приходится {len(due_tasks)} открытых задач")
    if urgent:
        signals.append(f"Срочных или важных задач: {len(urgent)}")
    if not signals:
        signals.append("Нагрузка распределена устойчиво")
    level = "high" if score >= 75 else "medium" if score >= 50 else "low"
    suggestion = (
        "Перенесите одну несрочную задачу и оставьте 30 минут без встреч."
        if level == "high"
        else "Сохраните буфер между крупными блоками."
        if level == "medium"
        else "Есть пространство для одного важного фокус-блока."
    )
    return {
        "level": level,
        "score": score,
        "scheduled_minutes": scheduled,
        "open_tasks": len(due_tasks),
        "urgent_tasks": len(urgent),
        "signals": signals,
        "suggestion": suggestion,
    }


def energy_for_user(
    db: Session, user_id: int, day: date | None = None, timezone_name: str | None = None
) -> dict:
    """Build a deterministic energy forecast from the user's persisted workload and routines."""
    timezone_name = timezone_name or _timezone_name(db, user_id)
    day = day or today_for(timezone_name)
    start, end = day_bounds(day, timezone_name)
    events = db.scalars(
        select(Event).where(Event.user_id == user_id, Event.start_at < end, Event.end_at > start).order_by(Event.start_at)
    ).all()
    tasks = db.scalars(
        select(Task).where(Task.user_id == user_id, Task.status.in_(["todo", "in_progress"]), Task.due_at <= end)
    ).all()
    habits = db.scalars(
        select(Habit).options(selectinload(Habit.checkins)).where(Habit.user_id == user_id, Habit.archived.is_(False))
    ).all()
    completed_habits = sum(1 for habit in habits if any(item.checkin_date == day for item in habit.checkins))
    health_events = [event for event in events if event.category == "health"]
    meeting_events = [event for event in events if event.category == "work"]
    scheduled_minutes = sum(max(0, int((event.end_at - event.start_at).total_seconds() / 60)) for event in events)
    workload = overload_for_user(db, user_id, day, timezone_name)

    # Circadian baseline adjusted by actual calendar density, urgent work and completed routines.
    curve = {6: 42, 7: 52, 8: 65, 9: 78, 10: 88, 11: 91, 12: 82, 13: 66, 14: 58,
             15: 64, 16: 71, 17: 68, 18: 58, 19: 51, 20: 44, 21: 36, 22: 28, 23: 20}
    urgent = sum(1 for task in tasks if task.priority in {"urgent", "high"})
    habit_bonus = min(8, completed_habits * 2)
    load_penalty = min(18, round(scheduled_minutes / 60) * 2 + urgent * 2)
    points: list[dict] = []
    for hour in range(6, 24):
        overlapping = [
            event
            for event in events
            if in_timezone(event.start_at, timezone_name).hour
            <= hour
            < max(
                in_timezone(event.start_at, timezone_name).hour + 1,
                in_timezone(event.end_at, timezone_name).hour,
            )
        ]
        meeting_penalty = sum(7 if event.category == "work" else 3 for event in overlapping)
        recovery_bonus = 7 if any(event.category == "health" for event in overlapping) else 0
        level = max(12, min(98, curve[hour] + habit_bonus - load_penalty - meeting_penalty + recovery_bonus))
        if level >= 78:
            kind, activity, recommendation = "peak", "Высокая концентрация", "Защитите это время для сложной индивидуальной работы."
        elif level <= 42:
            kind, activity, recommendation = "dip", "Возможный спад", "Снизьте когнитивную нагрузку и уберите экраны на короткий перерыв."
        elif recovery_bonus:
            kind, activity, recommendation = "recovery", "Восстановление", "Сохраните движение или спокойную паузу без новых встреч."
        else:
            kind, activity, recommendation = "steady", "Устойчивый темп", "Подходит для встреч, коммуникации и последовательных задач."
        points.append({"hour": hour, "level": level, "kind": kind, "activity": activity, "recommendation": recommendation})

    peak = max(points, key=lambda point: point["level"])
    score = round(sum(point["level"] for point in points[3:12]) / 9)
    status = "Высокий" if score >= 72 else "Средний" if score >= 48 else "Низкий"
    factors = [
        {"label": "Продолжительность сна", "value": "Нет данных", "impact": "Подключите источник здоровья", "tone": "neutral"},
        {"label": "Качество сна", "value": "Нет данных", "impact": "Не влияет на прогноз без измерений", "tone": "neutral"},
        {"label": "Физическая активность", "value": f"{len(health_events)} событий", "impact": "+ восстановление" if health_events else "Запланируйте движение", "tone": "positive" if health_events else "neutral"},
        {"label": "Количество встреч", "value": str(len(meeting_events)), "impact": "Высокая нагрузка" if len(meeting_events) >= 4 else "Умеренно", "tone": "negative" if len(meeting_events) >= 4 else "positive"},
        {"label": "Экранное время", "value": "Нет данных", "impact": "Подключите источник активности", "tone": "neutral"},
        {"label": "Рабочая нагрузка", "value": f"{workload['score']}/100", "impact": workload["level"], "tone": "negative" if workload["level"] == "high" else "positive"},
    ]
    recommendations = [
        {"time": f"{peak['hour']:02d}:00", "title": "Сложная задача", "body": "Начните наиболее требовательную работу в прогнозируемый пик концентрации.", "kind": "focus"},
        {"time": "14:00", "title": "Короткий перерыв", "body": "После обеда оставьте 20 минут без встреч и экранов.", "kind": "recovery"},
        {"time": "16:00", "title": "Встречи и коммуникация", "body": "Во второй устойчивый период удобно обсуждать решения с командой.", "kind": "meeting"},
        {"time": "19:00", "title": "Движение", "body": "Небольшая физическая активность поддержит вечернее восстановление.", "kind": "health"},
        {"time": "22:00", "title": "Подготовка ко сну", "body": "Снизьте яркость экранов и завершите рабочие коммуникации.", "kind": "sleep"},
    ]
    return {"date": day, "score": score, "status": status, "peak_start": f"{peak['hour']:02d}:00", "peak_end": f"{min(23, peak['hour'] + 2):02d}:00", "points": points, "factors": factors, "recommendations": recommendations}


def analytics_for_user(
    db: Session, user_id: int, days: int = 30, timezone_name: str | None = None
) -> dict:
    timezone_name = timezone_name or _timezone_name(db, user_id)
    today = today_for(timezone_name)
    since_date = today - timedelta(days=days - 1)
    since, _ = day_bounds(since_date, timezone_name)
    tasks = db.scalars(select(Task).where(Task.user_id == user_id, Task.created_at >= since)).all()
    completed = [task for task in tasks if task.status == "done"]
    focus_minutes = sum(task.estimate_minutes for task in completed)

    habits = db.scalars(
        select(Habit).options(selectinload(Habit.checkins)).where(Habit.user_id == user_id, Habit.archived.is_(False))
    ).all()
    possible = sum(min(days, habit.target_per_week * max(1, round(days / 7))) for habit in habits)
    actual = sum(sum(1 for checkin in habit.checkins if checkin.checkin_date >= since_date) for habit in habits)

    goals = db.scalars(select(Goal).where(Goal.user_id == user_id, Goal.status == "active")).all()
    latest_balance = db.scalar(
        select(BalanceAssessment).where(BalanceAssessment.user_id == user_id).order_by(BalanceAssessment.assessment_date.desc())
    )
    balance_score = None
    if latest_balance:
        values = [latest_balance.health, latest_balance.career, latest_balance.finance, latest_balance.relationships,
                  latest_balance.growth, latest_balance.recreation, latest_balance.environment, latest_balance.contribution]
        balance_score = round(sum(values) / len(values), 1)

    by_day = Counter(
        in_timezone(task.completed_at, timezone_name).date().isoformat()
        for task in completed
        if task.completed_at
    )
    events = db.scalars(select(Event).where(Event.user_id == user_id, Event.start_at >= since)).all()
    category_minutes: Counter[str] = Counter()
    for event in events:
        category_minutes[event.category] += max(0, int((event.end_at - event.start_at).total_seconds() / 60))

    productive_days = []
    for offset in range(min(days, 14) - 1, -1, -1):
        current = today - timedelta(days=offset)
        productive_days.append({"date": current.isoformat(), "completed": by_day[current.isoformat()]})
    return {
        "period_days": days,
        "tasks_completed": len(completed),
        "task_completion_rate": round(len(completed) / max(1, len(tasks)) * 100, 1),
        "focus_minutes": focus_minutes,
        "habit_completion_rate": round(min(1, actual / max(1, possible)) * 100, 1),
        "active_goal_progress": round(sum(goal.progress for goal in goals) / max(1, len(goals)), 1),
        "balance_score": balance_score,
        "productive_days": productive_days,
        "category_minutes": dict(category_minutes),
    }


def dashboard_for_user(db: Session, user: User) -> dict:
    local_now = now_for(user.timezone)
    today = local_now.date()
    start, end = day_bounds(today, user.timezone)
    events = db.scalars(
        select(Event).where(Event.user_id == user.id, Event.start_at < end, Event.end_at > start).order_by(Event.start_at)
    ).all()
    tasks = db.scalars(
        select(Task).where(Task.user_id == user.id, Task.status.in_(["todo", "in_progress"])).order_by(Task.due_at)
    ).all()
    due = [task for task in tasks if task.due_at and task.due_at < end]
    completed_today = db.scalars(
        select(Task).where(Task.user_id == user.id, Task.status == "done", Task.completed_at >= start, Task.completed_at < end)
    ).all()
    goals = db.scalars(
        select(Goal).where(Goal.user_id == user.id, Goal.status == "active").order_by(Goal.target_date).limit(3)
    ).all()
    habits = db.scalars(
        select(Habit).options(selectinload(Habit.checkins)).where(Habit.user_id == user.id, Habit.archived.is_(False))
    ).all()
    habit_data = [
        {"id": h.id, "title": h.title, "emoji": h.emoji, "color": h.color, **streak_stats(h, today)}
        for h in habits
    ]
    rate = round(sum(1 for h in habit_data if h["completed_today"]) / max(1, len(habit_data)) * 100, 1)
    overload = overload_for_user(db, user.id, today, user.timezone)
    hour = local_now.hour
    greeting = "Доброе утро" if hour < 12 else "Добрый день" if hour < 18 else "Добрый вечер"
    focus_score = max(10, min(98, round(92 - overload["score"] * 0.35 + rate * 0.25)))
    return {
        "greeting": f"{greeting}, {user.name.split()[0]}",
        "date_label": today.strftime("%d.%m.%Y"),
        "focus_score": focus_score,
        "tasks_due": len(due),
        "completed_today": len(completed_today),
        "habit_rate": rate,
        "events_today": [
            {
                "id": e.id,
                "title": e.title,
                "start_at": in_timezone(e.start_at, user.timezone).isoformat(),
                "end_at": in_timezone(e.end_at, user.timezone).isoformat(),
                "category": e.category,
                "color": e.color,
                "location": e.location,
            }
            for e in events
        ],
        "priority_tasks": [
            {
                "id": t.id,
                "title": t.title,
                "priority": t.priority,
                "due_at": in_timezone(t.due_at, user.timezone).isoformat() if t.due_at else None,
                "estimate_minutes": t.estimate_minutes,
                "project": t.project,
            }
            for t in (due[:4] or tasks[:4])
        ],
        "goals": [{"id": g.id, "title": g.title, "progress": g.progress, "target_date": g.target_date.isoformat() if g.target_date else None} for g in goals],
        "habits": habit_data,
        "overload": overload,
        "recommendation": None,
    }
