import asyncio
import logging
from weakref import WeakValueDictionary

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from backend.ai import decompose_goal
from backend.ai.client import LLMError
from backend.ai.factory import get_llm_client
from backend.ai.goal_planner_service import GoalPlannerService, GoalPlanValidationError
from backend.ai.schemas import (
    GoalPlanApplyRequest,
    GoalPlanApplyResponse,
    GoalPlanRequest,
    GoalPlanResponse,
    GoalPlanUpdate,
)
from backend.api.deps import CurrentUser, DbSession
from backend.database import SessionLocal
from backend.models import Goal, GoalStep, User
from backend.schemas.goals import DecomposeRequest, GoalCreate, GoalResponse, GoalStepResponse, GoalStepUpdate, GoalUpdate
from backend.services.time import today_for
from backend.services.privacy import has_current_ai_consent, require_ai_context_consent
from backend.config import settings

router = APIRouter(prefix="/goals", tags=["Goals"])
logger = logging.getLogger(__name__)
_goal_generation_locks: WeakValueDictionary[tuple[int, int], asyncio.Lock] = WeakValueDictionary()


def _goal_generation_lock(user_id: int, goal_id: int) -> asyncio.Lock:
    return _goal_generation_locks.setdefault((user_id, goal_id), asyncio.Lock())


def owned_goal(db: DbSession, user_id: int, goal_id: int) -> Goal:
    goal = db.scalar(select(Goal).options(selectinload(Goal.steps)).where(Goal.id == goal_id, Goal.user_id == user_id))
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@router.get("", response_model=list[GoalResponse])
def list_goals(user: CurrentUser, db: DbSession):
    return db.scalars(select(Goal).options(selectinload(Goal.steps)).where(Goal.user_id == user.id).order_by(Goal.created_at.desc())).all()


async def _generate_plan_in_background(goal_id: int, user_id: int) -> None:
    db = SessionLocal()
    try:
        async with _goal_generation_lock(user_id, goal_id):
            goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
            user = db.scalar(select(User).where(User.id == user_id))
            if goal is None or user is None:
                return
            if settings.llm_provider.lower() == "gigachat" and not has_current_ai_consent(user):
                return
            planner = GoalPlannerService(get_llm_client())
            if planner.get(db, user_id, goal_id) is not None:
                return
            await planner.llm_client.status()
            await planner.generate(db, user, goal, reason="Автоматический план после создания цели")
    except Exception as exc:
        logger.warning("Automatic goal plan generation failed: %s", type(exc).__name__)
    finally:
        db.close()


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
def create_goal(payload: GoalCreate, background_tasks: BackgroundTasks, user: CurrentUser, db: DbSession):
    goal = Goal(user_id=user.id, **payload.model_dump())
    db.add(goal)
    db.commit()
    if settings.llm_provider.lower() != "gigachat" or has_current_ai_consent(user):
        background_tasks.add_task(_generate_plan_in_background, goal.id, user.id)
    return owned_goal(db, user.id, goal.id)


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(goal_id: int, payload: GoalUpdate, user: CurrentUser, db: DbSession):
    goal = owned_goal(db, user.id, goal_id)
    previous_target_date = goal.target_date
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, key, value)
    if "target_date" in payload.model_fields_set and goal.target_date != previous_target_date:
        plan = GoalPlannerService(get_llm_client()).get(db, user.id, goal.id)
        if plan is not None:
            plan.status = "needs_review"
            plan.diff_data = '{"added":[],"removed":[],"moved":[],"reason":"Дедлайн цели изменился — рекомендуется пересоставить план"}'
    db.commit()
    return owned_goal(db, user.id, goal_id)


@router.post("/{goal_id}/decompose", response_model=list[GoalStepResponse])
def ai_decompose(goal_id: int, payload: DecomposeRequest, user: CurrentUser, db: DbSession):
    goal = owned_goal(db, user.id, goal_id)
    db.execute(delete(GoalStep).where(GoalStep.goal_id == goal.id))
    steps = [
        GoalStep(goal_id=goal.id, **item)
        for item in decompose_goal(goal, payload.context, today_for(user.timezone))
    ]
    db.add_all(steps)
    db.commit()
    for step in steps:
        db.refresh(step)
    return steps


