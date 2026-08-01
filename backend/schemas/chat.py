from datetime import date, datetime

from pydantic import BaseModel, Field

from backend.schemas.common import ORMModel


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    selected_date: date | None = None


class ChatMessageResponse(ORMModel):
    id: int
    role: str
    content: str
    created_at: datetime
