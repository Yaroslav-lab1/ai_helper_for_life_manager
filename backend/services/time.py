from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Europe/Moscow"


def timezone_for(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unknown IANA timezone") from exc


def validate_timezone(name: str) -> str:
    timezone_for(name)
    return name


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime, timezone_name: str | None = None) -> datetime:
    """Normalize an instant to UTC; legacy/HTML naive values are user-local."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone_for(timezone_name))
    return value.astimezone(UTC)


def in_timezone(value: datetime, timezone_name: str | None) -> datetime:
    return to_utc(value).astimezone(timezone_for(timezone_name))


def now_for(timezone_name: str | None, *, now: datetime | None = None) -> datetime:
    return to_utc(now or utc_now()).astimezone(timezone_for(timezone_name))


def today_for(timezone_name: str | None, *, now: datetime | None = None) -> date:
    return now_for(timezone_name, now=now).date()


def day_bounds_utc(day: date, timezone_name: str | None) -> tuple[datetime, datetime]:
    """Return an inclusive start and exclusive end, preserving DST day length."""
    zone = timezone_for(timezone_name)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def local_datetime_utc(day: date, local_time: time, timezone_name: str | None) -> datetime:
    return datetime.combine(day, local_time, tzinfo=timezone_for(timezone_name)).astimezone(UTC)
