from __future__ import annotations

from fastapi import HTTPException, status

from backend.config import settings
from backend.models import User


def external_ai_consent_required() -> bool:
    return settings.llm_provider.lower() == "gigachat"


def has_current_ai_consent(user: User) -> bool:
    current = user.settings
    return bool(
        current
        and current.ai_context_consent_at
        and current.ai_context_consent_revoked_at is None
        and current.ai_context_consent_version == settings.privacy_policy_version
    )


def require_ai_context_consent(user: User) -> None:
    if external_ai_consent_required() and not has_current_ai_consent(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Перед отправкой персонального контекста в GigaChat необходимо явно дать согласие.",
        )
