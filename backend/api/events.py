from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, DbSession
from backend.models import Event
from backend.schemas.events import EventCreate, EventResponse, EventUpdate
from backend.services.recurrence import events_for_range
from backend.services.time import to_utc

router = APIRouter(prefix="/events", tags=["Calendar"])


def owned_event(db: DbSession, user_id: int, event_id: int) -> Event:
    event = db.scalar(select(Event).where(Event.id == event_id, Event.user_id == user_id))
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("", response_model=list[EventResponse])
def list_events(user: CurrentUser, db: DbSession, start: datetime | None = None, end: datetime | None = None):
    if start is not None and end is not None:
        range_start = to_utc(start, user.timezone)
        range_end = to_utc(end, user.timezone)
        if range_end <= range_start:
            raise HTTPException(status_code=422, detail="end must be later than start")
        if range_end - range_start > timedelta(days=366):
            raise HTTPException(status_code=422, detail="Calendar range cannot exceed 366 days")
        return events_for_range(db, user.id, range_start, range_end, user.timezone)
    query = select(Event).where(Event.user_id == user.id)
    if start:
        query = query.where(Event.end_at >= to_utc(start, user.timezone))
    if end:
        query = query.where(Event.start_at <= to_utc(end, user.timezone))
    return db.scalars(query.order_by(Event.start_at)).all()


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: int, user: CurrentUser, db: DbSession):
    """Return the stored series. Occurrence edits are intentionally series-wide."""
    return owned_event(db, user.id, event_id)


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, user: CurrentUser, db: DbSession):
    values = payload.model_dump()
    values["start_at"] = to_utc(values["start_at"], user.timezone)
    values["end_at"] = to_utc(values["end_at"], user.timezone)
    event = Event(user_id=user.id, **values)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.patch("/{event_id}", response_model=EventResponse)
def update_event(event_id: int, payload: EventUpdate, user: CurrentUser, db: DbSession):
    event = owned_event(db, user.id, event_id)
    values = payload.model_dump(exclude_unset=True)
    for key in ("start_at", "end_at"):
        if key in values and values[key] is not None:
            values[key] = to_utc(values[key], user.timezone)
    start = values.get("start_at", event.start_at)
    end = values.get("end_at", event.end_at)
    if end <= start:
        raise HTTPException(status_code=422, detail="end_at must be later than start_at")
    for key, value in values.items():
        setattr(event, key, value)
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: int, user: CurrentUser, db: DbSession):
    db.delete(owned_event(db, user.id, event_id))
    db.commit()
    return Response(status_code=204)
