from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from backend.config import settings

MONEY = Decimal("0.01")
YEARLY_FACTOR = Decimal("0.83")
YEARLY_DISCOUNT_PERCENT = 17
BILLING_INTERVALS = {"monthly", "yearly"}


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    monthly_price: Decimal
    entitlements: frozenset[str]
    features: tuple[str, ...]
    available: bool = True

    def price(self, interval: str) -> Decimal:
        if self.code == "free":
            return Decimal("0.00")
        if interval not in BILLING_INTERVALS:
            raise ValueError("Unsupported billing interval")
        if interval == "monthly":
            return self.monthly_price.quantize(MONEY)
        return (self.monthly_price * 12 * YEARLY_FACTOR).quantize(MONEY, ROUND_HALF_UP)


FREE_ENTITLEMENTS = frozenset({"calendar", "tasks", "goals", "habits", "basic_analytics"})
PRO_ENTITLEMENTS = FREE_ENTITLEMENTS | frozenset(
    {
        "ai_assistant",
        "ai_day_planning",
        "ai_period_analysis",
        "overload_analysis",
        "personal_recommendations",
        "smart_goal_planning",
    }
)
EXECUTIVE_ENTITLEMENTS = PRO_ENTITLEMENTS | frozenset(
    {
        "deep_time_analysis",
        "communication_analysis",
        "efficiency_analysis",
        "life_report",
        "advanced_ai_insights",
        "behavior_model",
    }
)


def plans() -> dict[str, Plan]:
    return {
        "free": Plan(
            "free",
            "FREE",
            Decimal("0.00"),
            FREE_ENTITLEMENTS,
            ("Календарь", "Задачи и цели", "Привычки", "Базовая аналитика"),
        ),
        "pro": Plan(
            "pro",
            "PRO",
            Decimal("399.00"),
            PRO_ENTITLEMENTS,
            (
                "Всё из FREE",
                "AI-планирование дня",
                "AI-анализ дня и недели",
                "Анализ нагрузки",
                "Персональные рекомендации",
                "Умное планирование целей",
                "AI-ассистент",
            ),
        ),
        "executive": Plan(
            "executive",
            "EXECUTIVE",
            Decimal("990.00"),
            EXECUTIVE_ENTITLEMENTS,
            (
                "Всё из PRO",
                "Архитектура Executive-возможностей",
                "Расширенные entitlement-коды для будущих модулей",
            ),
            available=settings.executive_plan_enabled,
        ),
    }


def get_plan(code: str, *, require_available: bool = True) -> Plan:
    plan = plans().get(code)
    if plan is None or require_available and not plan.available:
        raise ValueError("Unknown or unavailable plan")
    return plan


def catalog_payload() -> list[dict]:
    result = []
    for plan in plans().values():
        monthly = plan.price("monthly")
        yearly = plan.price("yearly")
        full_year = (monthly * 12).quantize(MONEY)
        result.append(
            {
                "code": plan.code,
                "name": plan.name,
                "available": plan.available,
                "currency": settings.yookassa_currency,
                "monthly_price": f"{monthly:.2f}",
                "yearly_price": f"{yearly:.2f}",
                "yearly_monthly_equivalent": f"{(yearly / 12).quantize(MONEY):.2f}",
                "yearly_savings": f"{(full_year - yearly).quantize(MONEY):.2f}",
                "yearly_discount_percent": YEARLY_DISCOUNT_PERCENT,
                "features": list(plan.features),
                "entitlements": sorted(plan.entitlements),
            }
        )
    return result
