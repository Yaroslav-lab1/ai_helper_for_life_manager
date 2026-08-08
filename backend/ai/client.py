from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta
from typing import Any

import httpx

from backend.services.time import utc_now


logger = logging.getLogger(__name__)


OLLAMA_UNAVAILABLE_MESSAGE = "Локальная нейросеть недоступна. Запустите Ollama и повторите попытку"
GIGACHAT_UNAVAILABLE_MESSAGE = "GigaChat недоступен. Проверьте подключение и ключ авторизации"
GIGACHAT_RATE_LIMIT_MESSAGE = (
    "GigaChat занят другим запросом или временно ограничил частоту. "
    "Подождите несколько секунд и повторите попытку"
)


class LLMError(RuntimeError):
    """Safe, user-facing LLM error."""


class LLMUnavailableError(LLMError):
    pass


class LLMModelNotFoundError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


class LLMClient:
    async def chat(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        response_schema: dict | None = None,
        temperature: float = 0.3,
    ) -> str | AsyncIterator[str]:
        raise NotImplementedError

    async def status(self) -> dict[str, Any]:
        raise NotImplementedError


class OllamaLLMClient(LLMClient):
    provider = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout_seconds: int = 120,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            transport=self.transport,
        )

    async def status(self) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise LLMUnavailableError(OLLAMA_UNAVAILABLE_MESSAGE) from exc

        names = {
            str(item.get("name") or item.get("model") or "")
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        if self.model not in names:
            raise LLMModelNotFoundError(f"Модель {self.model} не найдена в Ollama")
        return {
            "available": True,
            "provider": "ollama",
            "model": self.model,
            "base_url": self.base_url,
        }

    async def chat(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        response_schema: dict | None = None,
        temperature: float = 0.3,
    ) -> str | AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": stream,
            "think": False,
            "messages": messages,
            "options": {"temperature": temperature},
        }
        if response_schema is not None:
            payload["format"] = response_schema
        if stream:
            return self._stream(payload)
        return await self._complete(payload)

    async def _complete(self, payload: dict[str, Any]) -> str:
        for attempt in range(2):
            try:
                async with self._client() as client:
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)
                    response.raise_for_status()
                data = response.json()
                content = data["message"]["content"]
                if not isinstance(content, str):
                    raise TypeError("message.content is not text")
                return content
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                if attempt == 0:
                    await asyncio.sleep(0)
                    continue
                raise LLMUnavailableError(OLLAMA_UNAVAILABLE_MESSAGE) from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise LLMModelNotFoundError(f"Модель {self.model} не найдена в Ollama") from exc
                logger.warning(
                    "Ollama chat returned HTTP %s: %s",
                    exc.response.status_code,
                    exc.response.text[:500],
                )
                raise LLMResponseError("Локальная нейросеть вернула ошибку") from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise LLMResponseError("Некорректный ответ локальной нейросети") from exc
        raise LLMUnavailableError(OLLAMA_UNAVAILABLE_MESSAGE)

    async def _stream(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        emitted = False
        for attempt in range(2):
            try:
                async with self._client() as client:
                    async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            data = json.loads(line)
                            chunk = data.get("message", {}).get("content", "")
                            if chunk:
                                emitted = True
                                yield str(chunk)
                            if data.get("done"):
                                return
                return
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                if attempt == 0 and not emitted:
                    await asyncio.sleep(0)
                    continue
                raise LLMUnavailableError(OLLAMA_UNAVAILABLE_MESSAGE) from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise LLMModelNotFoundError(f"Модель {self.model} не найдена в Ollama") from exc
                logger.warning("Ollama stream returned HTTP %s", exc.response.status_code)
                raise LLMResponseError("Локальная нейросеть вернула ошибку") from exc
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise LLMResponseError("Некорректный потоковый ответ локальной нейросети") from exc


class GigaChatLLMClient(LLMClient):
    """GigaChat REST client with automatic OAuth token refresh."""

    provider = "gigachat"

    def __init__(
        self,
        model: str,
        authorization_key: str,
        scope: str = "GIGACHAT_API_PERS",
        base_url: str = "https://api.giga.chat/v1",
        oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        timeout_seconds: int = 120,
        verify_ssl: bool = True,
        ca_bundle_file: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] | None = None,
    ):
        self.model = model
        self.authorization_key = authorization_key.strip()
        self.scope = scope
        self.base_url = base_url.rstrip("/")
        self.oauth_url = oauth_url
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl
        self.ca_bundle_file = ca_bundle_file
        self.transport = transport
        self._clock = clock or time.time
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        # Freemium access for individuals permits one generation stream.
        self._generation_lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        verify: bool | ssl.SSLContext = self.verify_ssl
        if self.verify_ssl and self.ca_bundle_file:
            verify = ssl.create_default_context()
            verify.load_verify_locations(cafile=self.ca_bundle_file)
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            verify=verify,
            transport=self.transport,
        )

    def _basic_authorization(self) -> str:
        key = self.authorization_key
        if key.lower().startswith("basic "):
            key = key[6:].strip()
        return f"Basic {key}"

    async def _get_access_token(self) -> str:
        if not self.authorization_key:
            raise LLMUnavailableError(
                "Ключ авторизации GigaChat не настроен. Укажите GIGACHAT_AUTHORIZATION_KEY"
            )

        now = self._clock()
        if self._access_token and now < self._access_token_expires_at - 60:
            return self._access_token

        async with self._token_lock:
            now = self._clock()
            if self._access_token and now < self._access_token_expires_at - 60:
                return self._access_token
            try:
                async with self._client() as client:
                    response = await client.post(
                        self.oauth_url,
                        headers={
                            "Accept": "application/json",
                            "Authorization": self._basic_authorization(),
                            "RqUID": str(uuid.uuid4()),
                        },
                        data={"scope": self.scope},
                    )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                raise LLMUnavailableError(GIGACHAT_UNAVAILABLE_MESSAGE) from exc

            if response.status_code in {401, 403}:
                raise LLMUnavailableError(
                    "GigaChat отклонил ключ авторизации. Проверьте GIGACHAT_AUTHORIZATION_KEY"
                )
            if response.is_error:
                logger.warning(
                    "GigaChat OAuth returned HTTP %s: %s",
                    response.status_code,
                    response.text[:500],
                )
                raise LLMUnavailableError(GIGACHAT_UNAVAILABLE_MESSAGE)

            try:
                payload = response.json()
                access_token = payload["access_token"]
                if not isinstance(access_token, str) or not access_token:
                    raise TypeError("access_token is missing")
                raw_expiry = float(payload.get("expires_at") or now + 25 * 60)
            except (KeyError, TypeError, ValueError) as exc:
                raise LLMResponseError("GigaChat вернул некорректный OAuth-ответ") from exc

            # The API has returned expires_at in both seconds and milliseconds.
            if raw_expiry > 10_000_000_000:
                raw_expiry /= 1000
            if raw_expiry <= now:
                raw_expiry = now + 25 * 60
            self._access_token = access_token
            self._access_token_expires_at = raw_expiry
            return access_token

    def _invalidate_access_token(self, rejected_token: str) -> None:
        if self._access_token == rejected_token:
            self._access_token = None
            self._access_token_expires_at = 0

    def _raise_for_api_error(self, response: httpx.Response) -> None:
        if response.status_code == 404:
            raise LLMModelNotFoundError(f"Модель {self.model} не найдена в GigaChat")
        if response.status_code in {401, 403}:
            raise LLMUnavailableError(
                "GigaChat отклонил access token. Проверьте ключ авторизации"
            )
        if response.status_code == 429:
            logger.warning("GigaChat rate limit response: %s", response.text[:500])
            raise LLMUnavailableError(GIGACHAT_RATE_LIMIT_MESSAGE)
        if response.is_error:
            logger.warning(
                "GigaChat API returned HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )
            raise LLMResponseError("GigaChat вернул ошибку")

    async def _api_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        for attempt in range(2):
            token = await self._get_access_token()
            try:
                async with self._client() as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}/{path.lstrip('/')}",
                        headers={
                            "Accept": "application/json",
                            "Authorization": f"Bearer {token}",
                        },
                        json=json_body,
                    )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                if attempt == 0:
                    await asyncio.sleep(0)
                    continue
                raise LLMUnavailableError(GIGACHAT_UNAVAILABLE_MESSAGE) from exc
            if response.status_code == 401 and attempt == 0:
                self._invalidate_access_token(token)
                continue
            if response.status_code == 429 and attempt == 0:
                await asyncio.sleep(self._retry_delay(response))
                continue
            self._raise_for_api_error(response)
            return response
        raise LLMUnavailableError(GIGACHAT_UNAVAILABLE_MESSAGE)

    @staticmethod
    def _retry_delay(response: httpx.Response) -> float:
        try:
            return min(5.0, max(0.25, float(response.headers.get("Retry-After", "1"))))
        except ValueError:
            return 1.0

    @staticmethod
    def _model_aliases(model: str) -> set[str]:
        aliases = {
            "GigaChat": "GigaChat-2",
            "GigaChat-Pro": "GigaChat-2-Pro",
            "GigaChat-Max": "GigaChat-2-Max",
        }
        result = {model}
        if model in aliases:
            result.add(aliases[model])
        legacy_name = next((old for old, new in aliases.items() if new == model), None)
        if legacy_name:
            result.add(legacy_name)
        return result

    async def status(self) -> dict[str, Any]:
        response = await self._api_request("GET", "models")
        try:
            payload = response.json()
            models = payload["data"]
            if not isinstance(models, list):
                raise TypeError("data is not a list")
            names = {
                str(item.get("id") or "")
                for item in models
                if isinstance(item, dict)
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError("GigaChat вернул некорректный список моделей") from exc
        if not (self._model_aliases(self.model) & names):
            raise LLMModelNotFoundError(f"Модель {self.model} не найдена в GigaChat")
        return {
            "available": True,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
        }

    async def chat(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        response_schema: dict | None = None,
        temperature: float = 0.3,
    ) -> str | AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "schema": response_schema,
                "strict": True,
            }
        if stream:
            return self._stream(payload)
        return await self._complete(payload)

    async def _complete(self, payload: dict[str, Any]) -> str:
        async with self._generation_lock:
            try:
                return await self._complete_unlocked(payload)
            except LLMResponseError as exc:
                if str(exc) != "GigaChat завершил генерацию без текста. Повторите попытку":
                    raise
                logger.warning("GigaChat completion returned no text. Retrying with compact recovery context")
                return await self._complete_unlocked(self._recovery_payload(payload))

    @staticmethod
    def _recovery_payload(payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages") or []
        system_message = next(
            (message for message in messages if message.get("role") == "system"),
            None,
        )
        last_user = next(
            (message for message in reversed(messages) if message.get("role") == "user"),
            {"role": "user", "content": "Сформируй ответ пользователю"},
        )
        recovery_user = {
            **last_user,
            "content": (
                str(last_user.get("content", "")).strip()
                + "\n\nПредыдущая генерация завершилась без текста. "
                "Обязательно верни непустой ответ в формате, указанном системной инструкцией."
            ),
        }
        recovery_messages = [system_message, recovery_user] if system_message is not None else [recovery_user]
        return {
            **payload,
            "messages": recovery_messages,
            "stream": False,
            "temperature": min(0.2, float(payload.get("temperature", 0.2))),
        }

    async def _complete_unlocked(self, payload: dict[str, Any]) -> str:
        response = await self._api_request(
            "POST",
            "chat/completions",
            json_body=payload,
        )
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message.content is not text")
            if not content.strip():
                raise LLMResponseError("GigaChat завершил генерацию без текста. Повторите попытку")
            return content
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError("GigaChat вернул некорректный ответ") from exc

    async def _stream(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        async with self._generation_lock:
            async for chunk in self._stream_unlocked(payload):
                yield chunk

    async def _stream_unlocked(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        emitted = False
        for attempt in range(2):
            token = await self._get_access_token()
            finish_reason: str | None = None
            request_id: str | None = None
            try:
                async with self._client() as client:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Accept": "text/event-stream",
                            "Authorization": f"Bearer {token}",
                        },
                        json=payload,
                    ) as response:
                        if response.status_code == 401 and attempt == 0 and not emitted:
                            await response.aread()
                            self._invalidate_access_token(token)
                            continue
                        if response.status_code == 429 and attempt == 0 and not emitted:
                            await response.aread()
                            await asyncio.sleep(self._retry_delay(response))
                            continue
                        if response.is_error:
                            await response.aread()
                            self._raise_for_api_error(response)
                        request_id = response.headers.get("x-request-id")
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            encoded = line[5:].strip()
                            if encoded == "[DONE]":
                                break
                            data = json.loads(encoded)
                            choice = data.get("choices", [{}])[0]
                            finish_reason = choice.get("finish_reason") or finish_reason
                            chunk = choice.get("delta", {}).get("content", "")
                            if chunk:
                                emitted = True
                                yield str(chunk)
                if emitted:
                    return
                logger.warning(
                    "GigaChat stream completed without text; finish_reason=%s request_id=%s. "
                    "Retrying once with compact recovery context",
                    finish_reason,
                    request_id,
                )
                fallback = await self._complete_unlocked(self._recovery_payload(payload))
                yield fallback
                return
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                if attempt == 0 and not emitted:
                    await asyncio.sleep(0)
                    continue
                raise LLMUnavailableError(GIGACHAT_UNAVAILABLE_MESSAGE) from exc
            except (IndexError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise LLMResponseError("GigaChat вернул некорректный потоковый ответ") from exc


class MockLLMClient(LLMClient):
    """Deterministic client used only by automated tests."""

    provider = "mock"

    async def status(self) -> dict[str, Any]:
        return {"available": True, "provider": "mock", "model": "mock", "base_url": None}

    async def chat(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        response_schema: dict | None = None,
        temperature: float = 0.3,
    ) -> str | AsyncIterator[str]:
        del temperature
        if response_schema is not None:
            result = json.dumps(self._goal_plan(messages), ensure_ascii=False)
        else:
            user_text = next(
                (str(message.get("content", "")) for message in reversed(messages) if message.get("role") == "user"),
                "",
            )
            result = f"Я изучил ваш контекст. Предлагаю начать с одного приоритетного шага: {user_text}"
        if not stream:
            return result

        async def chunks() -> AsyncIterator[str]:
            for word in result.split(" "):
                yield word + " "

        return chunks()

    @staticmethod
    def _goal_plan(messages: list[dict] | None = None) -> dict[str, Any]:
        messages = messages or []
        selected_date = next((
            payload.get("selected_date")
            for message in reversed(messages)
            if message.get("role") == "user"
            for payload in [MockLLMClient._json_object(message.get("content"))]
            if payload.get("selected_date")
        ), utc_now().date().isoformat())
        planning_date = date.fromisoformat(str(selected_date))
        first_deadline = planning_date + timedelta(days=6)
        milestone_deadline = planning_date + timedelta(days=14)
        return {
            "goal_summary": "Достичь сформулированной цели",
            "strategy": "Двигаться короткими регулярными итерациями с еженедельной проверкой прогресса",
            "assumptions": ["Доступно не менее трёх часов в неделю"],
            "clarifying_questions": [],
            "milestones": [{
                "title": "Подтвердить первый измеримый результат",
                "description": "Зафиксировать исходную точку и критерий успеха",
                "deadline": milestone_deadline.isoformat(),
                "success_criteria": ["Критерий результата записан и проверяем"],
            }],
            "monthly_actions": [{"month": planning_date.strftime("%Y-%m"), "actions": ["Выполнить четыре недельных итерации"]}],
            "weekly_plan": [{"day_of_week": "monday", "duration_minutes": 30, "action": "Проверить прогресс"}],
            "tasks": [{
                "title": "Зафиксировать исходную точку",
                "description": "Описать текущую ситуацию и ближайший результат",
                "priority": "high",
                "estimated_minutes": 45,
                "deadline": first_deadline.isoformat(),
            }],
            "habits": [{"title": "Ежедневный шаг к цели", "frequency": "daily", "duration_minutes": 20}],
            "schedule_suggestions": [{
                "title": "Фокус на цели",
                "preferred_days": ["monday", "wednesday", "friday"],
                "preferred_time": "19:00",
                "duration_minutes": 30,
            }],
            "risks": [{"risk": "Нерегулярность", "mitigation": "Сохранить минимальную версию действия на 10 минут"}],
            "progress_metrics": [{"name": "Фокус-сессии", "target": "12 в месяц"}],
            "first_next_action": {"title": "Зафиксировать исходную точку", "estimated_minutes": 45},
        }

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
