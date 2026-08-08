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
from backend.ai.chat_service import ChatService
from backend.ai.context_service import UserContextService
from backend.ai.factory import create_llm_client, get_llm_client
from backend.ai.goal_planner_service import GoalPlannerService, GoalPlanValidationError
from backend.ai.schemas import goal_plan_response_schema
from backend.database import SessionLocal
from backend.models import AIActionProposal, AIConversation, AIMessage, Event, Goal, GoalPlan, Task, User


def test_llm_factory_selects_mock_ollama_and_gigachat():
    mock_settings = SimpleNamespace(llm_provider="mock", environment="test")
    with patch("backend.ai.factory.get_settings", return_value=mock_settings):
        assert isinstance(create_llm_client(), MockLLMClient)

    with patch(
        "backend.ai.factory.get_settings",
        return_value=SimpleNamespace(llm_provider="mock", environment="development"),
    ):
        with pytest.raises(ValueError, match="только в автоматических тестах"):
            create_llm_client()

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


def test_gigachat_empty_stream_retries_with_provider_completion():
    calls: list[dict] = []

    def responder(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if payload["stream"]:
            return httpx.Response(
                200,
                headers={"x-request-id": "empty-stream-test"},
                text="\n\n".join([
                    'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}',
                    "data: [DONE]",
                ]),
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Ответ GigaChat после повторного запроса"}}]},
        )

    client = GigaChatLLMClient(
        "GigaChat-2",
        "secret-key",
        transport=httpx.MockTransport(responder),
        clock=lambda: 1_800_000_000,
    )
    client._access_token = "access"
    client._access_token_expires_at = 1_800_001_000

    async def collect() -> str:
        stream = await client.chat([
            {"role": "system", "content": "Ответь по контексту"},
            {"role": "user", "content": "Старый вопрос"},
            {"role": "assistant", "content": "Старый ответ"},
            {"role": "user", "content": "с 14 до 17"},
        ], stream=True)
        assert not isinstance(stream, str)
        return "".join([chunk async for chunk in stream])

    assert asyncio.run(collect()) == "Ответ GigaChat после повторного запроса"
    assert [payload["stream"] for payload in calls] == [True, False]
    assert [message["role"] for message in calls[1]["messages"]] == ["system", "user"]
    assert "Старый вопрос" not in calls[1]["messages"][-1]["content"]
    assert "Обязательно верни непустой ответ" in calls[1]["messages"][-1]["content"]


def test_gigachat_empty_completion_retries_for_action_classifier():
    calls: list[dict] = []

    def responder(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"has_proposal":false}'}}]},
        )

    client = GigaChatLLMClient(
        "GigaChat-2",
        "secret-key",
        transport=httpx.MockTransport(responder),
        clock=lambda: 1_800_000_000,
    )
    client._access_token = "access"
    client._access_token_expires_at = 1_800_001_000

    result = asyncio.run(client.chat([
        {"role": "system", "content": "Верни JSON"},
        {"role": "user", "content": "Определи действие"},
    ]))

    assert result == '{"has_proposal":false}'
    assert len(calls) == 2
    assert "Обязательно верни непустой ответ" in calls[1]["messages"][-1]["content"]


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


def test_safe_context_marks_energy_as_calculated_forecast(auth: dict[str, str]):
    del auth
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "test@example.com"))
        context = UserContextService().build(db, user, "Что порекомендуешь?", date(2031, 5, 17))
        assert "energy" not in context
        assert context["energy_forecast"]["source"] == "calculated_by_axel_one_not_user_reported"
        assert context["selected_date"] == "2031-05-17"
    finally:
        db.close()


def test_llm_history_collapses_unanswered_same_role_runs():
    previous = [
        SimpleNamespace(role="user", content="Первый старый повтор"),
        SimpleNamespace(role="user", content="Последний старый повтор"),
        SimpleNamespace(role="assistant", content="Уточните время"),
        SimpleNamespace(role="user", content="с 14 до 17"),
        SimpleNamespace(role="user", content="с 14 до 17"),
    ]

    history = ChatService._llm_history(previous, "Давай с 14 до 17")

    assert history == [
        {"role": "user", "content": "Последний старый повтор"},
        {"role": "assistant", "content": "Уточните время"},
        {"role": "user", "content": "Давай с 14 до 17"},
    ]
    assert all(left["role"] != right["role"] for left, right in zip(history, history[1:]))


