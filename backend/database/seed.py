from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import SessionLocal
from backend.models import (
    BalanceAssessment,
    Event,
    Goal,
    GoalStep,
    Habit,
    HabitCheckin,
    Recommendation,
    Task,
    User,
    UserSettings,
)
from backend.services.security import hash_password
from backend.services.time import local_datetime_utc, today_for


SeedModel = TypeVar("SeedModel", Event, Task, Goal, Habit, BalanceAssessment, Recommendation)


def _sync(db: Session, model: type[SeedModel], user_id: int, key: str, values: dict[str, Any]) -> SeedModel:
    item = db.scalar(
        select(model).where(model.user_id == user_id, model.demo_seed_key == key)
    )
    if item is None:
        item = model(user_id=user_id, demo_seed_key=key, **values)
        db.add(item)
    else:
        for name, value in values.items():
            setattr(item, name, value)
    db.flush()
    return item


def seed_demo() -> None:
    if settings.is_production:
        raise RuntimeError("Demo seed is disabled in production")
    if not settings.enable_demo_seed:
        raise RuntimeError("Set ENABLE_DEMO_SEED=true to run the explicit development demo seed")
    if len(settings.demo_password) < 12:
        raise RuntimeError("DEMO_PASSWORD must contain at least 12 characters")

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == settings.demo_email.lower()))
        if user is None:
            user = User(
                email=settings.demo_email.lower(),
                hashed_password=hash_password(settings.demo_password),
                name="Алексей Ветров",
                occupation="Product designer",
                timezone="Europe/Moscow",
                avatar_color="#7857FF",
            )
            db.add(user)
            db.flush()
            db.add(UserSettings(user_id=user.id, weekly_focus_hours=14, daily_digest_time="08:00"))
        elif user.settings is None:
            db.add(UserSettings(user_id=user.id))

        today = today_for(user.timezone)

        def at(hour: int, minute: int = 0, offset: int = 0) -> datetime:
            return local_datetime_utc(today + timedelta(days=offset), time(hour, minute), user.timezone)

        event_specs = [
            ("morning-focus", {"title": "Утренний фокус", "start_at": at(9), "end_at": at(10, 30), "category": "focus", "color": "#7857FF", "recurrence_rule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "reminder_minutes": 10}),
            ("product-sync", {"title": "Синк с продуктовой командой", "start_at": at(11), "end_at": at(11, 45), "category": "work", "color": "#FF8A65", "location": "Google Meet", "reminder_minutes": 10}),
            ("screen-free-lunch", {"title": "Обед без экрана", "start_at": at(13), "end_at": at(13, 45), "category": "health", "color": "#00B894"}),
            ("workout", {"title": "Тренировка", "start_at": at(19), "end_at": at(20), "category": "health", "color": "#2D9CDB", "location": "Фитнес-клуб", "reminder_minutes": 30}),
            ("weekly-review", {"title": "Разбор недельных итогов", "start_at": at(16, offset=1), "end_at": at(17, offset=1), "category": "personal", "color": "#F2C94C"}),
        ]
        for key, values in event_specs:
            _sync(db, Event, user.id, key, values)

        task_specs = [
            ("onboarding-prototype", {"title": "Подготовить прототип онбординга", "due_at": at(12, 30), "priority": "urgent", "estimate_minutes": 80, "energy": "high", "project": "Axel Mobile", "reminder_at": at(9, 30), "status": "todo", "completed_at": None}),
            ("interview-notes", {"title": "Отправить заметки после интервью", "due_at": at(15), "priority": "high", "estimate_minutes": 25, "energy": "low", "project": "Research", "status": "todo", "completed_at": None}),
            ("dentist", {"title": "Записаться к стоматологу", "due_at": at(18), "priority": "medium", "estimate_minutes": 10, "energy": "low", "project": "Личное", "status": "todo", "completed_at": None}),
            ("portfolio", {"title": "Обновить портфолио — кейс аналитики", "due_at": at(18, offset=2), "priority": "medium", "estimate_minutes": 90, "energy": "high", "project": "Развитие", "status": "todo", "completed_at": None}),
            ("systems-reading", {"title": "Прочитать главу о системном мышлении", "due_at": at(21, offset=1), "priority": "low", "estimate_minutes": 35, "energy": "medium", "project": "Развитие", "status": "todo", "completed_at": None}),
            ("interview-questions", {"title": "Сформировать вопросы для интервью", "due_at": at(10, offset=-1), "priority": "high", "status": "done", "estimate_minutes": 40, "energy": "medium", "project": "Research", "completed_at": at(17, offset=-1)}),
        ]
        for key, values in task_specs:
            _sync(db, Task, user.id, key, values)

        goal1 = _sync(db, Goal, user.id, "personal-product", {"title": "Запустить личный продукт", "description": "Проверить гипотезу и выпустить первую полезную версию", "horizon": "quarter", "target_date": today + timedelta(days=76), "progress": 42})
        goal2 = _sync(db, Goal, user.id, "run-10k", {"title": "Пробежать 10 км", "description": "Комфортно закончить городской забег", "horizon": "quarter", "target_date": today + timedelta(days=54), "progress": 65})
        _sync(db, Goal, user.id, "emergency-fund", {"title": "Собрать финансовую подушку", "description": "Накопить резерв на четыре месяца", "horizon": "year", "target_date": today + timedelta(days=180), "progress": 28})

        db.execute(delete(GoalStep).where(GoalStep.goal_id.in_([goal1.id, goal2.id])))
        db.add_all([
            GoalStep(goal_id=goal1.id, title="Описать аудиторию и ключевую проблему", order_index=0, is_completed=True, due_date=today - timedelta(days=14)),
            GoalStep(goal_id=goal1.id, title="Провести 8 проблемных интервью", order_index=1, is_completed=True, due_date=today - timedelta(days=3)),
            GoalStep(goal_id=goal1.id, title="Собрать интерактивный прототип", order_index=2, due_date=today + timedelta(days=12)),
            GoalStep(goal_id=goal1.id, title="Провести закрытый запуск", order_index=3, due_date=today + timedelta(days=36)),
            GoalStep(goal_id=goal2.id, title="Стабильно бегать 3 раза в неделю", order_index=0, is_completed=True),
            GoalStep(goal_id=goal2.id, title="Пробежать контрольные 8 км", order_index=1, due_date=today + timedelta(days=21)),
        ])

        habit_specs = [
            ("water", "Стакан воды утром", "💧", "#2D9CDB", 7),
            ("meditation", "10 минут медитации", "🧘", "#7857FF", 5),
            ("reading", "Чтение", "📖", "#F2C94C", 6),
            ("walk", "Прогулка", "🌿", "#00B894", 7),
        ]
        for index, (key, title, emoji, color, target) in enumerate(habit_specs):
            habit = _sync(db, Habit, user.id, key, {"title": title, "emoji": emoji, "color": color, "target_per_week": target, "cadence": "daily"})
            db.execute(delete(HabitCheckin).where(HabitCheckin.habit_id == habit.id))
            completed_offsets = range(0 if index in {0, 2} else 1, 8 - index)
            db.add_all([
                HabitCheckin(habit_id=habit.id, checkin_date=today - timedelta(days=offset))
                for offset in completed_offsets
            ])

        _sync(db, BalanceAssessment, user.id, "current-balance", {"assessment_date": today - timedelta(days=2), "health": 7, "career": 8, "finance": 6, "relationships": 7, "growth": 8, "recreation": 5, "environment": 8, "contribution": 6, "note": "Хочется больше времени на спокойный отдых."})
        _sync(db, Recommendation, user.id, "recovery-evening", {"kind": "balance", "title": "Освободите вечер для восстановления", "body": "Отдых сейчас заметно отстаёт от остальных сфер. Один вечер без рабочих задач поможет удержать темп.", "action": "Забронировать вечер"})
        db.commit()
        print(f"Development demo data synchronized for {settings.demo_email}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo()
