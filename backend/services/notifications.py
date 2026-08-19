from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Callable
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Event, NotificationDelivery, Task, User
from backend.services.analytics import overload_for_user
from backend.services.email import sender
from backend.services.recurrence import events_for_range
from backend.services.time import day_bounds_utc, in_timezone, local_datetime_utc, today_for, utc_now


logger = logging.getLogger(__name__)
DELIVERABLE_STATUSES = {"pending", "retry"}
MAX_EVENT_REMINDER_MINUTES = 10080


def _enqueue(
    db: Session,
    *,
    user_id: int,
    kind: str,
    dedupe_key: str,
    subject: str,
    body: str,
    scheduled_at: datetime,
) -> bool:
    if db.scalar(select(NotificationDelivery.id).where(NotificationDelivery.dedupe_key == dedupe_key)):
        return False
    try:
        with db.begin_nested():
            db.add(NotificationDelivery(
                user_id=user_id,
                kind=kind,
                dedupe_key=dedupe_key,
                subject=subject[:255],
                body=body,
                scheduled_at=scheduled_at,
                next_attempt_at=scheduled_at,
            ))
            db.flush()
    except IntegrityError:
        return False
    return True


def _event_reminders(db: Session, user: User, now: datetime, horizon: datetime) -> int:
    occurrence_end = horizon + timedelta(minutes=MAX_EVENT_REMINDER_MINUTES)
    occurrences = events_for_range(db, user.id, now, occurrence_end, user.timezone)
    created = 0
    for occurrence in occurrences:
        if occurrence.reminder_minutes is None:
            continue
        scheduled_at = occurrence.start_at - timedelta(minutes=occurrence.reminder_minutes)
        if not (now - timedelta(hours=24) <= scheduled_at <= horizon):
            continue
        local_start = in_timezone(occurrence.start_at, user.timezone)
        created += _enqueue(
            db,
            user_id=user.id,
            kind="event_reminder",
            dedupe_key=f"event-reminder:{occurrence.occurrence_id}:{occurrence.reminder_minutes}",
            subject=f"Напоминание: {occurrence.title}",
            body=(
                f"Событие «{occurrence.title}» начнётся "
                f"{local_start.strftime('%d.%m.%Y в %H:%M')}."
            ),
            scheduled_at=scheduled_at,
        )
    return created


def _task_reminders(db: Session, user: User, now: datetime, horizon: datetime) -> int:
    tasks = db.scalars(
        select(Task).where(
            Task.user_id == user.id,
            Task.status.in_(["todo", "in_progress"]),
            Task.reminder_at.is_not(None),
            Task.reminder_at >= now - timedelta(hours=24),
            Task.reminder_at <= horizon,
        )
    ).all()
    created = 0
    for task in tasks:
        scheduled_at = task.reminder_at
        if scheduled_at is None:
            continue
        due = (
            f" Срок: {in_timezone(task.due_at, user.timezone).strftime('%d.%m.%Y %H:%M')}."
            if task.due_at
            else ""
        )
        created += _enqueue(
            db,
            user_id=user.id,
            kind="task_reminder",
            dedupe_key=f"task-reminder:{task.id}:{scheduled_at.isoformat()}",
            subject=f"Напоминание о задаче: {task.title}",
            body=f"Задача «{task.title}» ожидает выполнения.{due}",
            scheduled_at=scheduled_at,
        )
    return created


def _digest_body(db: Session, user: User, local_day) -> str:
    start, end = day_bounds_utc(local_day, user.timezone)
    events = events_for_range(db, user.id, start, end, user.timezone, limit=30)
    tasks = db.scalars(
        select(Task)
        .where(Task.user_id == user.id, Task.status.in_(["todo", "in_progress"]))
        .order_by(Task.due_at)
        .limit(12)
    ).all()
    overload = overload_for_user(db, user.id, local_day, user.timezone)
    lines = [f"Доброе утро, {user.name.split()[0]}!", "", "Ближайшие события:"]
    if events:
        lines.extend(
            f"• {in_timezone(item.start_at, user.timezone).strftime('%H:%M')} — {item.title}"
            for item in events[:8]
        )
    else:
        lines.append("• Событий на сегодня нет")
    lines.extend(["", "Открытые задачи:"])
    if tasks:
        lines.extend(f"• {item.title} ({item.priority})" for item in tasks[:8])
    else:
        lines.append("• Открытых задач нет")
    lines.extend([
        "",
        f"Нагрузка: {overload['score']}/100 ({overload['level']}).",
        overload["suggestion"],
    ])
    return "\n".join(lines)