def test_chat_service_uses_llm_response_history_and_selected_date(auth: dict[str, str]):
    del auth

    class RecordingLLMClient(LLMClient):
        def __init__(self):
            self.calls: list[tuple[list[dict], dict]] = []
            self.responses = iter(["Первый ответ LLM", "Точный второй ответ LLM"])

        async def status(self):
            return {"available": True, "provider": "test", "model": "recording"}

        async def chat(self, messages, **kwargs):
            if kwargs.get("response_schema") is not None:
                return json.dumps({"has_proposal": False})
            self.calls.append((messages, kwargs))
            response = next(self.responses)

            async def chunks():
                yield response[:7]
                yield response[7:]

            return chunks()

    class RecordingContextService:
        def __init__(self):
            self.calls: list[tuple[str, date | None]] = []

        def build(self, db, user, question, selected_date=None):
            del db, user
            self.calls.append((question, selected_date))
            return {"selected_date": selected_date.isoformat() if selected_date else None, "safe": True}

    llm = RecordingLLMClient()
    context = RecordingContextService()
    service = ChatService(llm, context)
    selected_date = date(2031, 5, 17)

    async def collect(db, user, message, conversation_id=None):
        return [
            event
            async for event in service.stream_reply(
                db,
                user,
                message,
                conversation_id=conversation_id,
                selected_date=selected_date,
            )
        ]

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "test@example.com"))
        with patch("backend.ai.engine.compose_chat_reply", create=True) as compose:
            first_events = asyncio.run(collect(db, user, "Первый вопрос"))
            conversation_id = next(event["conversation_id"] for event in first_events if event["event"] == "meta")
            second_events = asyncio.run(collect(db, user, "Второй вопрос", conversation_id))
            compose.assert_not_called()

        assert "".join(
            event.get("text", "") for event in second_events if event["event"] == "chunk"
        ) == "Точный второй ответ LLM"
        assert next(event for event in second_events if event["event"] == "done")["text"] == (
            "Точный второй ответ LLM"
        )
        assert context.calls == [("Первый вопрос", selected_date), ("Второй вопрос", selected_date)]
        assert llm.calls[0][0][-1] == {"role": "user", "content": "Первый вопрос"}
        assert llm.calls[1][0][-3:] == [
            {"role": "user", "content": "Первый вопрос"},
            {"role": "assistant", "content": "Первый ответ LLM"},
            {"role": "user", "content": "Второй вопрос"},
        ]
        assert llm.calls[1][1]["stream"] is True
        system_messages = [message for message in llm.calls[1][0] if message["role"] == "system"]
        assert len(system_messages) == 1
        assert llm.calls[1][0][0] == system_messages[0]
        assert '"selected_date": "2031-05-17"' in system_messages[0]["content"]
        assert "Безопасный контекст пользователя" in system_messages[0]["content"]
        stored = db.scalars(
            select(AIMessage).where(AIMessage.conversation_id == conversation_id).order_by(AIMessage.id)
        ).all()
        assert [message.content for message in stored] == [
            "Первый вопрос",
            "Первый ответ LLM",
            "Второй вопрос",
            "Точный второй ответ LLM",
        ]
    finally:
        db.close()


