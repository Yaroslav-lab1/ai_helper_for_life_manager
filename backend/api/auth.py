from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, DbSession
from backend.config import settings
from backend.models import User, UserSettings
from backend.schemas.auth import (
    EmailRequest,
    LoginRequest,
    MessageResponse,
    OneTimeTokenRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from backend.services.email import send_password_reset_email, send_verification_email
from backend.services.rate_limit import enforce_auth_limit, limiter
from backend.services.security import (
    consume_one_time_token,
    create_one_time_token,
    hash_password,
    issue_session,
    revoke_all_sessions,
    revoke_session,
    rotate_refresh_session,
    token_digest,
    verify_password,
)
from backend.services.time import utc_now

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)
GENERIC_EMAIL_MESSAGE = "If the account exists, an email will be sent."


def _set_refresh_cookie(response: Response, refresh: str) -> None:
    if settings.use_secure_auth_cookies:
        response.set_cookie(
            key=settings.refresh_cookie_name,
            value=refresh,
            max_age=settings.refresh_token_days * 86400,
            httponly=True,
            secure=True,
            samesite=settings.refresh_cookie_samesite,
            path="/api/v1/auth",
        )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.use_secure_auth_cookies,
        samesite=settings.refresh_cookie_samesite,
        path="/api/v1/auth",
    )


def _token_pair(user: User, access: str, refresh: str, response: Response) -> TokenPair:
    _set_refresh_cookie(response, refresh)
    return TokenPair(
        access_token=access,
        refresh_token=None if settings.use_secure_auth_cookies else refresh,
        expires_in=settings.access_token_minutes * 60,
        user=UserResponse.model_validate(user),
    )


def _new_token_pair(db: DbSession, user: User, response: Response) -> TokenPair:
    access, refresh, _ = issue_session(db, user)
    db.commit()
    return _token_pair(user, access, refresh, response)


def _send_safely(callback, email: str, token: str) -> None:
    try:
        callback(email, token)
    except Exception as exc:
        logger.warning("Email delivery failed (%s)", type(exc).__name__)


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, request: Request, response: Response, db: DbSession):
    enforce_auth_limit(request, "register", payload.email)
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="User with this email already exists")
    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        name=payload.name.strip(),
        timezone=payload.timezone,
    )
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    verification_token = create_one_time_token(db, user, "verify_email")
    pair = _new_token_pair(db, user, response)
    _send_safely(send_verification_email, user.email, verification_token)
    return pair


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, response: Response, db: DbSession):
    keys = enforce_auth_limit(request, "login", payload.email, login=True)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    for key in keys:
        limiter.reset(key)
    return _new_token_pair(db, user, response)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, request: Request, response: Response, db: DbSession):
    refresh_value = payload.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    if not refresh_value:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    enforce_auth_limit(request, "refresh", token_digest(refresh_value)[:24])
    try:
        user, access, refresh_token = rotate_refresh_session(db, refresh_value)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return _token_pair(user, access, refresh_token, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, user: CurrentUser, db: DbSession):
    session_id = getattr(request.state, "auth_session_id", None)
    if session_id:
        revoke_session(db, user.id, session_id)
    result = Response(status_code=204)
    _clear_refresh_cookie(result)
    return result


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(response: Response, user: CurrentUser, db: DbSession):
    revoke_all_sessions(db, user.id)
    result = Response(status_code=204)
    _clear_refresh_cookie(result)
    return result


@router.post("/forgot-password", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: EmailRequest, request: Request, db: DbSession):
    enforce_auth_limit(request, "forgot-password", payload.email)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is not None:
        token = create_one_time_token(db, user, "password_reset")
        _send_safely(send_password_reset_email, user.email, token)
    return {"message": GENERIC_EMAIL_MESSAGE}


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: PasswordResetRequest, request: Request, db: DbSession):
    enforce_auth_limit(request, "reset-password", token_digest(payload.token)[:24])
    try:
        user = consume_one_time_token(db, payload.token, "password_reset")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    revoke_all_sessions(db, user.id)
    return {"message": "Password changed. Sign in again."}


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(payload: OneTimeTokenRequest, request: Request, db: DbSession):
    enforce_auth_limit(request, "verify-email", token_digest(payload.token)[:24])
    try:
        user = consume_one_time_token(db, payload.token, "verify_email")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    if user.email_verified_at is None:
        user.email_verified_at = utc_now()
        db.commit()
    return {"message": "Email verified."}


@router.post("/request-email-verification", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def request_email_verification(request: Request, user: CurrentUser, db: DbSession):
    enforce_auth_limit(request, "request-verification", user.email)
    if user.email_verified_at is None:
        token = create_one_time_token(db, user, "verify_email")
        _send_safely(send_verification_email, user.email, token)
    return {"message": GENERIC_EMAIL_MESSAGE}


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: PasswordChangeRequest, user: CurrentUser, db: DbSession):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid current password")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    revoke_all_sessions(db, user.id)
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
def profile(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserResponse)
def update_profile(payload: UserUpdate, user: CurrentUser, db: DbSession):
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user
