import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.ai.client import (
    GigaChatLLMClient,
    LLMClient,
    LLMModelNotFoundError,
    LLMUnavailableError,
    MockLLMClient,
    OllamaLLMClient,
)
from backend.ai.factory import create_llm_client, get_llm_client
from backend.ai.goal_planner_service import GoalPlannerService, GoalPlanValidationError
from backend.ai.schemas import goal_plan_response_schema
from backend.database import SessionLocal
from backend.models import AIActionProposal, AIConversation, Goal, GoalPlan, Task, User


def test_llm_factory_selects_mock_ollama_and_gigachat():
    mock_settings = SimpleNamespace(llm_provider="mock")
    with patch("backend.ai.factory.get_settings", return_value=mock_settings):
        assert isinstance(create_llm_client(), MockLLMClient)

    ollama_settings = SimpleNamespace(
        llm_provider="ollama",
        llm_model="qwen3.5:9b",
        ollama_base_url="http://localhost:11434",
        ollama_request_timeout_seconds=120,
    )
    with patch("backend.ai.factory.get_settings", return_value=ollama_settings):
        client = create_llm_client()
    assert isinstance(client, OllamaLLMClient)
    assert client.model == "qwen3.5:9b"

    gigachat_settings = SimpleNamespace(
        llm_provider="gigachat",
        llm_model="GigaChat-2",
        gigachat_authorization_key="secret-key",
        gigachat_scope="GIGACHAT_API_PERS",
        gigachat_base_url="https://api.giga.chat/v1",
        gigachat_oauth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        gigachat_request_timeout_seconds=120,
        gigachat_verify_ssl=True,
        gigachat_ca_bundle_file=None,
    )
    with patch("backend.ai.factory.get_settings", return_value=gigachat_settings):
        client = create_llm_client()
    assert isinstance(client, GigaChatLLMClient)
    assert client.model == "GigaChat-2"
    assert client.scope == "GIGACHAT_API_PERS"


def test_llm_factory_reuses_runtime_client():
    get_llm_client.cache_clear()
    with patch("backend.ai.factory.create_llm_client", return_value=MockLLMClient()) as create:
        first = get_llm_client()
        second = get_llm_client()
    assert first is second
    create.assert_called_once()
    get_llm_client.cache_clear()


def test_ollama_goal_schema_is_flat_and_grammar_compatible():
    schema = goal_plan_response_schema()
    serialized = json.dumps(schema)
    assert "$ref" not in serialized
    assert "$defs" not in serialized
    assert "anyOf" not in serialized
    assert schema["additionalProperties"] is False
    assert "title" in schema["properties"]["milestones"]["items"]["properties"]


def test_gigachat_goal_schema_preserves_array_constraints():
    schema = goal_plan_response_schema(preserve_constraints=True)
    preferred_days = schema["properties"]["schedule_suggestions"]["items"]["properties"]["preferred_days"]
    assert preferred_days["minItems"] == 1
    assert preferred_days["maxItems"] == 7


def test_ollama_status_available_and_model_missing():
    def available(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}]})

    client = OllamaLLMClient("qwen3.5:9b", transport=httpx.MockTransport(available))
    assert asyncio.run(client.status())["available"] is True

    missing = OllamaLLMClient(
        "qwen3.5:9b",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"models": [{"name": "other:latest"}]})),
    )
    with pytest.raises(LLMModelNotFoundError, match="Модель qwen3.5:9b не найдена в Ollama"):
        asyncio.run(missing.status())


