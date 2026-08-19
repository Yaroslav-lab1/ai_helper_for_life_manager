from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient


def _register(client: TestClient, timezone: str, index: int) -> dict[str, str]:
    response = client.post("/api/v1/auth/register", json={
        "email": f"timezone-{index}@example.com",
        "password": "long-secure-password",
        "name": "Timezone User",
        "timezone": timezone,
    })
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize(("timezone", "created_local", "created_utc", "edited_local", "edited_utc"), [
    ("UTC", "2026-07-01T09:00:00", datetime(2026, 7, 1, 9, tzinfo=UTC), "2026-07-02T10:00:00", datetime(2026, 7, 2, 10, tzinfo=UTC)),
    ("Europe/Moscow", "2026-07-01T09:00:00", datetime(2026, 7, 1, 6, tzinfo=UTC), "2026-07-02T10:00:00", datetime(2026, 7, 2, 7, tzinfo=UTC)),
    # New York changes from UTC-4 to UTC-5 between these two wall-clock values.
    ("America/New_York", "2026-10-30T09:00:00", datetime(2026, 10, 30, 13, tzinfo=UTC), "2026-11-02T09:00:00", datetime(2026, 11, 2, 14, tzinfo=UTC)),
])
def test_naive_task_datetimes_are_user_local_on_create_and_edit(
    client: TestClient,
    timezone: str,
    created_local: str,
    created_utc: datetime,
    edited_local: str,
    edited_utc: datetime,
):
    headers = _register(client, timezone, abs(hash(timezone)))
    created = client.post("/api/v1/tasks", headers=headers, json={
        "title": "Local wall clock",
        "due_at": created_local,
        "reminder_at": created_local,
    })
    assert created.status_code == 201
    assert datetime.fromisoformat(created.json()["due_at"]).astimezone(UTC) == created_utc
    assert datetime.fromisoformat(created.json()["reminder_at"]).astimezone(UTC) == created_utc

    edited = client.patch(f"/api/v1/tasks/{created.json()['id']}", headers=headers, json={
        "due_at": edited_local,
        "reminder_at": edited_local,
    })
    assert edited.status_code == 200
    assert datetime.fromisoformat(edited.json()["due_at"]).astimezone(UTC) == edited_utc
    assert datetime.fromisoformat(edited.json()["reminder_at"]).astimezone(UTC) == edited_utc


def test_timezone_aware_task_datetime_keeps_the_same_instant(client: TestClient):
    headers = _register(client, "Europe/Moscow", 999)
    response = client.post("/api/v1/tasks", headers=headers, json={
        "title": "Absolute instant",
        "due_at": "2026-07-01T12:00:00+02:00",
    })
    assert response.status_code == 201
    assert datetime.fromisoformat(response.json()["due_at"]).astimezone(UTC) == datetime(2026, 7, 1, 10, tzinfo=UTC)
