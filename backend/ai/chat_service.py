from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.client import LLMClient
from backend.ai.context_service import UserContextService
from backend.ai.prompts import CHAT_SYSTEM_PROMPT
from backend.config import get_settings
from backend.models import AIActionProposal, AIConversation, AIMessage, User, utcnow


_generation_slots = asyncio.Semaphore(get_settings().ai_max_concurrent_generations)
_proposal_pattern = re.compile(r"```json\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


class ConversationNotFoundError(LookupError):
    pass


class ChatService:
    def __init__(self, llm_client: LLMClient, context_service: UserContextService | None = None):
        self.llm_client = llm_client
        self.context_service = context_service or UserContextService()

    async def ensure_available(self) -> dict[str, Any]:
        return await self.llm_client.status()

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
        llm_messages = [
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "system", "content": "Безопасный контекст пользователя:\n" + json.dumps(context, ensure_ascii=False)},
            *[{"role": item.role, "content": item.content} for item in previous if item.role in {"user", "assistant"}],
            {"role": "user", "content": message},
        ]
        chunks: list[str] = []
        assistant_saved = False
        try:
            async with _generation_slots:
                result = await self.llm_client.chat(llm_messages, stream=True, temperature=0.3)
                if isinstance(result, str):
                    chunks.append(result)
                    yield {"event": "chunk", "text": result}
                else:
                    async for chunk in result:
                        chunks.append(chunk)
                        yield {"event": "chunk", "text": chunk}
            content = "".join(chunks).strip()
            assistant = self._save_assistant(db, user.id, conversation, content)
            assistant_saved = True
            proposals = self._save_proposals(db, user.id, conversation.id, assistant.id, content)
            yield {
                "event": "done",
                "conversation_id": conversation.id,
                "message_id": assistant.id,
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
            if chunks and not assistant_saved:
                self._save_assistant(db, user.id, conversation, "".join(chunks).strip())

    @staticmethod
    def _save_assistant(
        db: Session, user_id: int, conversation: AIConversation, content: str
    ) -> AIMessage:
        assistant = AIMessage(
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content=content or "Не удалось сформировать ответ",
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
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            action_type = str(payload.get("type", ""))
            if not action_type.endswith("_action_proposal") or payload.get("requires_confirmation") is not True:
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
