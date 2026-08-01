from collections.abc import Iterator
from datetime import time

from fastapi import APIRouter, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from backend.ai import compose_chat_reply
from backend.api.deps import CurrentUser, DbSession
from backend.models import ChatMessage, Event, Goal, Habit, Task
from backend.schemas.chat import ChatMessageResponse, ChatRequest
from backend.services.analytics import day_bounds, energy_for_user, overload_for_user
from backend.services.time import in_timezone, today_for

router = APIRouter(prefix="/chat", tags=["AI chat"])


@router.get("/history", response_model=list[ChatMessageResponse])
def history(user: CurrentUser, db: DbSession, limit: int = 50):
    items = db.scalars(select(ChatMessage).where(ChatMessage.user_id == user.id).order_by(ChatMessage.created_at.desc()).limit(min(limit, 100))).all()
    return list(reversed(items))


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
def clear_history(user: CurrentUser, db: DbSession):
    items = db.scalars(select(ChatMessage).where(ChatMessage.user_id == user.id)).all()
    for item in items:
        db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/stream")
def chat_stream(payload: ChatRequest, user: CurrentUser, db: DbSession):
    db.add(ChatMessage(user_id=user.id, role="user", content=payload.message))
    open_tasks = len(db.scalars(select(Task).where(Task.user_id == user.id, Task.status.in_(["todo", "in_progress"]))).all())
    selected_date = payload.selected_date or today_for(user.timezone)
    start, end = day_bounds(selected_date, user.timezone)
    events = db.scalars(
        select(Event)
        .where(Event.user_id == user.id, Event.start_at < end, Event.end_at > start)
        .order_by(Event.start_at)
    ).all()
    overload = overload_for_user(db, user.id, selected_date, user.timezone)
    energy = energy_for_user(db, user.id, selected_date, user.timezone)
    active_goals = len(db.scalars(select(Goal).where(Goal.user_id == user.id, Goal.status == "active")).all())
    active_habits = len(db.scalars(select(Habit).where(Habit.user_id == user.id, Habit.archived.is_(False))).all())
    cursor = 8 * 60
    free_minutes = 0
    for event in events:
        local_start = in_timezone(event.start_at, user.timezone)
        local_end = in_timezone(event.end_at, user.timezone)
        event_start = max(cursor, local_start.hour * 60 + local_start.minute)
        free_minutes += max(0, event_start - cursor)
        cursor = max(cursor, local_end.hour * 60 + local_end.minute)
    free_minutes += max(0, 20 * 60 - cursor)
    reply = compose_chat_reply(payload.message, {
        "selected_date": selected_date.strftime("%d.%m.%Y"), "open_tasks": open_tasks,
        "events_today": len(events), "overload": overload["level"], "free_minutes": free_minutes,
        "goals": active_goals, "habits": active_habits, "energy": energy["score"], "energy_peak": energy["peak_start"],
    }, user.name.split()[0])
    db.add(ChatMessage(user_id=user.id, role="assistant", content=reply))
    db.commit()

    def words() -> Iterator[str]:
        parts = reply.split(" ")
        for index, word in enumerate(parts):
            yield word + (" " if index < len(parts) - 1 else "")

    return StreamingResponse(words(), media_type="text/plain; charset=utf-8", headers={"X-Accel-Buffering": "no"})
