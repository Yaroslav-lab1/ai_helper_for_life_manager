from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient


def test_tasks_events_and_dashboard(client: TestClient, auth: dict[str, str]):
    now = datetime.now().replace(microsecond=0)
    task = client.post("/api/v1/tasks", headers=auth, json={
        "title": "Важная задача", "due_at": (now + timedelta(hours=2)).isoformat(),
        "priority": "high", "estimate_minutes": 45, "energy": "medium",
    })
    assert task.status_code == 201
    task_id = task.json()["id"]
    assert client.patch(f"/api/v1/tasks/{task_id}", headers=auth, json={"status": "done"}).json()["completed_at"]

    event = client.post("/api/v1/events", headers=auth, json={
        "title": "Фокус", "start_at": now.isoformat(), "end_at": (now + timedelta(hours=1)).isoformat(),
        "category": "focus", "color": "#7257E8",
    })
    assert event.status_code == 201
    dashboard = client.get("/api/v1/dashboard", headers=auth)
    assert dashboard.status_code == 200
    assert dashboard.json()["events_today"][0]["title"] == "Фокус"


def test_goal_decomposition_and_progress(client: TestClient, auth: dict[str, str]):
    goal = client.post("/api/v1/goals", headers=auth, json={
        "title": "Запустить проект", "horizon": "quarter",
        "target_date": (date.today() + timedelta(days=60)).isoformat(),
    }).json()
    steps = client.post(f"/api/v1/goals/{goal['id']}/decompose", headers=auth, json={"context": "по вечерам"})
    assert steps.status_code == 200
    assert len(steps.json()) == 6
    first = steps.json()[0]
    toggled = client.patch(f"/api/v1/goals/{goal['id']}/steps/{first['id']}", headers=auth, json={"is_completed": True})
    assert toggled.status_code == 200
    current = client.get("/api/v1/goals", headers=auth).json()[0]
    assert current["progress"] == 17


def test_habit_streak_and_balance_analytics(client: TestClient, auth: dict[str, str]):
    habit = client.post("/api/v1/habits", headers=auth, json={
        "title": "Прогулка", "emoji": "🌿", "target_per_week": 7, "color": "#00B894",
    }).json()
    assert client.post(f"/api/v1/habits/{habit['id']}/checkins", headers=auth, json={"checkin_date": date.today().isoformat()}).status_code == 201
    current = client.get("/api/v1/habits", headers=auth).json()[0]
    assert current["completed_today"] is True
    assert current["current_streak"] == 1

    scores = {key: 7 for key in ["health", "career", "finance", "relationships", "growth", "recreation", "environment", "contribution"]}
    assert client.post("/api/v1/balance", headers=auth, json=scores).status_code == 201
    analytics = client.get("/api/v1/analytics", headers=auth).json()
    assert analytics["balance_score"] == 7.0


def test_chat_stream_is_persisted(client: TestClient, auth: dict[str, str]):
    response = client.post("/api/v1/chat/stream", headers=auth, json={"message": "Помоги спланировать сегодня", "selected_date": date.today().isoformat()})
    assert response.status_code == 200
    assert date.today().strftime("%d.%m.%Y") in response.text
    history = client.get("/api/v1/chat/history", headers=auth).json()
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert client.delete("/api/v1/chat/history", headers=auth).status_code == 204
    assert client.get("/api/v1/chat/history", headers=auth).json() == []


def test_calendar_range_and_energy_forecast(client: TestClient, auth: dict[str, str]):
    today = datetime.combine(date.today(), datetime.min.time())
    tomorrow = today + timedelta(days=1)
    for title, start in [("Сегодня", today + timedelta(hours=10)), ("Завтра", tomorrow + timedelta(hours=11))]:
        response = client.post("/api/v1/events", headers=auth, json={
            "title": title, "start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat(),
            "category": "work", "color": "#5B9DF5",
        })
        assert response.status_code == 201

    ranged = client.get("/api/v1/events", headers=auth, params={
        "start": today.isoformat(), "end": (today + timedelta(hours=23, minutes=59)).isoformat(),
    })
    assert ranged.status_code == 200
    assert [item["title"] for item in ranged.json()] == ["Сегодня"]

    energy = client.get("/api/v1/energy", headers=auth, params={"date": date.today().isoformat()})
    assert energy.status_code == 200
    payload = energy.json()
    assert payload["date"] == date.today().isoformat()
    assert len(payload["points"]) == 18
    assert {point["kind"] for point in payload["points"]} <= {"peak", "steady", "dip", "recovery"}
    assert payload["recommendations"]
    assert client.get("/api/v1/energy").status_code == 401
