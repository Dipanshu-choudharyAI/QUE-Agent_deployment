"""Chat request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ChatRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(min_length=1, max_length=32_000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("content must not be empty")
        return cleaned


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    conversation_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(
        default=None,
        max_length=64,
        description="Opaque Quizzer user id for audit/rate-limit only — never used for DB access",
    )


class ChatResponse(BaseModel):
    message: ChatMessage
    conversation_id: str | None = None
    model: str
    knowledge_packs: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)


class ErrorBody(BaseModel):
    detail: str
