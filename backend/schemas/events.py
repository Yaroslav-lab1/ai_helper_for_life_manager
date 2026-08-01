from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from backend.schemas.common import ORMModel


class EventBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    start_at: datetime
    end_at: datetime
    category: str = "personal"
    color: str = Field(default="#6C5CE7", pattern=r"^#[0-9A-Fa-f]{6}$")
    location: str | None = None
    recurrence_rule: str | None = None
    reminder_minutes: int | None = Field(default=None, ge=0, le=10080)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        return self


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    category: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    location: str | None = None
    recurrence_rule: str | None = None
    reminder_minutes: int | None = Field(default=None, ge=0, le=10080)


class EventResponse(EventBase, ORMModel):
    id: int
    user_id: int
    created_at: datetime
