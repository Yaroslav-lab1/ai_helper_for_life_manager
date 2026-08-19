from datetime import UTC, date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.database import SessionLocal
from backend.models import Event, User
from backend.ai.context_service import UserContextService
from backend.services.analytics import analytics_for_user, dashboard_for_user, overload_for_user


def test_weekly_recurrence_is_expanded_without_materializing_rows(client: TestClient, auth: dict[str, str]):
    created = client.post("/api/v1/events", headers=auth, json={
        "title": "Регулярный фокус",
        "start_at": "2026-08-17T09:00:00",
        "end_at": "2026-08-17T10:00:00",
        "category": "focus",
        "color": "#6C5CE7",
        "recurrence_rule": "FREQ=WEEKLY;BYDAY=MO,WE",
    })
    assert created.status_code == 201

    params = {"start": "2026-08-17T00:00:00", "end": "2026-08-25T00:00:00"}
    first = client.get("/api/v1/events", headers=auth, params=params)
    second = client.get("/api/v1/events", headers=auth, params=params)
    assert first.status_code == 200
    assert [item["start_at"] for item in first.json()] == [
        "2026-08-17T06:00:00Z",
        "2026-08-19T06:00:00Z",
        "2026-08-24T06:00:00Z",
    ]
    assert [item["occurrence_id"] for item in first.json()] == [
        item["occurrence_id"] for item in second.json()
    ]
    assert all(item["series_id"] == created.json()["id"] for item in first.json())

    with SessionLocal() as db:
        assert db.scalar(select(func.count(Event.id))) == 1


def test_weekly_recurrence_preserves_wall_clock_across_dst(client: TestClient, auth: dict[str, str]):
    assert client.patch("/api/v1/auth/me", headers=auth, json={"timezone": "America/New_York"}).status_code == 200
    created = client.post("/api/v1/events", headers=auth, json={
        "title": "Понедельник в девять",
        "start_at": "2026-10-26T09:00:00",
        "end_at": "2026-10-26T10:00:00",
        "category": "work",
        "color": "#5B9DF5",
        "recurrence_rule": "FREQ=WEEKLY",
    })
    assert created.status_code == 201
    response = client.get("/api/v1/events", headers=auth, params={
        "start": "2026-10-26T00:00:00",
        "end": "2026-11-03T00:00:00",
    })
    assert response.status_code == 200
    starts = [datetime.fromisoformat(item["start_at"].replace("Z", "+00:00")) for item in response.json()]
    assert starts == [
        datetime(2026, 10, 26, 13, tzinfo=UTC),
        datetime(2026, 11, 2, 14, tzinfo=UTC),
    ]


def test_recurrence_validation_and_range_limit(client: TestClient, auth: dict[str, str]):
    payload = {
        "title": "Некорректная серия",
        "start_at": "2026-08-19T09:00:00",
        "end_at": "2026-08-19T10:00:00",
        "category": "work",
        "color": "#5B9DF5",
        "recurrence_rule": "FREQ=MONTHLY",
    }
    assert client.post("/api/v1/events", headers=auth, json=payload).status_code == 422
    assert client.get("/api/v1/events", headers=auth, params={
        "start": "2026-01-01T00:00:00",
        "end": "2028-01-01T00:00:00",
    }).status_code == 422


def test_recurrence_is_shared_by_dashboard_analytics_overload_and_ai_context(client, auth):
    created = client.post("/api/v1/events", headers=auth, json={
        "title": "Ежедневный фокус",
        "start_at": "2026-08-13T09:00:00",
        "end_at": "2026-08-13T10:00:00",
        "category": "focus",
        "color": "#D3AE43",
        "recurrence_rule": "FREQ=DAILY",
    })
    assert created.status_code == 201
    target = date(2026, 8, 19)
    local_now = datetime(2026, 8, 19, 8, tzinfo=ZoneInfo("Europe/Moscow"))
    with SessionLocal() as db, patch("backend.services.analytics.today_for", return_value=target), patch(
        "backend.services.analytics.now_for", return_value=local_now
    ):
        user = db.get(User, 1)
        assert user is not None
        dashboard = dashboard_for_user(db, user)
        analytics = analytics_for_user(db, user.id, 7, user.timezone)
        overload = overload_for_user(db, user.id, target, user.timezone)
        context = UserContextService().build(db, user, "фокус", selected_date=target)

    assert len(dashboard["events_today"]) == 1
    assert dashboard["events_today"][0]["occurrence_id"].startswith(f"event:{created.json()['id']}:")
    assert analytics["category_minutes"]["focus"] == 7 * 60
    assert overload["scheduled_minutes"] == 60
    assert [event["title"] for event in context["events"]] == ["Ежедневный фокус"]