def _daily_digest(db: Session, user: User, now: datetime) -> int:
    user_settings = user.settings
    if user_settings is None:
        return 0
    try:
        digest_time = time.fromisoformat(user_settings.daily_digest_time)
    except ValueError:
        return 0
    local_day = today_for(user.timezone, now=now)
    scheduled_at = local_datetime_utc(local_day, digest_time, user.timezone)
    if scheduled_at > now:
        return 0
    return int(_enqueue(
        db,
        user_id=user.id,
        kind="daily_digest",
        dedupe_key=f"daily-digest:{user.id}:{local_day.isoformat()}",
        subject=f"План на {local_day.strftime('%d.%m.%Y')} — Axel One",
        body=_digest_body(db, user, local_day),
        scheduled_at=scheduled_at,
    ))


def enqueue_due_notifications(db: Session, now: datetime | None = None) -> int:
    now = now or utc_now()
    horizon = now + timedelta(hours=settings.notification_schedule_horizon_hours)
    users = db.scalars(select(User).options(selectinload(User.settings))).all()
    created = 0
    for user in users:
        if user.email_verified_at is None or user.settings is None or not user.settings.notifications_enabled:
            continue
        created += _event_reminders(db, user, now, horizon)
        created += _task_reminders(db, user, now, horizon)
        created += _daily_digest(db, user, now)
    db.commit()
    return created


def recover_stale_claims(db: Session, now: datetime | None = None) -> int:
    now = now or utc_now()
    stale_before = now - timedelta(seconds=settings.notification_claim_timeout_seconds)
    result = db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.status == "processing",
            NotificationDelivery.locked_at < stale_before,
        )
        .values(status="retry", locked_at=None, locked_by=None, next_attempt_at=now, updated_at=now)
    )
    db.commit()
    return int(result.rowcount or 0)


def claim_next_delivery(
    db: Session,
    worker_id: str,
    now: datetime | None = None,
) -> NotificationDelivery | None:
    now = now or utc_now()
    candidate_ids = db.scalars(
        select(NotificationDelivery.id)
        .where(
            NotificationDelivery.status.in_(DELIVERABLE_STATUSES),
            NotificationDelivery.next_attempt_at <= now,
        )
        .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
        .limit(settings.notification_batch_size)
    ).all()
    for delivery_id in candidate_ids:
        result = db.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.status.in_(DELIVERABLE_STATUSES),
                NotificationDelivery.next_attempt_at <= now,
            )
            .values(status="processing", locked_at=now, locked_by=worker_id, updated_at=now)
        )
        if result.rowcount:
            db.commit()
            return db.get(NotificationDelivery, delivery_id)
        db.rollback()
    return None


def deliver_claimed(
    db: Session,
    delivery_id: int,
    worker_id: str,
    now: datetime | None = None,
) -> NotificationDelivery:
    now = now or utc_now()
    delivery = db.get(NotificationDelivery, delivery_id)
    if delivery is None or delivery.status != "processing" or delivery.locked_by != worker_id:
        raise LookupError("Notification delivery is not claimed by this worker")
    user = db.scalar(select(User).options(selectinload(User.settings)).where(User.id == delivery.user_id))
    if (
        user is None
        or user.email_verified_at is None
        or user.settings is None
        or not user.settings.notifications_enabled
    ):
        delivery.status = "skipped"
        delivery.last_error = "notifications_disabled_or_email_unverified"
        delivery.locked_at = None
        delivery.locked_by = None
        delivery.updated_at = now
        db.commit()
        return delivery

    delivery.attempts += 1
    try:
        sender.send(user.email, delivery.subject, delivery.body)
    except Exception as exc:
        delivery.last_error = type(exc).__name__[:160]
        delivery.locked_at = None
        delivery.locked_by = None
        if delivery.attempts >= settings.notification_max_attempts:
            delivery.status = "failed"
        else:
            delay = min(
                settings.notification_retry_max_seconds,
                settings.notification_retry_base_seconds * (2 ** (delivery.attempts - 1)),
            )
            delivery.status = "retry"
            delivery.next_attempt_at = now + timedelta(seconds=delay)
    else:
        delivery.status = "sent"
        delivery.sent_at = now
        delivery.last_error = None
        delivery.locked_at = None
        delivery.locked_by = None
    delivery.updated_at = now
    db.commit()
    db.refresh(delivery)
    return delivery


def run_notification_cycle(
    now: datetime | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    cycle_now = now or utc_now()
    worker_id = uuid4().hex
    with SessionLocal() as db:
        recover_stale_claims(db, cycle_now)
        enqueue_due_notifications(db, cycle_now)
    delivered = 0
    for _ in range(settings.notification_batch_size):
        if should_stop and should_stop():
            break
        with SessionLocal() as db:
            claimed = claim_next_delivery(db, worker_id, cycle_now)
            if claimed is None:
                break
            delivery_id = claimed.id
        with SessionLocal() as db:
            deliver_claimed(db, delivery_id, worker_id, cycle_now)
        delivered += 1
    return delivered


class NotificationWorker:
    def __init__(self):
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(run_notification_cycle, None, self._stop.is_set)
            except Exception:
                logger.exception("Notification worker cycle failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=settings.notification_poll_interval_seconds,
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()
