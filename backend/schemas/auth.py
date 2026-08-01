from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.schemas.common import ORMModel
from backend.services.time import validate_timezone


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=2, max_length=120)
    timezone: str = "Europe/Moscow"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        return validate_timezone(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class UserResponse(ORMModel):
    id: int
    email: EmailStr
    name: str
    timezone: str
    occupation: str | None
    avatar_color: str
    email_verified: bool
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    timezone: str | None = None
    occupation: str | None = Field(default=None, max_length=160)
    avatar_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        return validate_timezone(value) if value is not None else None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str | None
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class EmailRequest(BaseModel):
    email: EmailStr


class OneTimeTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class PasswordResetRequest(OneTimeTokenRequest):
    new_password: str = Field(min_length=12, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


class MessageResponse(BaseModel):
    message: str
