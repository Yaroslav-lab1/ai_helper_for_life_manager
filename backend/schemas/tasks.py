from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.common import ORMModel


Priority = Literal["low", "medium", "high", "urgent"]
TaskStatus = Literal["todo", "in_progress", "done", "cancelled"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    notes: str | None = None
    due_at: datetime | None = None
    priority: Priority = "medium"
    status: TaskStatus = "todo"
    estimate_minutes: int = Field(default=30, ge=5, le=1440)
    energy: Literal["low", "medium", "high"] = "medium"
    project: str | None = Field(default=None, max_length=100)
    reminder_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    notes: str | None = None
    due_at: datetime | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    estimate_minutes: int | None = Field(default=None, ge=5, le=1440)
    energy: Literal["low", "medium", "high"] | None = None
    project: str | None = None
    reminder_at: datetime | None = None


class TaskResponse(TaskCreate, ORMModel):
    id: int
    user_id: int
    completed_at: datetime | None
    created_at: datetime
