from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser, DbSession
from backend.billing.catalog import get_plan, plans
from backend.billing.models import UserSubscription
from backend.config import settings
from backend.models.entities import User
from backend.services.time import utc_now

PLAN_ORDER = {"free": 0, "pro": 1, "executive": 2}


def get_or_create_subscription(db: Session, user_id: int) -> UserSubscription:
    subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user_id))
    if subscription is not None:
        return subscription
    try:
        with db.begin_nested():
            subscription = UserSubscription(user_id=user_id, plan_code="free", status="free")
            db.add(subscription)
            db.flush()
    except IntegrityError:
        subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user_id))
        if subscription is None:
            raise
    return subscription


def effective_plan_code(subscription: UserSubscription) -> str:
    if subscription.plan_code == "free" or subscription.status in {"free", "pending", "canceled", "expired"}:
        return "free"
    now = utc_now()
    if subscription.status == "past_due" and subscription.current_period_end:
        grace_end = subscription.current_period_end + timedelta(days=settings.subscription_grace_period_days)
        if now > grace_end:
            return "free"
    if subscription.status in {"active", "past_due", "cancel_scheduled"}:
        if subscription.current_period_end is None or now <= subscription.current_period_end or subscription.status == "past_due":
            return subscription.plan_code
    return "free"


def has_entitlement(user: User, feature_code: str, db: Session) -> bool:
    subscription = get_or_create_subscription(db, user.id)
    plan = get_plan(effective_plan_code(subscription), require_available=False)
    return feature_code in plan.entitlements


def required_plan_for(feature_code: str) -> str:
    for code in ("free", "pro", "executive"):
        if feature_code in plans()[code].entitlements:
            return code
    return "executive"


def require_entitlement(feature_code: str) -> Callable:
    def dependency(user: CurrentUser, db: DbSession) -> User:
        if not has_entitlement(user, feature_code, db):
            required = required_plan_for(feature_code)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "subscription_required",
                    "required_plan": required,
                    "message": f"Функция доступна на тарифе {required.upper()} или выше.",
                },
            )
        return user

    return dependency


def EntitledUser(feature_code: str):
    return Annotated[User, Depends(require_entitlement(feature_code))]
