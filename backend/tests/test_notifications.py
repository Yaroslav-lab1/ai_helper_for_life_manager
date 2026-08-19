from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Event, NotificationDelivery, Task, User
from backend.services.notifications import (
    claim_next_delivery,
    deliver_claimed,
    enqueue_due_notifications,
)
from backend.services.time import utc_now


def verified_user(db, *, timezone="Europe/Moscow") -> User:
    user = db.get(User, 1)
    assert user is not None and user.settings is not None
    user.timezone = timezone
    user.email_verified_at = utc_now()
    user.settings.notifications_enabled = True
    db.commit()
    return user


def test_reminders_and_digest_are_enqueued_once(client, auth):
    del client, auth
    now = datetime(2026, 8, 19, 7, 0, tzinfo=UTC)  # 10:00 Europe/Moscow
    with SessionLocal() as db:
        user = verified_user(db)
        user.settings.daily_digest_time = "09:00"
        db.add(Event(
            user_id=user.id,
            title="Ежедневный статус",
            start_at=now + timedelta(minutes=10),
            end_at=now + timedelta(minutes=40),
            category="work",
            color="#5B9DF5",
            recurrence_rule="FREQ=DAILY",
            reminder_minutes=15,
        ))
        db.add(Task(
            user_id=user.id,
            title="Ответить клиенту",
            reminder_at=now,
            due_at=now + timedelta(hours=2),
        ))
        db.commit()
        assert enqueue_due_notifications(db, now) == 5
        assert enqueue_due_notifications(db, now) == 0
        assert db.scalar(select(func.count(NotificationDelivery.id))) == 5
        assert {item.kind for item in db.scalars(select(NotificationDelivery)).all()} == {
            "event_reminder", "task_reminder", "daily_digest",
        }


def test_delivery_is_claimed_once_and_not_resent(client, auth, monkeypatch):
    del client, auth
    now = datetime(2026, 8, 19, 7, 0, tzinfo=UTC)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("backend.services.notifications.sender.send", lambda email, subject, body: sent.append((email, subject)))
    with SessionLocal() as db:
        user = verified_user(db)
        db.add(NotificationDelivery(
            user_id=user.id,
            kind="task_reminder",
            dedupe_key="once",
            subject="Напоминание",
            body="Текст",
            scheduled_at=now,
            next_attempt_at=now,
        ))
        db.commit()
        first = claim_next_delivery(db, "worker-a", now)
        assert first is not None
        assert claim_next_delivery(db, "worker-b", now) is None
        delivered = deliver_claimed(db, first.id, "worker-a", now)
        assert delivered.status == "sent"
        assert claim_next_delivery(db, "worker-a", now + timedelta(hours=1)) is None
    assert sent == [("test@example.com", "Напоминание")]


def test_disabled_notifications_skip_claimed_delivery(client, auth, monkeypatch):
    del client, auth
    now = datetime(2026, 8, 19, 7, 0, tzinfo=UTC)
    sent: list[str] = []
    monkeypatch.setattr("backend.services.notifications.sender.send", lambda *_: sent.append("sent"))
    with SessionLocal() as db:
        user = verified_user(db)
        db.add(NotificationDelivery(
            user_id=user.id,
            kind="daily_digest",
            dedupe_key="disabled",
            subject="Дайджест",
            body="Текст",
            scheduled_at=now,
            next_attempt_at=now,
        ))
        db.commit()
        delivery = claim_next_delivery(db, "worker", now)
        assert delivery is not None
        user.settings.notifications_enabled = False
        db.commit()
        assert deliver_claimed(db, delivery.id, "worker", now).status == "skipped"
    assert sent == []


def test_failed_delivery_retries_with_backoff_and_stops(client, auth, monkeypatch):
    del client, auth
    now = datetime(2026, 8, 19, 7, 0, tzinfo=UTC)
    monkeypatch.setattr(settings, "notification_max_attempts", 2)
    monkeypatch.setattr(settings, "notification_retry_base_seconds", 10)
    monkeypatch.setattr("backend.services.notifications.sender.send", lambda *_: (_ for _ in ()).throw(RuntimeError("secret details")))
    with SessionLocal() as db:
        user = verified_user(db)
        db.add(NotificationDelivery(
            user_id=user.id,
            kind="task_reminder",
            dedupe_key="retry",
            subject="Напоминание",
            body="Текст",
            scheduled_at=now,
            next_attempt_at=now,
        ))
        db.commit()
        first = claim_next_delivery(db, "worker", now)
        assert first is not None
        retried = deliver_claimed(db, first.id, "worker", now)
        assert retried.status == "retry"
        assert retried.last_error == "RuntimeError"
        assert claim_next_delivery(db, "worker", now + timedelta(seconds=9)) is None
        second = claim_next_delivery(db, "worker", now + timedelta(seconds=10))
        assert second is not None
        failed = deliver_claimed(db, second.id, "worker", now + timedelta(seconds=10))
        assert failed.status == "failed"
        assert claim_next_delivery(db, "worker", now + timedelta(days=1)) is None


def test_digest_uses_users_local_day(client, auth):
    del client, auth
    now = datetime(2026, 8, 19, 21, 30, tzinfo=UTC)
    with SessionLocal() as db:
        user = verified_user(db, timezone="Europe/Moscow")  # already 20 August
        user.settings.daily_digest_time = "00:15"
        db.commit()
        assert enqueue_due_notifications(db, now) == 1
        delivery = db.scalar(select(NotificationDelivery))
        assert delivery is not None
        assert delivery.dedupe_key == f"daily-digest:{user.id}:2026-08-20"
        assert delivery.scheduled_at == datetime(2026, 8, 19, 21, 15, tzinfo=UTC)


def test_notification_api_is_user_scoped_and_marks_sent_item_read(client, auth):
    now = datetime(2026, 8, 19, 7, 0, tzinfo=UTC)
    with SessionLocal() as db:
        user = db.get(User, 1)
        assert user is not None
        db.add(NotificationDelivery(
            user_id=user.id,
            kind="task_reminder",
            dedupe_key="api-visible",
            subject="Видимое напоминание",
            body="Только для владельца",
            status="sent",
            scheduled_at=now,
            next_attempt_at=now,
            sent_at=now,
        ))
        db.commit()

    listed = client.get("/api/v1/notifications", headers=auth)
    assert listed.status_code == 200
    assert listed.json()["unread"] == 1
    assert listed.json()["items"][0]["title"] == "Видимое напоминание"
    assert "last_error" not in listed.json()["items"][0]
    notification_id = listed.json()["items"][0]["id"]

    marked = client.post(f"/api/v1/notifications/{notification_id}/read", headers=auth)
    assert marked.status_code == 200
    assert marked.json()["unread"] == 0
    assert marked.json()["items"][0]["read_at"] is not None

    second = client.post("/api/v1/auth/register", json={
        "email": "notification-other@example.com",
        "password": "long-secure-password",
        "name": "Other User",
    }).json()
    other_headers = {"Authorization": f"Bearer {second['access_token']}"}
    assert client.get("/api/v1/notifications", headers=other_headers).json() == {"unread": 0, "items": []}
    assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=other_headers).status_code == 404