def test_action_proposal_json_is_hidden_and_invalid_confirmation_is_rejected(auth: dict[str, str]):
    del auth
    invalid_response = """Сначала выберите одну важную задачу из списка.

```json
{"type":"calendar_action_proposal","title":"Выбрать задачу","description":"Выберите одну важную задачу.","requires_confirmation":false,"payload":{}}
```"""
    valid_response = """Могу добавить задачу после вашего подтверждения.

```json
{"type":"task_action_proposal","title":"Подготовить отчёт","description":"Добавить задачу «Подготовить отчёт».","requires_confirmation":true,"payload":{"title":"Подготовить отчёт","estimate_minutes":45}}
```"""

    class ProposalLLMClient(LLMClient):
        def __init__(self):
            self.responses = iter([invalid_response, valid_response])
            self.calls: list[list[dict]] = []

        async def status(self):
            return {"available": True, "provider": "test", "model": "proposal-test"}

        async def chat(self, messages, **kwargs):
            if kwargs.get("response_schema") is not None:
                return json.dumps({"has_proposal": False})
            self.calls.append(messages)
            response = next(self.responses)

            async def chunks():
                for index in range(0, len(response), 5):
                    yield response[index:index + 5]

            return chunks()

    class SafeContextService:
        def build(self, db, user, question, selected_date=None):
            del db, user, question, selected_date
            return {"tasks": [{"title": "Подготовить отчёт"}]}

    llm = ProposalLLMClient()
    service = ChatService(llm, SafeContextService())

    async def collect(db, user, message, conversation_id=None):
        return [
            event
            async for event in service.stream_reply(
                db, user, message, conversation_id=conversation_id
            )
        ]

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "test@example.com"))
        first_events = asyncio.run(collect(db, user, "Что порекомендуешь?"))
        conversation_id = next(event["conversation_id"] for event in first_events if event["event"] == "meta")
        first_done = next(event for event in first_events if event["event"] == "done")
        first_stream = "".join(
            event.get("text", "") for event in first_events if event["event"] == "chunk"
        )

        assert first_stream.strip() == "Сначала выберите одну важную задачу из списка."
        assert first_done["text"] == "Сначала выберите одну важную задачу из списка."
        assert first_done["proposals"] == []
        assert "```json" not in first_stream

        second_events = asyncio.run(
            collect(db, user, "Добавь задачу «Подготовить отчёт» на 45 минут", conversation_id)
        )
        second_done = next(event for event in second_events if event["event"] == "done")
        second_stream = "".join(
            event.get("text", "") for event in second_events if event["event"] == "chunk"
        )

        assert second_stream.strip() == "Могу добавить задачу после вашего подтверждения."
        assert second_done["text"] == "Могу добавить задачу после вашего подтверждения."
        assert len(second_done["proposals"]) == 1
        assert second_done["proposals"][0]["requires_confirmation"] is True
        assert "```json" not in second_stream
        assert llm.calls[1][-3] == {"role": "user", "content": "Что порекомендуешь?"}
        assert llm.calls[1][-2] == {
            "role": "assistant",
            "content": "Сначала выберите одну важную задачу из списка.",
        }

        stored = db.scalars(
            select(AIMessage).where(AIMessage.conversation_id == conversation_id).order_by(AIMessage.id)
        ).all()
        assert "```json" not in stored[1].content
        assert "```json" not in stored[3].content
        assert ChatService.visible_content(invalid_response) == first_done["text"]
    finally:
        db.close()


