from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import AIActionProposal, Event, Task, User
from backend.services.time import to_utc


def execute_action_proposal(db: Session, user: User, proposal: AIActionProposal) -> AIActionProposal:
    if proposal.status != "pending":
        raise ValueError("Предложение уже обработано")
    try:
        data = json.loads(proposal.payload)
        if proposal.type == "calendar_action_proposal":
            start_at = to_utc(datetime.fromisoformat(str(data["start_at"])), user.timezone)
            end_at = to_utc(datetime.fromisoformat(str(data["end_at"])), user.timezone)
            if end_at <= start_at:
                raise ValueError("Некорректный временной интервал")
            title = str(data.get("title") or proposal.title)[:200]
            existing = db.scalar(select(Event).where(
                Event.user_id == user.id,
                Event.title == title,
                Event.start_at == start_at,
                Event.end_at == end_at,
            ))
            if existing is None:
                db.add(Event(
                    user_id=user.id,
                    title=title,
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
        raise ValueError(str(exc) or "Предложению не хватает данных") from exc
    proposal.status = "confirmed"
    db.commit()
    db.refresh(proposal)
    return proposal
