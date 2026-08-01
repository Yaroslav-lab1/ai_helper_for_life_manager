from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import AuthSession, OneTimeToken, User
from backend.services.time import utc_now

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_token(
    user_id: int,
    token_type: str,
    *,
    session_id: int | None = None,
    jti: str | None = None,
    family_id: str | None = None,
) -> str:
    now = utc_now()
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    payload: dict[str, object] = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now.timestamp(),
        "exp": now + lifetime,
    }
    if session_id is not None:
        payload["sid"] = session_id
    if jti is not None:
        payload["jti"] = jti
    if family_id is not None:
        payload["family"] = family_id
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_claims(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("type") != expected_type:
            raise InvalidTokenError("Unexpected token type")
        int(payload["sub"])
        return payload
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise ValueError("Invalid or expired token") from exc


def decode_token(token: str, expected_type: str) -> int:
    return int(decode_claims(token, expected_type)["sub"])


def issue_session(
    db: Session, user: User, *, family_id: str | None = None
) -> tuple[str, str, AuthSession]:
    now = utc_now()
    jti = secrets.token_urlsafe(32)
    family_id = family_id or uuid4().hex
    auth_session = AuthSession(
        user_id=user.id,
        family_id=family_id,
        token_hash=token_digest(jti),
        expires_at=now + timedelta(days=settings.refresh_token_days),
    )
    db.add(auth_session)
    db.flush()
    access = create_token(user.id, "access", session_id=auth_session.id)
    refresh = create_token(
        user.id,
        "refresh",
        session_id=auth_session.id,
        jti=jti,
        family_id=family_id,
    )
    return access, refresh, auth_session


def rotate_refresh_session(db: Session, refresh_token: str) -> tuple[User, str, str]:
    claims = decode_claims(refresh_token, "refresh")
    user_id = int(claims["sub"])
    session_id = int(claims.get("sid") or 0)
    family_id = str(claims.get("family") or "")
    jti = str(claims.get("jti") or "")
    if not session_id or not family_id or not jti:
        raise ValueError("Invalid or expired token")
    current = db.scalar(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.family_id == family_id,
            AuthSession.token_hash == token_digest(jti),
        )
    )
    now = utc_now()
    if current is None or current.revoked_at is not None or current.expires_at <= now:
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
        raise ValueError("Refresh token reuse detected; session family revoked")
    user = db.get(User, user_id)
    if user is None:
        raise ValueError("Invalid or expired token")
    current.revoked_at = now
    current.last_used_at = now
    access, refresh, replacement = issue_session(db, user, family_id=family_id)
    db.flush()
    current.replaced_by_id = replacement.id
    db.commit()
    return user, access, refresh


def revoke_session(db: Session, user_id: int, session_id: int) -> None:
    item = db.scalar(
        select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user_id)
    )
    if item is not None and item.revoked_at is None:
        item.revoked_at = utc_now()
        db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    now = utc_now()
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    user = db.get(User, user_id)
    if user is not None:
        user.sessions_revoked_at = now
    db.commit()


def create_one_time_token(db: Session, user: User, purpose: str) -> str:
    now = utc_now()
    db.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == user.id,
            OneTimeToken.purpose == purpose,
            OneTimeToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw = secrets.token_urlsafe(32)
    db.add(
        OneTimeToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=token_digest(raw),
            expires_at=now + timedelta(minutes=settings.email_token_minutes),
        )
    )
    db.commit()
    return raw


def consume_one_time_token(db: Session, raw: str, purpose: str) -> User:
    now = utc_now()
    item = db.scalar(
        select(OneTimeToken).where(
            OneTimeToken.token_hash == token_digest(raw),
            OneTimeToken.purpose == purpose,
            OneTimeToken.used_at.is_(None),
            OneTimeToken.expires_at > now,
        )
    )
    if item is None:
        raise ValueError("Invalid or expired token")
    user = db.get(User, item.user_id)
    if user is None:
        raise ValueError("Invalid or expired token")
    item.used_at = now
    db.commit()
    return user
