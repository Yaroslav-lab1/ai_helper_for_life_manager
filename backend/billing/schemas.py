from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: Literal["pro", "executive"]
    billing_interval: Literal["monthly", "yearly"]


class ChangePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: Literal["free", "pro", "executive"]
    billing_interval: Literal["monthly", "yearly"] | None = None


class CheckoutResponse(BaseModel):
    payment_id: int
    confirmation_url: str


class PaymentResponse(BaseModel):
    id: int
    kind: str
    plan_code: str
    plan_name: str
    billing_interval: str
    amount: str
    currency: str
    status: str
    confirmation_url: str | None = None
    paid_at: datetime | None = None
    canceled_at: datetime | None = None
    failure_code: str | None = None


class SubscriptionResponse(BaseModel):
    plan_code: str
    billing_interval: str | None
    status: str
    effective_plan_code: str
    entitlements: list[str]
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    next_billing_at: datetime | None
    access_until: datetime | None
    scheduled_plan_code: str | None
    scheduled_billing_interval: str | None
    scheduled_change_at: datetime | None
    can_resume: bool
    retry_count: int
    next_retry_at: datetime | None


class BillingActionResponse(BaseModel):
    subscription: SubscriptionResponse
    message: str