def test_structured_llm_action_proposal_is_saved_separately_from_visible_text(auth: dict[str, str]):
    del auth

    class StructuredProposalLLMClient(LLMClient):
        def __init__(self):
            self.calls: list[tuple[list[dict], dict]] = []

        async def status(self):
            return {"available": True, "provider": "test", "model": "structured-proposal"}

        async def chat(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            if kwargs.get("response_schema") is not None:
                return json.dumps({
                    "has_proposal": True,
                    "action_type": "calendar_action_proposal",
                    "title": "Запланировать плавание",
                    "description": "Добавить плавание с 14:00 до 17:00.",
                    "calendar_title": "Плавание",
                    "start_at": "2031-05-17T14:00:00",
                    "end_at": "2031-05-17T17:00:00",
                    "category": "health",
                    "task_title": "",
                    "priority": "",
                    "estimate_minutes": 0,
                }, ensure_ascii=False)

            async def chunks():
                yield "Подготовил предложение события. "
                yield "Подтвердите его перед добавлением."

            return chunks()

    class SelectedDateContextService:
        def build(self, db, user, question, selected_date=None):
            del db, user, question
            return {"selected_date": selected_date.isoformat(), "user": {"timezone": "Europe/Moscow"}}

    llm = StructuredProposalLLMClient()
    service = ChatService(llm, SelectedDateContextService())
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "test@example.com"))

        async def collect():
            return [
                event
                async for event in service.stream_reply(
                    db,
                    user,
                    "Давай запланируем плавание с 14 до 17",
                    selected_date=date(2031, 5, 17),
                    auto_execute_actions=True,
                )
            ]

        events = asyncio.run(collect())
        done = next(event for event in events if event["event"] == "done")
        assert done["text"] == "Подготовил предложение события. Подтвердите его перед добавлением."
        assert len(done["proposals"]) == 1
        assert done["proposals"][0]["type"] == "calendar_action_proposal"
        assert done["proposals"][0]["requires_confirmation"] is True
        assert done["proposals"][0]["status"] == "confirmed"
        assert done["action_error"] is None
        assert llm.calls[0][1]["stream"] is True
        assert llm.calls[1][1]["stream"] is False
        assert llm.calls[1][1]["response_schema"]["additionalProperties"] is False
        proposal = db.scalar(select(AIActionProposal).where(AIActionProposal.id == done["proposals"][0]["id"]))
        assert json.loads(proposal.payload)["start_at"] == "2031-05-17T14:00:00"
        event = db.scalar(select(Event).where(Event.user_id == user.id, Event.title == "Плавание"))
        assert event is not None
    finally:
        db.close()


def test_gigachat_action_classifier_uses_prompt_schema_without_response_format():
    class PlainJSONGigaClient(LLMClient):
        provider = "gigachat"

        def __init__(self):
            self.calls: list[tuple[list[dict], dict]] = []

        async def status(self):
            return {"available": True, "provider": self.provider, "model": "test"}

        async def chat(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            return """```json
{"has_proposal":false,"action_type":"none","title":"","description":"","calendar_title":"","start_at":"","end_at":"","category":"","task_title":"","priority":"","estimate_minutes":0}
```"""

    llm = PlainJSONGigaClient()
    service = ChatService(llm)
    result = asyncio.run(service._generate_action_proposal(
        {"selected_date": "2031-05-17"},
        [{"role": "user", "content": "Что порекомендуешь?"}],
        "Уточните, какое действие вы хотите запланировать.",
    ))

    assert result is None
    assert llm.calls[0][1]["response_schema"] is None
    assert "JSON Schema" in llm.calls[0][0][0]["content"]


def test_unavailable_llm_returns_error_without_fallback(client: TestClient, auth: dict[str, str]):
    class UnavailableLLMClient(LLMClient):
        async def status(self):
            raise LLMUnavailableError("Тестовый LLM-провайдер недоступен")

        async def chat(self, messages, **kwargs):
            raise AssertionError("chat must not run when provider status is unavailable")

    with patch("backend.api.ai.get_llm_client", return_value=UnavailableLLMClient()):
        response = client.post("/api/v1/ai/chat", headers=auth, json={"message": "Мой запрос"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Тестовый LLM-провайдер недоступен"}
    assert client.get("/api/v1/ai/conversations", headers=auth).json() == []

    class FailingStreamLLMClient(LLMClient):
        async def status(self):
            return {"available": True, "provider": "test", "model": "failing-stream"}

        async def chat(self, messages, **kwargs):
            raise LLMUnavailableError("LLM отключился во время генерации")

    with patch("backend.api.ai.get_llm_client", return_value=FailingStreamLLMClient()):
        streamed = client.post("/api/v1/ai/chat", headers=auth, json={"message": "Второй запрос"})

    assert streamed.status_code == 200
    assert '"event": "error"' in streamed.text
    assert "LLM отключился во время генерации" in streamed.text
    conversations = client.get("/api/v1/ai/conversations", headers=auth).json()
    messages = client.get(
        f"/api/v1/ai/conversations/{conversations[0]['id']}/messages", headers=auth
    ).json()
    assert [(message["role"], message["content"]) for message in messages] == [("user", "Второй запрос")]


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
