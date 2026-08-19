from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select

from backend.api.deps import CurrentUser, DbSession
from backend.models import (
    AIActionProposal,
    AIConversation,
    AIMessage,
    BalanceAssessment,
    ChatMessage,
    Event,
    Goal,
    GoalPlan,
    GoalPlanVersion,
    GoalStep,
    Habit,
    HabitCheckin,
    Recommendation,
    NotificationDelivery,
    Task,
)
from backend.schemas.account import AccountDeleteRequest
from backend.services.security import revoke_all_sessions, verify_password
from backend.services.time import utc_now

router = APIRouter(prefix="/account", tags=["Account & privacy"])


def _row(item, *, exclude: set[str] | None = None) -> dict:
    excluded = exclude or set()
    return {
        column.name: getattr(item, column.name)
        for column in item.__table__.columns
        if column.name not in excluded
    }


@router.get("/export")
def export_account(user: CurrentUser, db: DbSession):
    goals = db.scalars(select(Goal).where(Goal.user_id == user.id)).all()
    habits = db.scalars(select(Habit).where(Habit.user_id == user.id)).all()
    conversations = db.scalars(select(AIConversation).where(AIConversation.user_id == user.id)).all()
    plans = db.scalars(select(GoalPlan).where(GoalPlan.user_id == user.id)).all()
    payload = {
        "schema_version": "1",
        "exported_at": utc_now(),
        "profile": _row(
            user,
            exclude={"hashed_password", "sessions_revoked_at"},
        ),
        "settings": _row(user.settings) if user.settings else None,
        "events": [_row(item) for item in db.scalars(select(Event).where(Event.user_id == user.id)).all()],
        "tasks": [_row(item) for item in db.scalars(select(Task).where(Task.user_id == user.id)).all()],
        "goals": [_row(item) for item in goals],
        "goal_steps": [
            _row(item)
            for item in db.scalars(
                select(GoalStep).where(GoalStep.goal_id.in_([item.id for item in goals]))
            ).all()
        ] if goals else [],
        "habits": [_row(item) for item in habits],
        "habit_checkins": [
            _row(item)
            for item in db.scalars(
                select(HabitCheckin).where(HabitCheckin.habit_id.in_([item.id for item in habits]))
            ).all()
        ] if habits else [],
        "balance_assessments": [_row(item) for item in db.scalars(select(BalanceAssessment).where(BalanceAssessment.user_id == user.id)).all()],
        "recommendations": [_row(item) for item in db.scalars(select(Recommendation).where(Recommendation.user_id == user.id)).all()],
        "legacy_chat_messages": [_row(item) for item in db.scalars(select(ChatMessage).where(ChatMessage.user_id == user.id)).all()],
        "ai_conversations": [_row(item) for item in conversations],
        "ai_messages": [_row(item) for item in db.scalars(select(AIMessage).where(AIMessage.user_id == user.id)).all()],
        "goal_plans": [_row(item) for item in plans],
        "goal_plan_versions": [_row(item) for item in db.scalars(select(GoalPlanVersion).where(GoalPlanVersion.user_id == user.id)).all()],
        "ai_action_proposals": [_row(item) for item in db.scalars(select(AIActionProposal).where(AIActionProposal.user_id == user.id)).all()],
        "notification_deliveries": [
            _row(item, exclude={"last_error", "locked_by"})
            for item in db.scalars(
                select(NotificationDelivery).where(NotificationDelivery.user_id == user.id)
            ).all()
        ],
    }
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"Content-Disposition": 'attachment; filename="axel-one-export.json"'},
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(payload: AccountDeleteRequest, user: CurrentUser, db: DbSession):
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid password")
    revoke_all_sessions(db, user.id)
    db.delete(user)
    db.commit()
    return Response(status_code=204)