def test_ollama_unavailable_and_chat_modes():
    def unavailable(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    client = OllamaLLMClient("qwen3.5:9b", transport=httpx.MockTransport(unavailable))
    with pytest.raises(LLMUnavailableError, match="Локальная нейросеть недоступна"):
        asyncio.run(client.status())

    def responder(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["stream"]:
            body = '\n'.join([
                json.dumps({"message": {"content": "Привет"}, "done": False}, ensure_ascii=False),
                json.dumps({"message": {"content": "!"}, "done": True}, ensure_ascii=False),
            ])
            return httpx.Response(200, text=body)
        return httpx.Response(200, json={"message": {"content": '{"ok":true}'}})

    online = OllamaLLMClient("qwen3.5:9b", transport=httpx.MockTransport(responder))
    complete = asyncio.run(online.chat([{"role": "user", "content": "test"}], response_schema={"type": "object"}))
    assert complete == '{"ok":true}'

    async def collect() -> str:
        stream = await online.chat([{"role": "user", "content": "test"}], stream=True)
        assert not isinstance(stream, str)
        return "".join([chunk async for chunk in stream])

    assert asyncio.run(collect()) == "Привет!"


def test_gigachat_oauth_status_complete_stream_and_token_refresh():
    oauth_calls = 0
    now = [1_800_000_000.0]

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal oauth_calls
        if request.url.host == "ngw.devices.sberbank.ru":
            oauth_calls += 1
            assert request.url.path == "/api/v2/oauth"
            assert request.headers["Authorization"] == "Basic secret-key"
            assert request.headers["RqUID"]
            assert parse_qs(request.content.decode()) == {"scope": ["GIGACHAT_API_PERS"]}
            return httpx.Response(
                200,
                json={
                    "access_token": f"access-{oauth_calls}",
                    "expires_at": int((now[0] + 120) * 1000),
                },
            )

        assert request.url.host == "api.giga.chat"
        assert request.headers["Authorization"] == f"Bearer access-{oauth_calls}"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "GigaChat"}]})

        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "GigaChat-2"
        if payload["stream"]:
            body = "\n\n".join([
                'data: {"choices":[{"delta":{"content":"Привет"}}]}',
                'data: {"choices":[{"delta":{"content":"!"}}]}',
                "data: [DONE]",
            ])
            return httpx.Response(200, text=body)
        assert payload["response_format"] == {
            "type": "json_schema",
            "schema": {"type": "object"},
            "strict": True,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":true}'}}]},
        )

    client = GigaChatLLMClient(
        "GigaChat-2",
        "secret-key",
        transport=httpx.MockTransport(responder),
        clock=lambda: now[0],
    )
    assert asyncio.run(client.status())["provider"] == "gigachat"
    complete = asyncio.run(
        client.chat(
            [{"role": "user", "content": "test"}],
            response_schema={"type": "object"},
        )
    )
    assert complete == '{"ok":true}'

    async def collect() -> str:
        stream = await client.chat([{"role": "user", "content": "test"}], stream=True)
        assert not isinstance(stream, str)
        return "".join([chunk async for chunk in stream])

    assert asyncio.run(collect()) == "Привет!"
    assert oauth_calls == 1

    now[0] += 70
    assert asyncio.run(client.status())["available"] is True
    assert oauth_calls == 2


def test_gigachat_requires_authorization_key():
    client = GigaChatLLMClient("GigaChat-2", "")
    with pytest.raises(LLMUnavailableError, match="GIGACHAT_AUTHORIZATION_KEY"):
        asyncio.run(client.status())


