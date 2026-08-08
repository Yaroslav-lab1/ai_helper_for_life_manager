import os
from pathlib import Path

TEST_DB = Path(__file__).parent / "test_axel.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "test-key-only"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["TRUSTED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ["USE_SECURE_AUTH_COOKIES"] = "false"
os.environ["EMAIL_BACKEND"] = "console"

import pytest
from fastapi.testclient import TestClient

from backend.database import Base, engine
from backend.main import app
from backend.services.rate_limit import limiter


@pytest.fixture(autouse=True)
def fresh_database():
    limiter.clear()
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
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
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
