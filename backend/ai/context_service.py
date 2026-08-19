from __future__ import annotations

import json
import re
from datetime import date, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.config import get_settings
from backend.models import BalanceAssessment, Goal, Habit, Task, User
from backend.services.analytics import analytics_for_user, day_bounds, energy_for_user, overload_for_user
from backend.services.habits import streak_stats
from backend.services.recurrence import EventOccurrence, events_for_range
from backend.services.time import in_timezone, local_datetime_utc, today_for


class UserContextService:
    """Builds a bounded context containing only current-user life-management data."""

    def __init__(self, max_chars: int | None = None):
        self.max_chars = max_chars or get_settings().ai_max_context_chars

    def build(self, db: Session, user: User, question: str, selected_date: date | None = None) -> dict[str, Any]:
        selected_date = selected_date or today_for(user.timezone)
        start, end = day_bounds(selected_date, user.timezone)
        terms = {item for item in re.findall(r"[\wа-яё]+", question.lower()) if len(item) >= 4}

        events = events_for_range(db, user.id, start, end, user.timezone, limit=20)
        tasks = db.scalars(
            select(Task)
            .where(Task.user_id == user.id, Task.status.in_(["todo", "in_progress"]))
            .order_by(Task.due_at, Task.priority)
            .limit(30)
        ).all()
        goals = db.scalars(
            select(Goal).where(Goal.user_id == user.id, Goal.status == "active").order_by(Goal.target_date).limit(12)
        ).all()
        habits = db.scalars(
            select(Habit)
            .options(selectinload(Habit.checkins))
            .where(Habit.user_id == user.id, Habit.archived.is_(False))
            .limit(12)
        ).all()
        latest_balance = db.scalar(
            select(BalanceAssessment)
            .where(BalanceAssessment.user_id == user.id)
            .order_by(BalanceAssessment.assessment_date.desc())
        )

        tasks = self._relevant(tasks, terms, lambda item: f"{item.title} {item.notes or ''}", 16)
        goals = self._relevant(goals, terms, lambda item: f"{item.title} {item.description or ''}", 8)
        settings = user.settings
        work_start = self._parse_time(settings.workday_start if settings else "09:00")
        work_end = self._parse_time(settings.workday_end if settings else "20:00")
        free_intervals = self._free_intervals(events, selected_date, work_start, work_end, user.timezone)
        overload = overload_for_user(db, user.id, selected_date, user.timezone)
        energy = energy_for_user(db, user.id, selected_date, user.timezone)
        analytics = analytics_for_user(db, user.id, 14, user.timezone)

        context: dict[str, Any] = {
            "user": {"name": user.name, "timezone": user.timezone},
            "selected_date": selected_date.isoformat(),
            "events": [{
                "title": item.title,
                "start": in_timezone(item.start_at, user.timezone).isoformat(),
                "end": in_timezone(item.end_at, user.timezone).isoformat(),
                "category": item.category,
            } for item in events],
            "tasks": [{
                "title": item.title,
                "due_at": in_timezone(item.due_at, user.timezone).isoformat() if item.due_at else None,
                "priority": item.priority,
                "status": item.status,
                "estimate_minutes": item.estimate_minutes,
            } for item in tasks],
            "active_goals": [{
                "title": item.title,
                "description": item.description,
                "deadline": item.target_date.isoformat() if item.target_date else None,
                "progress_percent": item.progress,
            } for item in goals],
            "habits": [{
                "title": item.title,
                "cadence": item.cadence,
                "target_per_week": item.target_per_week,
                **streak_stats(item, selected_date),
            } for item in habits],
            "free_intervals": free_intervals,
            "life_balance": self._balance(latest_balance),
            "recent_productivity": {
                "tasks_completed": analytics["tasks_completed"],
                "task_completion_rate": analytics["task_completion_rate"],
                "habit_completion_rate": analytics["habit_completion_rate"],
            },
            "energy_forecast": {
                "source": "calculated_by_axel_one_not_user_reported",
                "score": energy["score"],
                "status": energy["status"],
                "peak": energy["peak_start"],
            },
            "overload": {
                "level": overload["level"],
                "score": overload["score"],
                "signals": overload["signals"],
                "suggestion": overload["suggestion"],
            },
        }
        return self._bounded(context)

    def build_for_goal(self, db: Session, user: User, goal: Goal, extra_context: str | None = None) -> dict[str, Any]:
        question = f"{goal.title} {goal.description or ''} {extra_context or ''}"
        context = self.build(db, user, question, today_for(user.timezone))
        context["goal"] = {
            "title": goal.title,
            "description": goal.description,
            "start_date": in_timezone(goal.created_at, user.timezone).date().isoformat(),
            "deadline": goal.target_date.isoformat() if goal.target_date else None,
            "horizon": goal.horizon,
            "current_progress_percent": goal.progress,
            "additional_constraints": extra_context,
        }
        return self._bounded(context)

    @staticmethod
    def _relevant(items: list[Any], terms: set[str], text: Any, limit: int) -> list[Any]:
        if not terms:
            return items[:limit]
        return sorted(items, key=lambda item: not any(term in text(item).lower() for term in terms))[:limit]

    @staticmethod
    def _parse_time(value: str) -> time:
        try:
            return time.fromisoformat(value)
        except ValueError:
            return time(9)

    @staticmethod
    def _free_intervals(
        events: list[EventOccurrence], day: date, start_at: time, end_at: time, timezone_name: str
    ) -> list[dict[str, Any]]:
        work_start = local_datetime_utc(day, start_at, timezone_name)
        work_end = local_datetime_utc(day, end_at, timezone_name)
        if work_end <= work_start:
            return []

        busy: list[tuple[Any, Any]] = []
        for event in events:
            clipped_start = max(work_start, event.start_at)
            clipped_end = min(work_end, event.end_at)
            if clipped_start < clipped_end:
                busy.append((clipped_start, clipped_end))
        busy.sort(key=lambda interval: interval[0])

        merged: list[tuple[Any, Any]] = []
        for interval_start, interval_end in busy:
            if merged and interval_start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], interval_end))
            else:
                merged.append((interval_start, interval_end))

        cursor = work_start
        result: list[dict[str, Any]] = []
        for interval_start, interval_end in merged:
            if interval_start > cursor:
                result.append({
                    "start": in_timezone(cursor, timezone_name).isoformat(),
                    "end": in_timezone(interval_start, timezone_name).isoformat(),
                    "duration_minutes": int((interval_start - cursor).total_seconds() / 60),
                })
            cursor = max(cursor, interval_end)
        if cursor < work_end:
            result.append({
                "start": in_timezone(cursor, timezone_name).isoformat(),
                "end": in_timezone(work_end, timezone_name).isoformat(),
                "duration_minutes": int((work_end - cursor).total_seconds() / 60),
            })
        return result[:10]

    @staticmethod
    def _balance(item: BalanceAssessment | None) -> dict[str, Any] | None:
        if item is None:
            return None
        values = {
            "health": item.health,
            "career": item.career,
            "finance": item.finance,
            "relationships": item.relationships,
            "growth": item.growth,
            "recreation": item.recreation,
            "environment": item.environment,
            "contribution": item.contribution,
        }
        return {"scores": values, "average": round(sum(values.values()) / len(values), 1), "date": item.assessment_date.isoformat()}

    def _bounded(self, context: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(context, ensure_ascii=False, default=str)) <= self.max_chars:
            return context
        for key in ("tasks", "events", "active_goals", "habits", "free_intervals"):
            value = context.get(key)
            if isinstance(value, list):
                context[key] = value[: max(2, len(value) // 2)]
            if len(json.dumps(context, ensure_ascii=False, default=str)) <= self.max_chars:
                break
        return context
