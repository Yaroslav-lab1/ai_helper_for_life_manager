from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AuthSession, User
from backend.services.security import decode_claims
from backend.services.time import utc_now

bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials:
        raise unauthorized
    try:
        claims = decode_claims(credentials.credentials, "access")
        user_id = int(claims["sub"])
    except ValueError:
        raise unauthorized
    user = db.get(User, user_id)
    if not user:
        raise unauthorized
    issued_at = datetime.fromtimestamp(float(claims["iat"]), UTC)
    if user.sessions_revoked_at and issued_at <= user.sessions_revoked_at:
        raise unauthorized
    session_id = int(claims.get("sid") or 0)
    if session_id:
        auth_session = db.get(AuthSession, session_id)
        if (
            auth_session is None
            or auth_session.user_id != user.id
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= utc_now()
        ):
            raise unauthorized
        request.state.auth_session_id = session_id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
