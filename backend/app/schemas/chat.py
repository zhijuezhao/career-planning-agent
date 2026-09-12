from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    title: str | None = Field(None, max_length=100)


class ChatSessionResponse(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ChatSessionListResponse(BaseModel):
    total: int
    items: list[ChatSessionResponse]


class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    model_config = {"from_attributes": True}


class ChatSessionDetailResponse(BaseModel):
    id: UUID
    title: str | None
    messages: list[ChatMessageResponse]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
