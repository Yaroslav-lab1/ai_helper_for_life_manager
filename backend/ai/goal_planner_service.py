from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.client import LLMClient, LLMResponseError
from backend.ai.context_service import UserContextService
from backend.ai.prompts import GOAL_PLAN_REPAIR_PROMPT, GOAL_PLANNER_SYSTEM_PROMPT
from backend.ai.schemas import GoalPlanPayload, WeeklyPlanItem, goal_plan_response_schema
from backend.models import Event, Goal, GoalPlan, GoalPlanVersion, GoalStep, Habit, Task, User, utcnow
from backend.services.time import local_datetime_utc, today_for


logger = logging.getLogger(__name__)


class GoalPlanValidationError(LLMResponseError):
    pass


class GoalPlannerService:
    def __init__(self, llm_client: LLMClient, context_service: UserContextService | None = None):
        self.llm_client = llm_client
        self.context_service = context_service or UserContextService()

    async def generate(
        self,
        db: Session,
        user: User,
        goal: Goal,
        *,
        extra_context: str | None = None,
        reason: str | None = None,
    ) -> GoalPlan:
        context = self.context_service.build_for_goal(db, user, goal, extra_context)
        schema = goal_plan_response_schema(
            preserve_constraints=getattr(self.llm_client, "provider", "") == "gigachat"
        )
        messages = [
            {"role": "system", "content": GOAL_PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
        raw = await self.llm_client.chat(messages, response_schema=schema, temperature=0.2)
        if not isinstance(raw, str):
            raise GoalPlanValidationError("AI не смог составить корректный план. Повторите попытку")
        try:
            payload = self._validate(raw, goal)
        except (ValueError, ValidationError) as first_error:
            repair_errors = self._safe_errors(first_error)
            logger.warning("Goal plan validation failed before repair: %s", repair_errors)
            repaired = await self.llm_client.chat(
                [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": GOAL_PLAN_REPAIR_PROMPT.format(errors=repair_errors)},
                ],
                response_schema=schema,
                temperature=0,
            )
            if not isinstance(repaired, str):
                raise GoalPlanValidationError("AI не смог составить корректный план. Повторите попытку")
            try:
                payload = self._validate(repaired, goal)
            except (ValueError, ValidationError) as exc:
                logger.warning("Goal plan validation failed after repair: %s", self._safe_errors(exc))
                raise GoalPlanValidationError("AI не смог составить корректный план. Повторите попытку") from exc
        return self.save_version(db, user.id, goal.id, payload, reason or "План создан AI")

    def update(self, db: Session, user_id: int, goal: Goal, payload: GoalPlanPayload, reason: str) -> GoalPlan:
        self._validate_goal_constraints(payload, goal)
        return self.save_version(db, user_id, goal.id, payload, reason)

    @staticmethod
    def get(db: Session, user_id: int, goal_id: int) -> GoalPlan | None:
        return db.scalar(select(GoalPlan).where(GoalPlan.goal_id == goal_id, GoalPlan.user_id == user_id))

    def save_version(
        self, db: Session, user_id: int, goal_id: int, payload: GoalPlanPayload, reason: str
    ) -> GoalPlan:
        current = self.get(db, user_id, goal_id)
        new_data = payload.model_dump(mode="json")
        diff = None
        if current is None:
            current = GoalPlan(
                goal_id=goal_id,
                user_id=user_id,
                status="draft",
                version=1,
                plan_data=json.dumps(new_data, ensure_ascii=False),
            )
            db.add(current)
            db.flush()
        else:
            old_data = json.loads(current.plan_data)
            diff = self.diff(old_data, new_data, reason)
            current.version += 1
            current.status = "draft"
            current.plan_data = json.dumps(new_data, ensure_ascii=False)
            current.diff_data = json.dumps(diff, ensure_ascii=False)
            current.updated_at = utcnow()
        db.add(GoalPlanVersion(
            plan_id=current.id,
            user_id=user_id,
            version=current.version,
            plan_data=current.plan_data,
            diff_data=current.diff_data,
            reason=reason,
        ))
        db.commit()
        db.refresh(current)
        return current

    def apply(
        self,
        db: Session,
        user: User,
        goal: Goal,
        *,
        confirm: bool,
        components: list[str],
        selected_indices: dict[str, list[int]] | None = None,
    ) -> dict[str, int]:
        if not confirm:
            raise PermissionError("Подтвердите применение плана после просмотра изменений")
        stored = self.get(db, user.id, goal.id)
        if stored is None:
            raise LookupError("План цели не найден")
        if stored.status == "cancelled":
            raise ValueError("План отменён. Сначала составьте новый план")
        plan = GoalPlanPayload.model_validate_json(stored.plan_data)
        self._validate_goal_constraints(plan, goal)
        selected_indices = selected_indices or {}
        created = {"milestones": 0, "tasks": 0, "habits": 0, "schedule_suggestions": 0}

        if "milestones" in components:
            existing = {item.title for item in goal.steps}
            for index, item in self._selected(plan.milestones, selected_indices.get("milestones")):
                if item.title in existing:
                    continue
                db.add(GoalStep(goal_id=goal.id, title=item.title, order_index=len(existing) + index, due_date=item.deadline))
                existing.add(item.title)
                created["milestones"] += 1
        if "tasks" in components:
            existing_tasks = set(db.scalars(select(Task.title).where(Task.user_id == user.id)).all())
            for _, item in self._selected(plan.tasks, selected_indices.get("tasks")):
                if item.title in existing_tasks:
                    continue
                db.add(Task(
                    user_id=user.id,
                    title=item.title,
                    notes=item.description,
                    due_at=local_datetime_utc(item.deadline, time(18), user.timezone) if item.deadline else None,
                    priority=item.priority,
                    estimate_minutes=item.estimated_minutes,
                    project=goal.title[:100],
                ))
                existing_tasks.add(item.title)
                created["tasks"] += 1
        if "habits" in components:
            existing_habits = set(db.scalars(select(Habit.title).where(Habit.user_id == user.id)).all())
            for _, item in self._selected(plan.habits, selected_indices.get("habits")):
                if item.title in existing_habits:
                    continue
                target = 7 if item.frequency == "daily" else 5 if item.frequency == "weekdays" else 1
                db.add(Habit(
                    user_id=user.id,
                    title=item.title,
                    emoji="✨",
                    cadence=item.frequency,
                    target_per_week=target,
                    color="#6C5CE7",
                ))
                existing_habits.add(item.title)
                created["habits"] += 1
        if "schedule_suggestions" in components:
            for _, item in self._selected(plan.schedule_suggestions, selected_indices.get("schedule_suggestions")):
                start_at = self._next_datetime(item.preferred_days[0], item.preferred_time, user.timezone)
                if goal.target_date and today_for(user.timezone, now=start_at) > goal.target_date:
                    continue
                duplicate = db.scalar(select(Event).where(
                    Event.user_id == user.id, Event.title == item.title, Event.start_at == start_at
                ))
                if duplicate:
                    continue
                db.add(Event(
                    user_id=user.id,
                    title=item.title,
                    description=f"Рекомендованный блок по цели «{goal.title}»",
                    start_at=start_at,
                    end_at=start_at + timedelta(minutes=item.duration_minutes),
                    category="focus",
                    color="#6C5CE7",
                ))
                created["schedule_suggestions"] += 1
        stored.status = "applied"
        stored.updated_at = utcnow()
        db.commit()
        return created

    @staticmethod
    def cancel(db: Session, plan: GoalPlan) -> None:
        plan.status = "cancelled"
        plan.updated_at = utcnow()
        db.commit()

    @staticmethod
    def serialize(plan: GoalPlan) -> dict[str, Any]:
        return {
            "id": plan.id,
            "goal_id": plan.goal_id,
            "status": plan.status,
            "version": plan.version,
            "plan": json.loads(plan.plan_data),
            "diff": json.loads(plan.diff_data) if plan.diff_data else None,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        }

    @staticmethod
    def diff(old: dict[str, Any], new: dict[str, Any], reason: str) -> dict[str, Any]:
        added: list[str] = []
        removed: list[str] = []
        moved: list[str] = []
        for section in ("milestones", "tasks", "habits", "schedule_suggestions"):
            old_items = {str(item.get("title")): item for item in old.get(section, []) if isinstance(item, dict)}
            new_items = {str(item.get("title")): item for item in new.get(section, []) if isinstance(item, dict)}
            added.extend(f"{section}: {title}" for title in new_items.keys() - old_items.keys())
            removed.extend(f"{section}: {title}" for title in old_items.keys() - new_items.keys())
            moved.extend(
                f"{section}: {title}"
                for title in old_items.keys() & new_items.keys()
                if old_items[title] != new_items[title]
            )
        return {"added": added, "removed": removed, "moved": moved, "reason": reason}

    @staticmethod
    def _validate(raw: str, goal: Goal) -> GoalPlanPayload:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("Ответ плана должен быть JSON-объектом")
        weekly_days = [
            item.get("day_of_week")
            for item in parsed.get("weekly_plan", [])
            if isinstance(item, dict) and item.get("day_of_week") in {
                "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
            }
        ]
        for section in ("milestones", "tasks"):
            for item in parsed.get(section, []):
                if isinstance(item, dict) and isinstance(item.get("deadline"), str):
                    value = item["deadline"]
                    if re.match(r"^\d{4}-\d{2}-\d{2}T", value):
                        item["deadline"] = value[:10]
        for item in parsed.get("schedule_suggestions", []):
            if not isinstance(item, dict):
                continue
            if not item.get("preferred_days"):
                item["preferred_days"] = list(dict.fromkeys(weekly_days))[:3] or ["monday"]
            if isinstance(item.get("preferred_time"), str):
                value = item["preferred_time"]
                if re.match(r"^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$", value):
                    item["preferred_time"] = value[:5]
        payload = GoalPlanPayload.model_validate(parsed)
        payload = GoalPlannerService._complete_weekly_plan(payload)
        GoalPlannerService._validate_goal_constraints(payload, goal)
        return payload

    @staticmethod
    def _complete_weekly_plan(payload: GoalPlanPayload) -> GoalPlanPayload:
        """Derive a weekly view when Ollama returns only schedule suggestions."""
        if payload.weekly_plan or not payload.schedule_suggestions:
            return payload

        weekly_plan: list[WeeklyPlanItem] = []
        seen: set[tuple[str, str]] = set()
        for suggestion in payload.schedule_suggestions:
            for day in suggestion.preferred_days:
                key = (day, suggestion.title)
                if key in seen:
                    continue
                weekly_plan.append(WeeklyPlanItem(
                    day_of_week=day,
                    duration_minutes=suggestion.duration_minutes,
                    action=suggestion.title,
                ))
                seen.add(key)
                if len(weekly_plan) == 21:
                    return payload.model_copy(update={"weekly_plan": weekly_plan})

        return payload.model_copy(update={"weekly_plan": weekly_plan})

    @staticmethod
    def _validate_goal_constraints(payload: GoalPlanPayload, goal: Goal) -> None:
        required_sections = {
            "tasks": payload.tasks,
            "habits": payload.habits,
            "weekly_plan": payload.weekly_plan,
            "schedule_suggestions": payload.schedule_suggestions,
        }
        empty = [name for name, items in required_sections.items() if not items]
        if empty:
            raise ValueError("План должен содержать непустые разделы: " + ", ".join(empty))
        if goal.target_date:
            late = [item.title for item in payload.milestones if item.deadline > goal.target_date]
            late.extend(item.title for item in payload.tasks if item.deadline and item.deadline > goal.target_date)
            if late:
                raise ValueError("Сроки пунктов выходят за дедлайн цели")

    @staticmethod
    def _safe_errors(error: Exception) -> str:
        if isinstance(error, ValidationError):
            return json.dumps(error.errors(include_input=False), ensure_ascii=False)[:3000]
        return str(error)[:1000]

    @staticmethod
    def _selected(items: list[Any], indices: list[int] | None) -> list[tuple[int, Any]]:
        allowed = set(indices) if indices is not None else None
        return [(index, item) for index, item in enumerate(items) if allowed is None or index in allowed]

    @staticmethod
    def _next_datetime(day_name: str, preferred_time: str, timezone_name: str) -> datetime:
        weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
        today = today_for(timezone_name)
        offset = (weekdays[day_name] - today.weekday()) % 7
        if offset == 0:
            offset = 7
        return local_datetime_utc(today + timedelta(days=offset), time.fromisoformat(preferred_time), timezone_name)
