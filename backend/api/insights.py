from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from backend.ai import generate_recommendations
from backend.api.deps import CurrentUser, DbSession
from backend.models import BalanceAssessment, Recommendation
from backend.schemas.insights import (
    AnalyticsResponse,
    BalanceCreate,
    BalanceResponse,
    DashboardResponse,
    EnergyResponse,
    OverloadResponse,
    RecommendationResponse,
    RecommendationUpdate,
)
from backend.services.analytics import analytics_for_user, dashboard_for_user, energy_for_user, overload_for_user
from backend.services.time import today_for

router = APIRouter(tags=["Insights & AI"])

BALANCE_LABELS = {
    "health": "Здоровье", "career": "Карьера", "finance": "Финансы", "relationships": "Отношения",
    "growth": "Развитие", "recreation": "Отдых", "environment": "Окружение", "contribution": "Вклад",
}


def balance_dict(item: BalanceAssessment) -> dict:
    values = [item.health, item.career, item.finance, item.relationships, item.growth, item.recreation, item.environment, item.contribution]
    return {column.name: getattr(item, column.name) for column in item.__table__.columns} | {"average": round(sum(values) / len(values), 1)}


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(user: CurrentUser, db: DbSession):
    result = dashboard_for_user(db, user)
    rec = db.scalar(select(Recommendation).where(Recommendation.user_id == user.id, Recommendation.status == "new").order_by(Recommendation.created_at.desc()))
    if rec:
        result["recommendation"] = {"id": rec.id, "kind": rec.kind, "title": rec.title, "body": rec.body, "action": rec.action}
    return result


@router.get("/analytics", response_model=AnalyticsResponse)
def analytics(user: CurrentUser, db: DbSession, days: int = Query(default=30, ge=7, le=365)):
    return analytics_for_user(db, user.id, days, user.timezone)


@router.get("/overload", response_model=OverloadResponse)
def overload(user: CurrentUser, db: DbSession):
    return overload_for_user(db, user.id, timezone_name=user.timezone)


@router.get("/energy", response_model=EnergyResponse)
def energy(user: CurrentUser, db: DbSession, target_date: date | None = Query(default=None, alias="date")):
    return energy_for_user(db, user.id, target_date or today_for(user.timezone), user.timezone)


@router.post("/balance", response_model=BalanceResponse, status_code=status.HTTP_201_CREATED)
def create_balance(payload: BalanceCreate, user: CurrentUser, db: DbSession):
    values = payload.model_dump()
    values["assessment_date"] = values["assessment_date"] or today_for(user.timezone)
    item = BalanceAssessment(user_id=user.id, **values)
    db.add(item)
    db.commit()
    db.refresh(item)
    return balance_dict(item)


@router.get("/balance", response_model=list[BalanceResponse])
def list_balance(user: CurrentUser, db: DbSession):
    items = db.scalars(select(BalanceAssessment).where(BalanceAssessment.user_id == user.id).order_by(BalanceAssessment.assessment_date.desc())).all()
    return [balance_dict(item) for item in items]


@router.post("/recommendations/generate", response_model=list[RecommendationResponse])
def generate(user: CurrentUser, db: DbSession):
    analytics = analytics_for_user(db, user.id, 30, user.timezone)
    overload = overload_for_user(db, user.id, timezone_name=user.timezone)
    latest = db.scalar(select(BalanceAssessment).where(BalanceAssessment.user_id == user.id).order_by(BalanceAssessment.assessment_date.desc()))
    weakest = None
    if latest:
        scores = {key: getattr(latest, key) for key in BALANCE_LABELS}
        weakest = BALANCE_LABELS[min(scores, key=scores.get)]
    items = [Recommendation(user_id=user.id, **data) for data in generate_recommendations(overload, weakest, analytics["habit_completion_rate"])]
    db.add_all(items)
    db.commit()
    for item in items:
        db.refresh(item)
    return items


@router.get("/recommendations", response_model=list[RecommendationResponse])
def list_recommendations(user: CurrentUser, db: DbSession):
    return db.scalars(select(Recommendation).where(Recommendation.user_id == user.id).order_by(Recommendation.created_at.desc()).limit(30)).all()


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationResponse)
def update_recommendation(recommendation_id: int, payload: RecommendationUpdate, user: CurrentUser, db: DbSession):
    item = db.scalar(select(Recommendation).where(Recommendation.id == recommendation_id, Recommendation.user_id == user.id))
    if not item:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    item.status = payload.status
    db.commit()
    db.refresh(item)
    return item
