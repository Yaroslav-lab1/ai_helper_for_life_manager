from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DayOfWeek = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class StrictPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Milestone(StrictPlanModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=2000)
    deadline: date
    success_criteria: list[str] = Field(min_length=1, max_length=8)


class MonthlyAction(StrictPlanModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    actions: list[str] = Field(min_length=1, max_length=12)


class WeeklyPlanItem(StrictPlanModel):
    day_of_week: DayOfWeek
    duration_minutes: int = Field(ge=5, le=480)
    action: str = Field(min_length=1, max_length=500)


class PlannedTask(StrictPlanModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    estimated_minutes: int = Field(ge=5, le=1440)
    deadline: date | None = None


class PlannedHabit(StrictPlanModel):
    title: str = Field(min_length=1, max_length=160)
    frequency: Literal["daily", "weekdays", "weekly"]
    duration_minutes: int = Field(ge=1, le=480)


class ScheduleSuggestion(StrictPlanModel):
    title: str = Field(min_length=1, max_length=200)
    preferred_days: list[DayOfWeek] = Field(min_length=1, max_length=7)
    preferred_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    duration_minutes: int = Field(ge=5, le=480)


class PlanRisk(StrictPlanModel):
    risk: str = Field(min_length=1, max_length=500)
    mitigation: str = Field(min_length=1, max_length=1000)


class ProgressMetric(StrictPlanModel):
    name: str = Field(min_length=1, max_length=240)
    target: str = Field(min_length=1, max_length=500)


class NextAction(StrictPlanModel):
    title: str = Field(min_length=1, max_length=240)
    estimated_minutes: int = Field(ge=1, le=1440)


class GoalPlanPayload(StrictPlanModel):
    goal_summary: str = Field(min_length=1, max_length=1000)
    strategy: str = Field(min_length=1, max_length=3000)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=3)
    milestones: list[Milestone] = Field(min_length=1, max_length=20)
    monthly_actions: list[MonthlyAction] = Field(default_factory=list, max_length=36)
    weekly_plan: list[WeeklyPlanItem] = Field(default_factory=list, max_length=21)
    tasks: list[PlannedTask] = Field(default_factory=list, max_length=40)
    habits: list[PlannedHabit] = Field(default_factory=list, max_length=12)
    schedule_suggestions: list[ScheduleSuggestion] = Field(default_factory=list, max_length=20)
    risks: list[PlanRisk] = Field(default_factory=list, max_length=15)
    progress_metrics: list[ProgressMetric] = Field(default_factory=list, max_length=15)
    first_next_action: NextAction


def goal_plan_response_schema(*, preserve_constraints: bool = False) -> dict[str, Any]:
    """Flatten references while optionally keeping constraints supported by GigaChat."""
    source = GoalPlanPayload.model_json_schema()
    definitions = source.get("$defs", {})
    unsupported = {"$defs", "title", "default", "format"}
    if not preserve_constraints:
        unsupported.update({
            "pattern", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems",
        })

    def simplify(node: Any) -> Any:
        if isinstance(node, list):
            return [simplify(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            name = str(node["$ref"]).rsplit("/", 1)[-1]
            return simplify(definitions[name])
        if "anyOf" in node:
            non_null = [item for item in node["anyOf"] if item.get("type") != "null"]
            return simplify(non_null[0] if non_null else {"type": "string"})
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                result[key] = {property_name: simplify(property_schema) for property_name, property_schema in value.items()}
            elif key not in unsupported:
                result[key] = simplify(value)
        return result

    schema = simplify(source)
    schema["additionalProperties"] = False
    return schema


class AIStatusResponse(BaseModel):
    available: bool
    provider: str
    model: str
    message: str


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class AIMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    selected_date: date | None = None
    auto_execute_actions: bool = False


class GoalPlanRequest(BaseModel):
    context: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)


class GoalPlanUpdate(BaseModel):
    plan: GoalPlanPayload
    reason: str = Field(default="Изменено пользователем", max_length=500)


class GoalPlanApplyRequest(BaseModel):
    confirm: bool = False
    components: list[Literal["milestones", "tasks", "habits", "schedule_suggestions"]] = Field(
        default_factory=lambda: ["milestones", "tasks", "habits", "schedule_suggestions"]
    )
    selected_indices: dict[str, list[int]] | None = None


class GoalPlanResponse(BaseModel):
    id: int
    goal_id: int
    status: str
    version: int
    plan: GoalPlanPayload
    diff: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class GoalPlanApplyResponse(BaseModel):
    status: str
    created: dict[str, int]


class ActionProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    description: str
    status: str
    requires_confirmation: bool = True


class ActionProposalUpdate(BaseModel):
    payload: dict[str, Any] | None = None
    status: Literal["cancelled"] | None = None