def test_gigachat_serializes_generation_requests():
    active = 0
    max_active = 0

    async def responder(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active
        assert request.url.path == "/v1/chat/completions"
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = GigaChatLLMClient(
        "GigaChat-2",
        "secret-key",
        transport=httpx.MockTransport(responder),
        clock=lambda: 1_800_000_000,
    )
    client._access_token = "access"
    client._access_token_expires_at = 1_800_001_000

    async def generate_twice():
        return await asyncio.gather(
            client.chat([{"role": "user", "content": "first"}]),
            client.chat([{"role": "user", "content": "second"}]),
        )

    assert asyncio.run(generate_twice()) == ["ok", "ok"]
    assert max_active == 1


def test_streaming_chat_conversations_and_user_isolation(client: TestClient, auth: dict[str, str]):
    response = client.post("/api/v1/ai/chat", headers=auth, json={"message": "Помоги выбрать приоритет"})
    assert response.status_code == 200
    assert '"event": "chunk"' in response.text
    assert '"event": "done"' in response.text

    conversations = client.get("/api/v1/ai/conversations", headers=auth).json()
    assert len(conversations) == 1
    conversation_id = conversations[0]["id"]
    messages = client.get(f"/api/v1/ai/conversations/{conversation_id}/messages", headers=auth).json()
    assert [item["role"] for item in messages] == ["user", "assistant"]

    other = client.post("/api/v1/auth/register", json={
        "email": "other@example.com", "password": "secure-pass-2026", "name": "Other User",
    }).json()
    other_auth = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/api/v1/ai/conversations/{conversation_id}/messages", headers=other_auth).status_code == 404
    assert client.delete(f"/api/v1/ai/conversations/{conversation_id}", headers=auth).status_code == 204


def test_goal_plan_generation_regeneration_apply_and_cancel(client: TestClient, auth: dict[str, str]):
    goal = client.post("/api/v1/goals", headers=auth, json={
        "title": "Выучить английский до B2",
        "description": "Сейчас уровень A2, доступно четыре часа в неделю",
        "horizon": "year",
        "target_date": (date.today() + timedelta(days=180)).isoformat(),
    }).json()
    first = client.get(f"/api/v1/goals/{goal['id']}/plan", headers=auth)
    assert first.status_code == 200
    assert first.json()["version"] == 1
    assert first.json()["plan"]["milestones"]
    assert first.json()["plan"]["tasks"]
    assert first.json()["plan"]["habits"]

    regenerated = client.post(
        f"/api/v1/goals/{goal['id']}/regenerate-plan",
        headers=auth,
        json={"reason": "Доступное время изменилось"},
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["version"] == 2
    assert regenerated.json()["diff"]["reason"] == "Доступное время изменилось"

    assert client.post(
        f"/api/v1/goals/{goal['id']}/plan/apply", headers=auth, json={"confirm": False}
    ).status_code == 409
    applied = client.post(
        f"/api/v1/goals/{goal['id']}/plan/apply",
        headers=auth,
        json={"confirm": True, "components": ["milestones", "tasks", "habits"]},
    )
    assert applied.status_code == 200
    assert applied.json()["created"]["milestones"] == 1
    assert applied.json()["created"]["tasks"] == 1
    assert applied.json()["created"]["habits"] == 1

    second = client.post("/api/v1/goals", headers=auth, json={
        "title": "Подготовить доклад",
        "horizon": "quarter",
        "target_date": (date.today() + timedelta(days=90)).isoformat(),
    }).json()
    assert client.post(f"/api/v1/goals/{second['id']}/plan/cancel", headers=auth).status_code == 204
    cancelled = client.get(f"/api/v1/goals/{second['id']}/plan", headers=auth).json()
    assert cancelled["status"] == "cancelled"

    other = client.post("/api/v1/auth/register", json={
        "email": "plan-other@example.com", "password": "secure-pass-2026", "name": "Plan Other",
    }).json()
    other_auth = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/api/v1/goals/{goal['id']}/plan", headers=other_auth).status_code == 404


def test_invalid_goal_json_is_retried_once_and_never_saved(client: TestClient, auth: dict[str, str]):
    class InvalidClient(LLMClient):
        calls = 0

        async def status(self):
            return {"available": True}

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            self.calls += 1
            return "not-json"

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "test@example.com"))
        goal = Goal(
            user_id=user.id,
            title="Изолированная цель",
            horizon="quarter",
            target_date=date.today() + timedelta(days=60),
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        invalid = InvalidClient()
        planner = GoalPlannerService(invalid)
        with pytest.raises(GoalPlanValidationError):
            asyncio.run(planner.generate(db, user, goal))
        assert invalid.calls == 2
        assert db.scalar(select(GoalPlan).where(GoalPlan.goal_id == goal.id)) is None
    finally:
        db.close()


def test_goal_plan_derives_missing_weekly_plan_from_schedule_suggestions():
    raw_plan = MockLLMClient._goal_plan()
    raw_plan["weekly_plan"] = []
    goal = SimpleNamespace(target_date=date.today() + timedelta(days=180))

    plan = GoalPlannerService._validate(json.dumps(raw_plan, ensure_ascii=False), goal)

    assert [(item.day_of_week, item.action) for item in plan.weekly_plan] == [
        ("monday", "Фокус на цели"),
        ("wednesday", "Фокус на цели"),
        ("friday", "Фокус на цели"),
    ]


def test_goal_plan_repairs_empty_schedule_days_locally():
    raw_plan = MockLLMClient._goal_plan()
    raw_plan["schedule_suggestions"][0]["preferred_days"] = []
    goal = SimpleNamespace(target_date=date.today() + timedelta(days=180))

    plan = GoalPlannerService._validate(json.dumps(raw_plan, ensure_ascii=False), goal)

    assert plan.schedule_suggestions[0].preferred_days == ["monday"]


def test_action_proposal_requires_confirmation(client: TestClient, auth: dict[str, str]):
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "test@example.com"))
        conversation = AIConversation(user_id=user.id, title="Действие")
        db.add(conversation)
        db.flush()
        proposal = AIActionProposal(
            user_id=user.id,
            conversation_id=conversation.id,
            type="task_action_proposal",
            title="Добавить тренировку",
            description="Создать задачу на тренировку",
            payload=json.dumps({"title": "Тренировка", "estimate_minutes": 45}),
        )
        db.add(proposal)
        db.commit()
        proposal_id = proposal.id
        assert db.scalar(select(Task).where(Task.user_id == user.id, Task.title == "Тренировка")) is None
    finally:
        db.close()

    confirmed = client.post(f"/api/v1/ai/action-proposals/{proposal_id}/confirm", headers=auth)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert any(item["title"] == "Тренировка" for item in client.get("/api/v1/tasks", headers=auth).json())
