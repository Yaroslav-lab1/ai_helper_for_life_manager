from backend.api.deps import CurrentUser, DbSession
from backend.models import UserSettings
from backend.config import settings
from backend.schemas.settings import AIConsentAccept, AIConsentStatus, SettingsResponse, SettingsUpdate
from backend.services.privacy import external_ai_consent_required, has_current_ai_consent
from backend.services.time import utc_now
from fastapi import APIRouter, HTTPException, Response, status

router = APIRouter(prefix="/settings", tags=["Settings"])


def ensure_settings(user: CurrentUser, db: DbSession) -> UserSettings:
    if user.settings:
        return user.settings
    item = UserSettings(user_id=user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=SettingsResponse)
def get_settings(user: CurrentUser, db: DbSession):
    return ensure_settings(user, db)


@router.patch("", response_model=SettingsResponse)
def update_settings(payload: SettingsUpdate, user: CurrentUser, db: DbSession):
    item = ensure_settings(user, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


def consent_status(user: CurrentUser, db: DbSession) -> dict:
    item = ensure_settings(user, db)
    return {
        "required": external_ai_consent_required(),
        "active": has_current_ai_consent(user),
        "policy_version": settings.privacy_policy_version,
        "accepted_at": item.ai_context_consent_at,
        "revoked_at": item.ai_context_consent_revoked_at,
    }


@router.get("/ai-consent", response_model=AIConsentStatus)
def get_ai_consent(user: CurrentUser, db: DbSession):
    return consent_status(user, db)


@router.post("/ai-consent", response_model=AIConsentStatus)
def accept_ai_consent(payload: AIConsentAccept, user: CurrentUser, db: DbSession):
    if payload.policy_version != settings.privacy_policy_version:
        raise HTTPException(
            status_code=409,
            detail="Версия политики конфиденциальности изменилась. Ознакомьтесь с ней повторно.",
        )
    item = ensure_settings(user, db)
    item.ai_context_consent_version = settings.privacy_policy_version
    item.ai_context_consent_at = utc_now()
    item.ai_context_consent_revoked_at = None
    db.commit()
    db.refresh(item)
    return consent_status(user, db)


@router.delete("/ai-consent", response_model=AIConsentStatus)
def revoke_ai_consent(user: CurrentUser, db: DbSession):
    item = ensure_settings(user, db)
    if item.ai_context_consent_at is not None and item.ai_context_consent_revoked_at is None:
        item.ai_context_consent_revoked_at = utc_now()
        db.commit()
        db.refresh(item)
    return consent_status(user, db)
