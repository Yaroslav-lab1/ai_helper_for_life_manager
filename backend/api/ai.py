from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from backend.ai.chat_service import ChatService, ConversationNotFoundError
from backend.ai.client import LLMError
from backend.ai.factory import get_llm_client
from backend.ai.schemas import (
    AIMessageResponse,
    AIStatusResponse,
    ActionProposalResponse,
    ActionProposalUpdate,
    ChatRequest,
    ConversationCreate,
    ConversationResponse,
)
from backend.api.deps import CurrentUser, DbSession
from backend.database import SessionLocal
from backend.models import AIActionProposal, AIConversation, AIMessage, Event, Task, User
from backend.services.time import to_utc
from backend.services.privacy import require_ai_context_consent


router = APIRouter(prefix="/ai", tags=["AI chat"])
logger = logging.getLogger(__name__)


def _service() -> ChatService:
    return ChatService(get_llm_client())


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/status", response_model=AIStatusResponse)
async def ai_status(user: CurrentUser):
    del user
    client = get_llm_client()
    try:
        current = await client.status()
        return {**current, "message": "AI-провайдер готов"}
    except LLMError as exc:
        return {
            "available": False,
            "provider": getattr(client, "provider", "unknown"),
            "model": getattr(client, "model", "unknown"),
            "message": str(exc),
        }


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request, user: CurrentUser, db: DbSession):
    require_ai_context_consent(user)
    service = _service()
    try:
        await service.ensure_available()
        if payload.conversation_id is not None:
            service.get_conversation(db, user.id, payload.conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    user_id = user.id

    async def events():
        stream_db = SessionLocal()
        try:
            stream_user = stream_db.get(User, user_id)
            if stream_user is None:
                yield _sse({"event": "error", "message": "Пользователь не найден"})
                return
            stream = service.stream_reply(
                stream_db,
                stream_user,
                payload.message,
                conversation_id=payload.conversation_id,
                selected_date=payload.selected_date,
            )
            async for event in stream:
                if await request.is_disconnected():
                    await stream.aclose()
                    return
                yield _sse(event)
        except LLMError as exc:
            yield _sse({"event": "error", "message": str(exc)})
        except Exception:
            logger.exception("AI streaming request failed")
            yield _sse({"event": "error", "message": "Не удалось получить ответ AI-провайдера"})
        finally:
            stream_db.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[ConversationResponse])
def conversations(user: CurrentUser, db: DbSession):
    return db.scalars(
        select(AIConversation)
        .where(AIConversation.user_id == user.id)
        .order_by(AIConversation.updated_at.desc())
    ).all()


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def new_conversation(payload: ConversationCreate, user: CurrentUser, db: DbSession):
    return ChatService.create_conversation(db, user.id, payload.title)


@router.get("/conversations/{conversation_id}/messages", response_model=list[AIMessageResponse])
def conversation_messages(conversation_id: int, user: CurrentUser, db: DbSession):
    try:
        ChatService.get_conversation(db, user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return db.scalars(
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation_id, AIMessage.user_id == user.id)
        .order_by(AIMessage.created_at)
    ).all()


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, user: CurrentUser, db: DbSession):
    try:
        conversation = ChatService.get_conversation(db, user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.delete(conversation)
    db.commit()
    return Response(status_code=204)


def _owned_proposal(db: DbSession, user_id: int, proposal_id: int) -> AIActionProposal:
    proposal = db.scalar(
        select(AIActionProposal).where(AIActionProposal.id == proposal_id, AIActionProposal.user_id == user_id)
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail="Предложение действия не найдено")
    return proposal


@router.patch("/action-proposals/{proposal_id}", response_model=ActionProposalResponse)
def edit_proposal(
    proposal_id: int, payload: ActionProposalUpdate, user: CurrentUser, db: DbSession
):
    proposal = _owned_proposal(db, user.id, proposal_id)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="Предложение уже обработано")
    if payload.payload is not None:
        proposal.payload = json.dumps(payload.payload, ensure_ascii=False)[:8000]
    if payload.status == "cancelled":
        proposal.status = "cancelled"
    db.commit()
    db.refresh(proposal)
    return proposal


@router.post("/action-proposals/{proposal_id}/confirm", response_model=ActionProposalResponse)
def confirm_proposal(proposal_id: int, user: CurrentUser, db: DbSession):
    proposal = _owned_proposal(db, user.id, proposal_id)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="Предложение уже обработано")
    try:
        data = json.loads(proposal.payload)
        if proposal.type == "calendar_action_proposal":
            start_at = to_utc(datetime.fromisoformat(str(data["start_at"])), user.timezone)
            end_at = to_utc(datetime.fromisoformat(str(data["end_at"])), user.timezone)
            if end_at <= start_at:
                raise ValueError("Некорректный временной интервал")
            db.add(Event(
                user_id=user.id,
                title=str(data.get("title") or proposal.title)[:200],
                description=str(data.get("description") or proposal.description)[:2000],
                start_at=start_at,
                end_at=end_at,
                category=str(data.get("category") or "personal")[:40],
                color="#6C5CE7",
            ))
        elif proposal.type == "task_action_proposal":
            db.add(Task(
                user_id=user.id,
                title=str(data.get("title") or proposal.title)[:240],
                notes=str(data.get("description") or proposal.description)[:2000],
                priority=str(data.get("priority") or "medium"),
                estimate_minutes=max(5, min(1440, int(data.get("estimate_minutes") or 30))),
            ))
        else:
            raise ValueError("Этот тип действия пока нельзя выполнить автоматически")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc) or "Предложению не хватает данных") from exc
    proposal.status = "confirmed"
    db.commit()
    db.refresh(proposal)
    return proposal
