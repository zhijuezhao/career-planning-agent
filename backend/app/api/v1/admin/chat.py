from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.report import ChatMessage, ChatSession
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    ChatMessageListResponse,
    ChatMessageResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
)

router = APIRouter()


# ── Chat Sessions ───────────────────────────────────────────────────────────


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    start: datetime | None = Query(None, description="创建时间下限（含），ISO8601"),
    end: datetime | None = Query(None, description="创建时间上限（含），ISO8601"),
    keyword: str | None = Query(None, description="按标题或摘要模糊搜索"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """会话列表（P1-5：支持时间范围与关键字筛选）。"""
    query = select(ChatSession)
    count_query = select(func.count()).select_from(ChatSession)

    if user_id is not None:
        query = query.where(ChatSession.user_id == user_id)
        count_query = count_query.where(ChatSession.user_id == user_id)
    if start is not None:
        query = query.where(ChatSession.created_at >= start)
        count_query = count_query.where(ChatSession.created_at >= start)
    if end is not None:
        query = query.where(ChatSession.created_at <= end)
        count_query = count_query.where(ChatSession.created_at <= end)
    if keyword:
        like = f"%{keyword}%"
        cond = or_(ChatSession.title.like(like), ChatSession.summary.like(like))
        query = query.where(cond)
        count_query = count_query.where(cond)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(ChatSession.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return ChatSessionListResponse(
        total=total,
        items=[ChatSessionResponse.model_validate(i) for i in items],
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(
    session_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single chat session by ID."""
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a chat session."""
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    await db.delete(session)
    await db.flush()


# ── Chat Messages ───────────────────────────────────────────────────────────


@router.get("/messages", response_model=ChatMessageListResponse)
async def list_chat_messages(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    session_id: UUID | None = None,
    role: Literal["user", "assistant", "system"] | None = Query(
        None, description="角色过滤（非法值自动 422）"
    ),
    start: datetime | None = Query(None, description="创建时间下限（含），ISO8601"),
    end: datetime | None = Query(None, description="创建时间上限（含），ISO8601"),
    keyword: str | None = Query(None, description="按消息内容模糊搜索"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """消息列表（P1-5：支持会话/角色/时间范围/关键字筛选）。"""
    query = select(ChatMessage)
    count_query = select(func.count()).select_from(ChatMessage)

    if session_id is not None:
        query = query.where(ChatMessage.session_id == session_id)
        count_query = count_query.where(ChatMessage.session_id == session_id)
    if role is not None:
        query = query.where(ChatMessage.role == role)
        count_query = count_query.where(ChatMessage.role == role)
    if start is not None:
        query = query.where(ChatMessage.created_at >= start)
        count_query = count_query.where(ChatMessage.created_at >= start)
    if end is not None:
        query = query.where(ChatMessage.created_at <= end)
        count_query = count_query.where(ChatMessage.created_at <= end)
    if keyword:
        like = f"%{keyword}%"
        query = query.where(ChatMessage.content.like(like))
        count_query = count_query.where(ChatMessage.content.like(like))

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(ChatMessage.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return ChatMessageListResponse(
        total=total,
        items=[ChatMessageResponse.model_validate(i) for i in items],
    )


@router.get("/messages/{message_id}", response_model=ChatMessageResponse)
async def get_chat_message(
    message_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single chat message by ID."""
    message = await db.get(ChatMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Chat message not found")
    return message
