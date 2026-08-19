from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    title: str
    body: str
    scheduled_at: datetime
    sent_at: datetime | None
    read_at: datetime | None


class NotificationSummary(BaseModel):
    unread: int
    items: list[NotificationResponse]
