from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.action_service import execute_action_proposal
from backend.ai.client import LLMClient, LLMError, LLMResponseError
from backend.ai.context_service import UserContextService
from backend.ai.prompts import ACTION_PROPOSAL_SCHEMA, ACTION_PROPOSAL_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT
from backend.config import get_settings
from backend.models import AIActionProposal, AIConversation, AIMessage, User, utcnow


_generation_slots = asyncio.Semaphore(get_settings().ai_max_concurrent_generations)
logger = logging.getLogger(__name__)
_proposal_pattern = re.compile(r"```json\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
_json_fence_start_pattern = re.compile(r"```json\s*", re.IGNORECASE)


def _action_proposal_payload(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or not str(payload.get("type", "")).endswith("_action_proposal"):
        return None
    return payload


class _VisibleResponseStream:
    """Streams prose while holding fenced JSON until it is known to be user-visible."""

    _prefix_tail_length = len("```json") - 1

    def __init__(self):
        self.buffer = ""
        self.inside_json_fence = False

    def feed(self, chunk: str) -> str:
        self.buffer += chunk
        visible: list[str] = []
        while self.buffer:
            if not self.inside_json_fence:
                match = _json_fence_start_pattern.search(self.buffer)
                if match is not None:
                    visible.append(self.buffer[:match.start()])
                    self.buffer = self.buffer[match.start():]
                    self.inside_json_fence = True
                    continue
                safe_length = max(0, len(self.buffer) - self._prefix_tail_length)
                if safe_length:
                    visible.append(self.buffer[:safe_length])
                    self.buffer = self.buffer[safe_length:]
                break

            start = _json_fence_start_pattern.match(self.buffer)
            if start is None:
                self.inside_json_fence = False
                continue
            closing_index = self.buffer.find("```", start.end())
            if closing_index < 0:
                break
            block_end = closing_index + 3
            raw_json = self.buffer[start.end():closing_index].strip()
            if _action_proposal_payload(raw_json) is None:
                visible.append(self.buffer[:block_end])
            self.buffer = self.buffer[block_end:]
            self.inside_json_fence = False
        return "".join(visible)

    def finish(self, *, drop_incomplete_json: bool = False) -> str:
        if drop_incomplete_json and self.inside_json_fence:
            trailing = ""
        else:
            trailing = self.buffer
        self.buffer = ""
        self.inside_json_fence = False
        return trailing


class ConversationNotFoundError(LookupError):
    pass


class ChatService:
    def __init__(self, llm_client: LLMClient, context_service: UserContextService | None = None):
        self.llm_client = llm_client
        self.context_service = context_service or UserContextService()

    async def ensure_available(self) -> dict[str, Any]:
        return await self.llm_client.status()

    @staticmethod
    def visible_content(content: str) -> str:
        descriptions: list[str] = []

        def remove_proposal(match: re.Match[str]) -> str:
            payload = _action_proposal_payload(match.group(1))
            if payload is None:
                return match.group(0)
            description = str(payload.get("description", "")).strip()
            if description:
                descriptions.append(description)
            return ""

        visible = _proposal_pattern.sub(remove_proposal, content).strip()
        return visible or "\n\n".join(descriptions).strip()

    @classmethod
    def _llm_history(cls, previous: list[AIMessage], current_message: str) -> list[dict[str, str]]:
        """Keep the latest message from an unanswered same-role run for provider-compatible history."""
        messages: list[dict[str, str]] = []
        for item in previous:
            if item.role not in {"user", "assistant"}:
                continue
            content = cls.visible_content(item.content) if item.role == "assistant" else item.content.strip()
            if not content:
                continue
            message = {"role": item.role, "content": content}
            if messages and messages[-1]["role"] == item.role:
                messages[-1] = message
            else:
                messages.append(message)

        current = {"role": "user", "content": current_message}
        if messages and messages[-1]["role"] == "user":
            messages[-1] = current
        else:
            messages.append(current)
        return messages

    @staticmethod
    def get_conversation(db: Session, user_id: int, conversation_id: int) -> AIConversation:
        conversation = db.scalar(
            select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.user_id == user_id)
        )
        if conversation is None:
            raise ConversationNotFoundError("Диалог не найден")
        return conversation

    @staticmethod
    def create_conversation(db: Session, user_id: int, title: str | None = None) -> AIConversation:
        conversation = AIConversation(user_id=user_id, title=(title or "Новый диалог").strip()[:120] or "Новый диалог")
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation

    async def stream_reply(
        self,
        db: Session,
        user: User,
        message: str,
        *,
        conversation_id: int | None = None,
        selected_date: date | None = None,
        auto_execute_actions: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        conversation = (
            self.get_conversation(db, user.id, conversation_id)
            if conversation_id is not None
            else self.create_conversation(db, user.id)
        )
        previous = db.scalars(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation.id, AIMessage.user_id == user.id)
            .order_by(AIMessage.created_at.desc())
            .limit(20)
        ).all()
        previous = list(reversed(previous))
        user_message = AIMessage(conversation_id=conversation.id, user_id=user.id, role="user", content=message)
        db.add(user_message)
        if not previous:
            conversation.title = message.strip().replace("\n", " ")[:80]
        conversation.updated_at = utcnow()
        db.commit()
        yield {"event": "meta", "conversation_id": conversation.id}

        context = self.context_service.build(db, user, message, selected_date)
        context["action_execution_mode"] = (
            "automatic_for_explicit_calendar_commands"
            if auto_execute_actions
            else "requires_confirmation"
        )
        history = self._llm_history(previous, message)
        llm_messages = [
            {
                "role": "system",
                "content": (
                    CHAT_SYSTEM_PROMPT
                    + "\n\nБезопасный контекст пользователя:\n"
                    + json.dumps(context, ensure_ascii=False)
                ),
            },
            *history,
        ]
        chunks: list[str] = []
        visible_chunks: list[str] = []
        visible_stream = _VisibleResponseStream()
        stream_finished = False
        assistant_saved = False
        try:
            async with _generation_slots:
                result = await self.llm_client.chat(llm_messages, stream=True, temperature=0.3)
                if isinstance(result, str):
                    chunks.append(result)
                    visible_chunk = visible_stream.feed(result)
                    if visible_chunk:
                        visible_chunks.append(visible_chunk)
                        yield {"event": "chunk", "text": visible_chunk}
                else:
                    async for chunk in result:
                        chunks.append(chunk)
                        visible_chunk = visible_stream.feed(chunk)
                        if visible_chunk:
                            visible_chunks.append(visible_chunk)
                            yield {"event": "chunk", "text": visible_chunk}
            trailing = visible_stream.finish()
            stream_finished = True
            if trailing:
                visible_chunks.append(trailing)
                yield {"event": "chunk", "text": trailing}
            raw_content = "".join(chunks).strip()
            if not raw_content:
                raise LLMResponseError("AI-провайдер вернул пустой ответ. Повторите попытку")
            content = self.visible_content(raw_content)
            if not content:
                raise LLMResponseError("AI-провайдер вернул ответ без текста. Повторите попытку")
            assistant = self._save_assistant(db, user.id, conversation, content)
            assistant_saved = True
            proposal_data: dict[str, Any] | None = None
            try:
                async with _generation_slots:
                    proposal_data = await self._generate_action_proposal(context, history, content)
            except LLMError as exc:
                logger.warning("AI action proposal classification failed: %s", exc)
            proposals = self._save_structured_proposal(
                db, user.id, conversation.id, assistant.id, proposal_data
            )
            if not proposals:
                proposals = self._save_proposals(db, user.id, conversation.id, assistant.id, raw_content)
            action_error = None
            if auto_execute_actions:
                for proposal in proposals:
                    if proposal.type != "calendar_action_proposal":
                        continue
                    try:
                        execute_action_proposal(db, user, proposal)
                    except ValueError as exc:
                        action_error = str(exc)
                        logger.warning("Automatic calendar action failed: %s", exc)
            yield {
                "event": "done",
                "conversation_id": conversation.id,
                "message_id": assistant.id,
                "text": content,
                "action_error": action_error,
                "proposals": [{
                    "id": item.id,
                    "type": item.type,
                    "title": item.title,
                    "description": item.description,
                    "status": item.status,
                    "requires_confirmation": item.requires_confirmation,
                } for item in proposals],
            }
        finally:
            if not stream_finished:
                trailing = visible_stream.finish(drop_incomplete_json=True)
                if trailing:
                    visible_chunks.append(trailing)
            partial_content = "".join(visible_chunks).strip()
            if partial_content and not assistant_saved:
                self._save_assistant(db, user.id, conversation, partial_content)

    async def _generate_action_proposal(
        self,
        context: dict[str, Any],
        history: list[dict[str, str]],
        assistant_answer: str,
    ) -> dict[str, Any] | None:
        request = {
            "history": history[-12:],
            "assistant_answer": assistant_answer,
            "safe_context": context,
        }
        provider = getattr(self.llm_client, "provider", "")
        system_prompt = ACTION_PROPOSAL_SYSTEM_PROMPT
        response_schema = ACTION_PROPOSAL_SCHEMA
        if provider == "gigachat":
            system_prompt += "\n\nJSON Schema:\n" + json.dumps(ACTION_PROPOSAL_SCHEMA, ensure_ascii=False)
            response_schema = None
        result = await self.llm_client.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ],
            stream=False,
            response_schema=response_schema,
            temperature=0,
        )
        if not isinstance(result, str):
            raise LLMResponseError("AI-провайдер вернул некорректное предложение действия")
        try:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            decision = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMResponseError("AI-провайдер вернул некорректное предложение действия") from exc
        if not isinstance(decision, dict) or decision.get("has_proposal") is not True:
            return None

        action_type = decision.get("action_type")
        title = str(decision.get("title", "")).strip()
        description = str(decision.get("description", "")).strip()
        if not title or not description:
            return None
        if action_type == "calendar_action_proposal":
            calendar_title = str(decision.get("calendar_title", "")).strip()
            start_at = str(decision.get("start_at", "")).strip()
            end_at = str(decision.get("end_at", "")).strip()
            try:
                if not calendar_title or datetime.fromisoformat(end_at) <= datetime.fromisoformat(start_at):
                    return None
            except ValueError:
                return None
            payload = {
                "title": calendar_title,
                "description": description,
                "start_at": start_at,
                "end_at": end_at,
                "category": str(decision.get("category") or "personal")[:40],
            }
        elif action_type == "task_action_proposal":
            task_title = str(decision.get("task_title", "")).strip()
            try:
                estimate_minutes = int(decision.get("estimate_minutes", 0))
            except (TypeError, ValueError):
                return None
            if not task_title or not 5 <= estimate_minutes <= 1440:
                return None
            priority = str(decision.get("priority") or "medium")
            if priority not in {"low", "medium", "high", "urgent"}:
                priority = "medium"
            payload = {
                "title": task_title,
                "description": description,
                "priority": priority,
                "estimate_minutes": estimate_minutes,
            }
        else:
            return None
        return {
            "type": action_type,
            "title": title,
            "description": description,
            "payload": payload,
        }

    @staticmethod
    def _save_assistant(
        db: Session, user_id: int, conversation: AIConversation, content: str
    ) -> AIMessage:
        assistant = AIMessage(
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content=content,
        )
        conversation.updated_at = utcnow()
        db.add(assistant)
        db.commit()
        db.refresh(assistant)
        return assistant

    @staticmethod
    def _save_proposals(
        db: Session, user_id: int, conversation_id: int, message_id: int, content: str
    ) -> list[AIActionProposal]:
        proposals: list[AIActionProposal] = []
        for raw in _proposal_pattern.findall(content)[-3:]:
            payload = _action_proposal_payload(raw)
            if payload is None:
                continue
            action_type = str(payload.get("type", ""))
            if payload.get("requires_confirmation") is not True:
                continue
            title = str(payload.get("title", "")).strip()[:200]
            description = str(payload.get("description", "")).strip()[:2000]
            if not title or not description:
                continue
            proposal = AIActionProposal(
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                type=action_type[:80],
                title=title,
                description=description,
                payload=json.dumps(payload.get("payload") or {}, ensure_ascii=False)[:8000],
            )
            db.add(proposal)
            proposals.append(proposal)
        if proposals:
            db.commit()
            for item in proposals:
                db.refresh(item)
        return proposals

    @staticmethod
    def _save_structured_proposal(
        db: Session,
        user_id: int,
        conversation_id: int,
        message_id: int,
        decision: dict[str, Any] | None,
    ) -> list[AIActionProposal]:
        if decision is None:
            return []
        proposal = AIActionProposal(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            type=str(decision["type"])[:80],
            title=str(decision["title"])[:200],
            description=str(decision["description"])[:2000],
            payload=json.dumps(decision["payload"], ensure_ascii=False)[:8000],
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        return [proposal]
