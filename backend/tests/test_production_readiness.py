from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.config import Settings, settings
from backend.database import SessionLocal
from backend.database.seed import seed_demo
from backend.models import AuthSession, Event, Task, User
from backend.services.rate_limit import limiter
from backend.services.time import day_bounds_utc


def register(client: TestClient, email: str = "security@example.com", timezone: str = "Europe/Moscow"):
    return client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "long-secure-password",
        "name": "Security User",
        "timezone": timezone,
    })


def test_refresh_rotation_reuse_and_logout_revoke_sessions(client: TestClient):
    created = register(client)
    assert created.status_code == 201
    first = created.json()
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    second = rotated.json()

    assert client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401

    fresh = client.post("/api/v1/auth/login", json={
        "email": "security@example.com",
        "password": "long-secure-password",
    }).json()
    headers = {"Authorization": f"Bearer {fresh['access_token']}"}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_production_refresh_cookie_is_http_only_secure_and_not_exposed_in_json(client: TestClient):
    previous = settings.use_secure_auth_cookies
    settings.use_secure_auth_cookies = True
    try:
        created = register(client)
        assert created.status_code == 201
        assert created.json()["refresh_token"] is None
        cookie = created.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "secure" in cookie
        assert "samesite=lax" in cookie
        assert "path=/api/v1/auth" in cookie
    finally:
        settings.use_secure_auth_cookies = previous


def test_password_reset_is_single_use_uniform_and_revokes_all_sessions(client: TestClient):
    created = register(client)
    old_headers = {"Authorization": f"Bearer {created.json()['access_token']}"}
    captured: list[str] = []
    with patch("backend.api.auth.send_password_reset_email", side_effect=lambda email, token: captured.append(token)):
        existing = client.post("/api/v1/auth/forgot-password", json={"email": "security@example.com"})
        missing = client.post("/api/v1/auth/forgot-password", json={"email": "missing@example.com"})
    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json()
    assert len(captured) == 1

    reset = client.post("/api/v1/auth/reset-password", json={
        "token": captured[0],
        "new_password": "a-new-secure-password",
    })
    assert reset.status_code == 200
    assert client.post("/api/v1/auth/reset-password", json={
        "token": captured[0],
        "new_password": "another-secure-password",
    }).status_code == 400
    assert client.get("/api/v1/auth/me", headers=old_headers).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": "security@example.com",
        "password": "long-secure-password",
    }).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": "security@example.com",
        "password": "a-new-secure-password",
    }).status_code == 200


def test_email_verification_token_is_hashed_and_single_use(client: TestClient):
    captured: list[str] = []
    with patch("backend.api.auth.send_verification_email", side_effect=lambda email, token: captured.append(token)):
        created = register(client)
    assert created.status_code == 201
    assert created.json()["user"]["email_verified"] is False
    assert len(captured) == 1

    verified = client.post("/api/v1/auth/verify-email", json={"token": captured[0]})
    assert verified.status_code == 200
    assert client.post("/api/v1/auth/verify-email", json={"token": captured[0]}).status_code == 400
    headers = {"Authorization": f"Bearer {created.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["email_verified"] is True

    db = SessionLocal()
    try:
        from backend.models import OneTimeToken
        stored = db.scalar(select(OneTimeToken))
        assert stored is not None
        assert captured[0] not in stored.token_hash
        assert len(stored.token_hash) == 64
    finally:
        db.close()


def test_login_rate_limit_blocks_bruteforce_by_identifier_and_ip(client: TestClient):
    register(client)
    original = settings.login_rate_limit_attempts
    settings.login_rate_limit_attempts = 2
    limiter.clear()
    try:
        payload = {"email": "security@example.com", "password": "wrong-password"}
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401
        limited = client.post("/api/v1/auth/login", json=payload)
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1
    finally:
        settings.login_rate_limit_attempts = original
        limiter.clear()


def test_timezone_day_bounds_dst_and_naive_api_values_are_normalized(client: TestClient):
    spring_start, spring_end = day_bounds_utc(date(2026, 3, 8), "America/New_York")
    autumn_start, autumn_end = day_bounds_utc(date(2026, 11, 1), "America/New_York")
    assert (spring_end - spring_start).total_seconds() == 23 * 3600
    assert (autumn_end - autumn_start).total_seconds() == 25 * 3600

    created = register(client, timezone="America/New_York").json()
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    event = client.post("/api/v1/events", headers=headers, json={
        "title": "DST boundary",
        "start_at": "2026-03-08T00:30:00",
        "end_at": "2026-03-08T01:30:00",
        "category": "personal",
        "color": "#6C5CE7",
    })
    assert event.status_code == 201
    assert datetime.fromisoformat(event.json()["start_at"]).astimezone(UTC) == datetime(2026, 3, 8, 5, 30, tzinfo=UTC)

    local_now = datetime(2026, 3, 8, 1, 0, tzinfo=datetime.now().astimezone().tzinfo)
    with patch("backend.services.analytics.now_for", return_value=datetime(2026, 3, 8, 1, 0, tzinfo=__import__("zoneinfo").ZoneInfo("America/New_York"))):
        dashboard = client.get("/api/v1/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["events_today"][0]["title"] == "DST boundary"


def test_demo_seed_is_idempotent_refreshes_dates_and_preserves_unmanaged_data():
    previous = (settings.enable_demo_seed, settings.demo_password, settings.demo_email)
    settings.enable_demo_seed = True
    settings.demo_password = "development-demo-password"
    settings.demo_email = "demo-seed@example.com"
    try:
        with patch("backend.database.seed.today_for", return_value=date(2026, 7, 28)):
            seed_demo()
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.email == settings.demo_email))
            assert user is not None
            db.add(Task(user_id=user.id, title="Пользовательская задача", priority="low"))
            db.commit()
        finally:
            db.close()

        with patch("backend.database.seed.today_for", return_value=date(2026, 7, 30)):
            seed_demo()
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.email == settings.demo_email))
            assert db.scalar(select(func.count()).select_from(Event).where(Event.user_id == user.id)) == 5
            assert db.scalar(select(func.count()).select_from(Task).where(Task.user_id == user.id)) == 7
            focus = db.scalar(select(Event).where(Event.user_id == user.id, Event.demo_seed_key == "morning-focus"))
            assert focus.start_at == datetime(2026, 7, 30, 6, 0, tzinfo=UTC)
            assert db.scalar(select(Task).where(Task.user_id == user.id, Task.title == "Пользовательская задача"))
        finally:
            db.close()
    finally:
        settings.enable_demo_seed, settings.demo_password, settings.demo_email = previous