async def _generate_plan(
    goal_id: int, payload: GoalPlanRequest, user: CurrentUser, db: DbSession, *, regenerate: bool
) -> dict:
    require_ai_context_consent(user)
    async with _goal_generation_lock(user.id, goal_id):
        goal = owned_goal(db, user.id, goal_id)
        planner = GoalPlannerService(get_llm_client())
        if not regenerate:
            existing = planner.get(db, user.id, goal.id)
            if existing is not None:
                return planner.serialize(existing)
        try:
            await planner.llm_client.status()
            plan = await planner.generate(
                db,
                user,
                goal,
                extra_context=payload.context,
                reason=payload.reason or (
                    "План пересоставлен по запросу пользователя" if regenerate else "План создан AI"
                ),
            )
        except (LLMError, GoalPlanValidationError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return planner.serialize(plan)


@router.post("/{goal_id}/generate-plan", response_model=GoalPlanResponse)
async def generate_plan(goal_id: int, payload: GoalPlanRequest, user: CurrentUser, db: DbSession):
    return await _generate_plan(goal_id, payload, user, db, regenerate=False)


@router.post("/{goal_id}/regenerate-plan", response_model=GoalPlanResponse)
async def regenerate_plan(goal_id: int, payload: GoalPlanRequest, user: CurrentUser, db: DbSession):
    return await _generate_plan(goal_id, payload, user, db, regenerate=True)


@router.get("/{goal_id}/plan", response_model=GoalPlanResponse)
def get_plan(goal_id: int, user: CurrentUser, db: DbSession):
    owned_goal(db, user.id, goal_id)
    planner = GoalPlannerService(get_llm_client())
    plan = planner.get(db, user.id, goal_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="План цели ещё не составлен")
    return planner.serialize(plan)


@router.patch("/{goal_id}/plan", response_model=GoalPlanResponse)
def update_plan(goal_id: int, payload: GoalPlanUpdate, user: CurrentUser, db: DbSession):
    goal = owned_goal(db, user.id, goal_id)
    planner = GoalPlannerService(get_llm_client())
    try:
        plan = planner.update(db, user.id, goal, payload.plan, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return planner.serialize(plan)


@router.post("/{goal_id}/plan/apply", response_model=GoalPlanApplyResponse)
def apply_plan(goal_id: int, payload: GoalPlanApplyRequest, user: CurrentUser, db: DbSession):
    goal = owned_goal(db, user.id, goal_id)
    planner = GoalPlannerService(get_llm_client())
    try:
        created = planner.apply(
            db,
            user,
            goal,
            confirm=payload.confirm,
            components=payload.components,
            selected_indices=payload.selected_indices,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "applied", "created": created}


@router.post("/{goal_id}/plan/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_plan(goal_id: int, user: CurrentUser, db: DbSession):
    owned_goal(db, user.id, goal_id)
    planner = GoalPlannerService(get_llm_client())
    plan = planner.get(db, user.id, goal_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="План цели ещё не составлен")
    planner.cancel(db, plan)
    return Response(status_code=204)


@router.patch("/{goal_id}/steps/{step_id}", response_model=GoalStepResponse)
def update_step(goal_id: int, step_id: int, payload: GoalStepUpdate, user: CurrentUser, db: DbSession):
    goal = owned_goal(db, user.id, goal_id)
    step = next((item for item in goal.steps if item.id == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail="Goal step not found")
    step.is_completed = payload.is_completed
    completed = sum(1 for item in goal.steps if item.is_completed or item.id == step.id and payload.is_completed)
    goal.progress = round(completed / max(1, len(goal.steps)) * 100)
    if goal.progress == 100:
        goal.status = "completed"
    elif goal.status == "completed":
        goal.status = "active"
    if payload.is_completed:
        plan = GoalPlannerService(get_llm_client()).get(db, user.id, goal.id)
        if plan is not None and plan.status == "applied":
            plan.status = "needs_review"
            plan.diff_data = '{"added":[],"removed":[],"moved":[],"reason":"Этап достигнут — можно адаптировать следующие действия"}'
    db.commit()
    db.refresh(step)
    return step


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, user: CurrentUser, db: DbSession):
    db.delete(owned_goal(db, user.id, goal_id))
    db.commit()
    return Response(status_code=204)
