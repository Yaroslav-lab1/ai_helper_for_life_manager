from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.common import ORMModel


class HabitCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    emoji: str = Field(default="✓", max_length=12)
    cadence: Literal["daily", "weekdays", "weekly"] = "daily"
    target_per_week: int = Field(default=7, ge=1, le=7)
    color: str = Field(default="#00B894", pattern=r"^#[0-9A-Fa-f]{6}$")


class HabitUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    emoji: str | None = Field(default=None, max_length=12)
    cadence: Literal["daily", "weekdays", "weekly"] | None = None
    target_per_week: int | None = Field(default=None, ge=1, le=7)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    archived: bool | None = None


class HabitCheckinCreate(BaseModel):
    checkin_date: date | None = None
    value: float = Field(default=1, gt=0)
    note: str | None = Field(default=None, max_length=255)


class HabitCheckinResponse(HabitCheckinCreate, ORMModel):
    id: int
    checkin_date: date


class HabitResponse(HabitCreate, ORMModel):
    id: int
    user_id: int
    archived: bool
    created_at: datetime
    current_streak: int = 0
    best_streak: int = 0
    completed_today: bool = False
    week_count: int = 0
    checkins: list[HabitCheckinResponse] = []
