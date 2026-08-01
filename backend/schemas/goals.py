from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.common import ORMModel


class GoalStepResponse(ORMModel):
    id: int
    title: str
    order_index: int
    due_date: date | None
    is_completed: bool


class GoalCreate(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    description: str | None = None
    horizon: Literal["month", "quarter", "year", "long_term"] = "quarter"
    target_date: date | None = None


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=240)
    description: str | None = None
    horizon: Literal["month", "quarter", "year", "long_term"] | None = None
    target_date: date | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    status: Literal["active", "paused", "completed", "cancelled"] | None = None


class GoalResponse(GoalCreate, ORMModel):
    id: int
    user_id: int
    progress: int
    status: str
    created_at: datetime
    steps: list[GoalStepResponse] = []


class GoalStepUpdate(BaseModel):
    is_completed: bool


class DecomposeRequest(BaseModel):
    context: str | None = Field(default=None, max_length=1000)