def test_export_is_user_scoped_and_delete_requires_password(client: TestClient):
    first = register(client, "first@example.com").json()
    second = register(client, "second@example.com").json()
    first_headers = {"Authorization": f"Bearer {first['access_token']}"}
    second_headers = {"Authorization": f"Bearer {second['access_token']}"}
    client.post("/api/v1/tasks", headers=first_headers, json={"title": "First private task"})
    client.post("/api/v1/tasks", headers=second_headers, json={"title": "Second private task"})

    exported = client.get("/api/v1/account/export", headers=first_headers)
    assert exported.status_code == 200
    serialized = exported.text
    assert "First private task" in serialized
    assert "Second private task" not in serialized
    assert "hashed_password" not in serialized
    assert "attachment" in exported.headers["content-disposition"]

    assert client.request("DELETE", "/api/v1/account", headers=first_headers, json={
        "password": "wrong-password",
        "confirmation": "DELETE",
    }).status_code == 401
    assert client.request("DELETE", "/api/v1/account", headers=first_headers, json={
        "password": "long-secure-password",
        "confirmation": "DELETE",
    }).status_code == 204
    assert client.get("/api/v1/auth/me", headers=first_headers).status_code == 401


def test_gigachat_consent_is_versioned_enforced_and_revocable(client: TestClient):
    created = register(client).json()
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    previous = settings.llm_provider
    settings.llm_provider = "gigachat"
    try:
        blocked = client.post("/api/v1/ai/chat", headers=headers, json={"message": "Мой план"})
        assert blocked.status_code == 403
        assert "согласие" in blocked.json()["detail"]
        consent = client.get("/api/v1/settings/ai-consent", headers=headers).json()
        assert consent["required"] is True and consent["active"] is False
        assert client.post("/api/v1/settings/ai-consent", headers=headers, json={
            "accepted": True,
            "policy_version": "old",
        }).status_code == 409
        accepted = client.post("/api/v1/settings/ai-consent", headers=headers, json={
            "accepted": True,
            "policy_version": consent["policy_version"],
        })
        assert accepted.status_code == 200
        assert accepted.json()["active"] is True
        revoked = client.delete("/api/v1/settings/ai-consent", headers=headers)
        assert revoked.json()["active"] is False
        assert client.post("/api/v1/ai/chat", headers=headers, json={"message": "Мой план"}).status_code == 403
    finally:
        settings.llm_provider = previous


def test_production_configuration_rejects_defaults_and_accepts_safe_values():
    unsafe = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://axel:axel@db/axel",
        secret_key="change-me-in-production",
        domain="example.com",
        cors_origins="https://example.com",
        email_backend="smtp",
        smtp_host="smtp.example.com",
        email_from="noreply@example.com",
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        unsafe.validate_runtime()

    copied_example = Settings(
        _env_file=None,
        environment="production",
        database_url=(
            "postgresql+psycopg://axel:"
            "replace-with-a-unique-random-database-password@db/axel"
        ),
        secret_key="development-only-change-before-production",
        domain="example.com",
        trusted_hosts="example.com",
        cors_origins="https://example.com",
        email_backend="smtp",
        smtp_host="smtp.example.com",
        email_from="noreply@example.com",
        use_secure_auth_cookies=True,
    )
    with pytest.raises(RuntimeError) as copied_error:
        copied_example.validate_runtime()
    assert "SECRET_KEY" in str(copied_error.value)
    assert "PostgreSQL password" in str(copied_error.value)

    safe = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://axel:unique-random-db-password@db/axel",
        secret_key="a-unique-random-secret-key-with-more-than-32-characters",
        domain="example.com",
        trusted_hosts="example.com",
        cors_origins="https://example.com",
        email_backend="smtp",
        smtp_host="smtp.example.com",
        email_from="noreply@example.com",
        use_secure_auth_cookies=True,
        llm_provider="ollama",
    )
    safe.validate_runtime()
