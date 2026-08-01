from fastapi.testclient import TestClient


def test_register_login_refresh_and_profile(client: TestClient):
    created = client.post("/api/v1/auth/register", json={
        "email": "person@example.com", "password": "long-enough-password", "name": "Иван Петров",
    })
    assert created.status_code == 201
    tokens = created.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    profile = client.get("/api/v1/auth/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["name"] == "Иван Петров"

    changed = client.patch("/api/v1/auth/me", headers=headers, json={"occupation": "Инженер"})
    assert changed.json()["occupation"] == "Инженер"
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


def test_duplicate_registration_is_rejected(client: TestClient):
    payload = {"email": "same@example.com", "password": "long-enough-password", "name": "Test User"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409
