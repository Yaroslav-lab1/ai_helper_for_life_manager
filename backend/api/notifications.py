from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, DbSession
from backend.models import NotificationDelivery
from backend.schemas.notifications import NotificationSummary
from backend.services.time import utc_now


router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _serialize(item: NotificationDelivery) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "status": item.status,
        "title": item.subject,
        "body": item.body,
        "scheduled_at": item.scheduled_at,
        "sent_at": item.sent_at,
        "read_at": item.read_at,
    }


@router.get("", response_model=NotificationSummary)
def list_notifications(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
):
    visible = ["pending", "retry", "processing", "sent", "failed"]
    items = db.scalars(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.user_id == user.id,
            NotificationDelivery.status.in_(visible),
        )
        .order_by(NotificationDelivery.scheduled_at.desc())
        .limit(limit)
    ).all()
    unread = db.scalar(
        select(func.count(NotificationDelivery.id)).where(
            NotificationDelivery.user_id == user.id,
            NotificationDelivery.status == "sent",
            NotificationDelivery.read_at.is_(None),
        )
    ) or 0
    return {"unread": unread, "items": [_serialize(item) for item in items]}


@router.post("/{notification_id}/read", response_model=NotificationSummary)
def mark_notification_read(notification_id: int, user: CurrentUser, db: DbSession):
    item = db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.id == notification_id,
            NotificationDelivery.user_id == user.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if item.read_at is None:
        item.read_at = utc_now()
        db.commit()
    return list_notifications(user, db, 20)
