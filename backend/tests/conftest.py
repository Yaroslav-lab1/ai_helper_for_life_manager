import os
from pathlib import Path

TEST_DB = Path(__file__).parent / "test_axel.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-key-only-with-at-least-32-characters"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["TRUSTED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ["USE_SECURE_AUTH_COOKIES"] = "false"
os.environ["EMAIL_BACKEND"] = "console"
os.environ["YOOKASSA_WEBHOOK_IP_CHECK_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient

from backend.database import Base, engine
from backend.main import app
from backend.services.rate_limit import limiter
from backend.billing.yookassa_client import reset_billing_client


@pytest.fixture(autouse=True)
def fresh_database():
    limiter.clear()
    reset_billing_client()
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    reset_billing_client()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/register", json={
        "email": "test@example.com", "password": "secure-pass-2026", "name": "Test User",
    })
    assert response.status_code == 201
    # Most legacy feature tests exercise AI flows. Give this shared fixture PRO;
    # billing tests register directly when they need to assert the FREE default.
    from datetime import timedelta
    from backend.database import SessionLocal
    from backend.models import UserSubscription
    from backend.services.time import utc_now

    with SessionLocal() as db:
        subscription = db.get(UserSubscription, response.json()["user"]["id"])
        subscription.plan_code = "pro"
        subscription.billing_interval = "monthly"
        subscription.status = "active"
        subscription.current_period_start = utc_now()
        subscription.current_period_end = utc_now() + timedelta(days=30)
        db.commit()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
