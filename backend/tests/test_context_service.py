from datetime import date, time
from types import SimpleNamespace

from backend.ai.context_service import UserContextService
from backend.services.time import local_datetime_utc


DAY = date(2026, 8, 19)
ZONE = "Europe/Moscow"


def event(start_hour: int, end_hour: int, start_minute: int = 0, end_minute: int = 0):
    return SimpleNamespace(
        start_at=local_datetime_utc(DAY, time(start_hour, start_minute), ZONE),
        end_at=local_datetime_utc(DAY, time(end_hour, end_minute), ZONE),
    )


def free(events, start=time(9), end=time(18)):
    return UserContextService._free_intervals(events, DAY, start, end, ZONE)


def spans(intervals):
    return [(item["start"][11:16], item["end"][11:16]) for item in intervals]


def test_free_intervals_empty_calendar_and_invalid_workday():
    assert spans(free([])) == [("09:00", "18:00")]
    assert free([], time(18), time(9)) == []
    assert free([], time(9), time(9)) == []


def test_free_intervals_ignore_events_outside_workday():
    assert spans(free([event(7, 8), event(20, 21)])) == [("09:00", "18:00")]


def test_free_intervals_clip_partial_boundary_events():
    assert spans(free([event(8, 10), event(17, 20)])) == [("10:00", "17:00")]


def test_free_intervals_merge_overlapping_and_nested_events():
    intervals = free([event(10, 13), event(11, 12), event(12, 15), event(16, 17)])
    assert spans(intervals) == [("09:00", "10:00"), ("15:00", "16:00"), ("17:00", "18:00")]
    assert all(item["duration_minutes"] > 0 for item in intervals)
