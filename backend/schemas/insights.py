from datetime import date, datetime

from pydantic import BaseModel, Field

from backend.schemas.common import ORMModel


class BalanceCreate(BaseModel):
    assessment_date: date | None = None
    health: int = Field(ge=1, le=10)
    career: int = Field(ge=1, le=10)
    finance: int = Field(ge=1, le=10)
    relationships: int = Field(ge=1, le=10)
    growth: int = Field(ge=1, le=10)
    recreation: int = Field(ge=1, le=10)
    environment: int = Field(ge=1, le=10)
    contribution: int = Field(ge=1, le=10)
    note: str | None = None


class BalanceResponse(BalanceCreate, ORMModel):
    id: int
    user_id: int
    assessment_date: date
    average: float = 0


class RecommendationResponse(ORMModel):
    id: int
    kind: str
    title: str
    body: str
    action: str | None
    status: str
    created_at: datetime


class RecommendationUpdate(BaseModel):
    status: str = Field(pattern="^(new|accepted|dismissed|done)$")


class OverloadResponse(BaseModel):
    level: str
    score: int
    scheduled_minutes: int
    open_tasks: int
    urgent_tasks: int
    signals: list[str]
    suggestion: str


class AnalyticsResponse(BaseModel):
    period_days: int
    tasks_completed: int
    task_completion_rate: float
    focus_minutes: int
    habit_completion_rate: float
    active_goal_progress: float
    balance_score: float | None
    productive_days: list[dict]
    category_minutes: dict[str, int]


class EnergyPoint(BaseModel):
    hour: int = Field(ge=0, le=23)
    level: int = Field(ge=0, le=100)
    kind: str
    activity: str
    recommendation: str


class EnergyFactor(BaseModel):
    label: str
    value: str
    impact: str
    tone: str


class EnergyRecommendation(BaseModel):
    time: str
    title: str
    body: str
    kind: str


class EnergyResponse(BaseModel):
    date: date
    score: int = Field(ge=0, le=100)
    status: str
    peak_start: str
    peak_end: str
    points: list[EnergyPoint]
    factors: list[EnergyFactor]
    recommendations: list[EnergyRecommendation]


class DashboardResponse(BaseModel):
    greeting: str
    date_label: str
    focus_score: int
    tasks_due: int
    completed_today: int
    habit_rate: float
    events_today: list[dict]
    priority_tasks: list[dict]
    goals: list[dict]
    habits: list[dict]
    overload: OverloadResponse
    recommendation: dict | None
