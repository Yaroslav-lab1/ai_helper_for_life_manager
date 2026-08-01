from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.common import ORMModel


class SettingsUpdate(BaseModel):
    theme: str | None = Field(default=None, pattern="^(system|light|dark)$")
    language: str | None = Field(default=None, max_length=10)
    notifications_enabled: bool | None = None
    daily_digest_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    workday_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    workday_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekly_focus_hours: int | None = Field(default=None, ge=1, le=80)
    compact_mode: bool | None = None
    ai_tone: str | None = Field(default=None, pattern="^(supportive|direct|coach)$")


class SettingsResponse(ORMModel):
    theme: str
    language: str
    notifications_enabled: bool
    daily_digest_time: str
    workday_start: str
    workday_end: str
    weekly_focus_hours: int
    compact_mode: bool
    ai_tone: str
    ai_context_consent_version: str | None
    ai_context_consent_at: datetime | None
    ai_context_consent_revoked_at: datetime | None


class AIConsentAccept(BaseModel):
    accepted: Literal[True]
    policy_version: str


class AIConsentStatus(BaseModel):
    required: bool
    active: bool
    policy_version: str
    accepted_at: datetime | None
    revoked_at: datetime | None
