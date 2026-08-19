from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import ceil

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.models import Event
from backend.services.time import in_timezone, local_datetime_utc


WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
MAX_OCCURRENCES = 5000


@dataclass(frozen=True)
class RecurrenceRule:
    frequency: str
    weekdays: frozenset[int]


@dataclass(frozen=True)
class EventOccurrence:
    id: int
    series_id: int
    occurrence_id: str
    is_occurrence: bool
    user_id: int
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime
    category: str
    color: str
    location: str | None
    recurrence_rule: str | None
    reminder_minutes: int | None
    created_at: datetime


def parse_recurrence_rule(value: str | None) -> RecurrenceRule | None:
    if value is None or not value.strip():
        return None
    parts: dict[str, str] = {}
    for item in value.strip().upper().split(";"):
        if "=" not in item:
            raise ValueError("Invalid recurrence rule")
        key, raw = item.split("=", 1)
        if not key or not raw or key in parts:
            raise ValueError("Invalid recurrence rule")
        parts[key] = raw
    unsupported = set(parts) - {"FREQ", "BYDAY"}
    if unsupported:
        raise ValueError("Unsupported recurrence rule option")
    frequency = parts.get("FREQ")
    if frequency not in {"DAILY", "WEEKLY"}:
        raise ValueError("Only FREQ=DAILY and FREQ=WEEKLY are supported")
    raw_days = parts.get("BYDAY", "")
    days: set[int] = set()
    if raw_days:
        for raw_day in raw_days.split(","):
            if raw_day not in WEEKDAYS:
                raise ValueError("Invalid BYDAY value")
            days.add(WEEKDAYS[raw_day])
    if frequency == "DAILY" and days:
        raise ValueError("BYDAY is supported only with FREQ=WEEKLY")
    return RecurrenceRule(frequency=frequency, weekdays=frozenset(days))


def normalize_recurrence_rule(value: str | None) -> str | None:
    rule = parse_recurrence_rule(value)
    if rule is None:
        return None
    result = f"FREQ={rule.frequency}"
    if rule.weekdays:
        ordered = ",".join(key for key, index in WEEKDAYS.items() if index in rule.weekdays)
        result += f";BYDAY={ordered}"
    return result


def occurrence_identifier(event_id: int, start_at: datetime) -> str:
    return f"event:{event_id}:{start_at.isoformat()}"


def _occurrence(event: Event, start_at: datetime, end_at: datetime, *, repeated: bool) -> EventOccurrence:
    return EventOccurrence(
        id=event.id,
        series_id=event.id,
        occurrence_id=occurrence_identifier(event.id, start_at),
        is_occurrence=repeated,
        user_id=event.user_id,
        title=event.title,
        description=event.description,
        start_at=start_at,
        end_at=end_at,
        category=event.category,
        color=event.color,
        location=event.location,
        recurrence_rule=event.recurrence_rule,
        reminder_minutes=event.reminder_minutes,
        created_at=event.created_at,
    )


def expand_event(
    event: Event,
    range_start: datetime,
    range_end: datetime,
    timezone_name: str,
    *,
    limit: int = MAX_OCCURRENCES,
) -> list[EventOccurrence]:
    if range_end <= range_start:
        return []
    rule = parse_recurrence_rule(event.recurrence_rule)
    if rule is None:
        if event.start_at < range_end and event.end_at > range_start:
            return [_occurrence(event, event.start_at, event.end_at, repeated=False)]
        return []

    anchor_local = in_timezone(event.start_at, timezone_name)
    duration = event.end_at - event.start_at
    overlap_days = max(1, ceil(max(0, duration.total_seconds()) / 86400))
    first_date = in_timezone(range_start, timezone_name).date() - timedelta(days=overlap_days)
    last_date = in_timezone(range_end, timezone_name).date()
    first_date = max(first_date, anchor_local.date())
    preferred_weekdays = rule.weekdays or frozenset({anchor_local.weekday()})
    local_start_time = time(
        anchor_local.hour,
        anchor_local.minute,
        anchor_local.second,
        anchor_local.microsecond,
    )

    occurrences: list[EventOccurrence] = []
    current = first_date
    while current <= last_date and len(occurrences) < limit:
        matches = rule.frequency == "DAILY" or current.weekday() in preferred_weekdays
        if matches:
            start_at = local_datetime_utc(current, local_start_time, timezone_name)
            end_at = start_at + duration
            if start_at >= event.start_at and start_at < range_end and end_at > range_start:
                occurrences.append(_occurrence(event, start_at, end_at, repeated=True))
        current += timedelta(days=1)
    return occurrences


def occurrences_for_events(
    events: list[Event],
    range_start: datetime,
    range_end: datetime,
    timezone_name: str,
    *,
    limit: int = MAX_OCCURRENCES,
) -> list[EventOccurrence]:
    result: list[EventOccurrence] = []
    for event in events:
        remaining = limit - len(result)
        if remaining <= 0:
            break
        result.extend(expand_event(event, range_start, range_end, timezone_name, limit=remaining))
    return sorted(result, key=lambda item: (item.start_at, item.end_at, item.series_id))


def events_for_range(
    db: Session,
    user_id: int,
    range_start: datetime,
    range_end: datetime,
    timezone_name: str,
    *,
    limit: int = MAX_OCCURRENCES,
) -> list[EventOccurrence]:
    events = db.scalars(
        select(Event).where(
            Event.user_id == user_id,
            or_(
                Event.recurrence_rule.is_not(None),
                (Event.start_at < range_end) & (Event.end_at > range_start),
            ),
        )
    ).all()
    return occurrences_for_events(list(events), range_start, range_end, timezone_name, limit=limit)
