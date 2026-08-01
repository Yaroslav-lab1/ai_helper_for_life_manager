from datetime import date

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from backend.api.deps import CurrentUser, DbSession
from backend.models import Habit, HabitCheckin
from backend.schemas.habits import HabitCheckinCreate, HabitCheckinResponse, HabitCreate, HabitResponse, HabitUpdate
from backend.services.habits import streak_stats
from backend.services.time import today_for

router = APIRouter(prefix="/habits", tags=["Habits"])


def owned_habit(db: DbSession, user_id: int, habit_id: int) -> Habit:
    habit = db.scalar(select(Habit).options(selectinload(Habit.checkins)).where(Habit.id == habit_id, Habit.user_id == user_id))
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    return habit


def serialize_habit(habit: Habit, today: date) -> dict:
    return {
        "id": habit.id, "user_id": habit.user_id, "title": habit.title, "emoji": habit.emoji,
        "cadence": habit.cadence, "target_per_week": habit.target_per_week, "color": habit.color,
        "archived": habit.archived, "created_at": habit.created_at, "checkins": habit.checkins,
        **streak_stats(habit, today),
    }


@router.get("", response_model=list[HabitResponse])
def list_habits(user: CurrentUser, db: DbSession, include_archived: bool = False):
    query = select(Habit).options(selectinload(Habit.checkins)).where(Habit.user_id == user.id)
    if not include_archived:
        query = query.where(Habit.archived.is_(False))
    today = today_for(user.timezone)
    return [serialize_habit(habit, today) for habit in db.scalars(query.order_by(Habit.created_at)).all()]


@router.post("", response_model=HabitResponse, status_code=status.HTTP_201_CREATED)
def create_habit(payload: HabitCreate, user: CurrentUser, db: DbSession):
    habit = Habit(user_id=user.id, **payload.model_dump())
    db.add(habit)
    db.commit()
    return serialize_habit(owned_habit(db, user.id, habit.id), today_for(user.timezone))


@router.patch("/{habit_id}", response_model=HabitResponse)
def update_habit(habit_id: int, payload: HabitUpdate, user: CurrentUser, db: DbSession):
    habit = owned_habit(db, user.id, habit_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(habit, key, value)
    db.commit()
    return serialize_habit(owned_habit(db, user.id, habit_id), today_for(user.timezone))


@router.post("/{habit_id}/checkins", response_model=HabitCheckinResponse, status_code=status.HTTP_201_CREATED)
def add_checkin(habit_id: int, payload: HabitCheckinCreate, user: CurrentUser, db: DbSession):
    habit = owned_habit(db, user.id, habit_id)
    values = payload.model_dump()
    values["checkin_date"] = values["checkin_date"] or today_for(user.timezone)
    checkin = HabitCheckin(habit_id=habit.id, **values)
    db.add(checkin)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Habit is already completed for this date")
    db.refresh(checkin)
    return checkin


@router.delete("/{habit_id}/checkins/{checkin_date}", status_code=status.HTTP_204_NO_CONTENT)
def remove_checkin(habit_id: int, checkin_date: date, user: CurrentUser, db: DbSession):
    habit = owned_habit(db, user.id, habit_id)
    checkin = db.scalar(select(HabitCheckin).where(HabitCheckin.habit_id == habit.id, HabitCheckin.checkin_date == checkin_date))
    if not checkin:
        raise HTTPException(status_code=404, detail="Habit check-in not found")
    db.delete(checkin)
    db.commit()
    return Response(status_code=204)


@router.delete("/{habit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_habit(habit_id: int, user: CurrentUser, db: DbSession):
    db.delete(owned_habit(db, user.id, habit_id))
    db.commit()
    return Response(status_code=204)
