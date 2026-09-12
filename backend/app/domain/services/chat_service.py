from __future__ import annotations

from uuid import UUID

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.report import ChatMessage, ChatSession


async def create_chat_session(
    session: AsyncSession,
    user_id: int,
    title: str | None = None,
) -> ChatSession:
    chat_session = ChatSession(user_id=user_id, title=title or "新的对话")
    session.add(chat_session)
    await session.flush()
    logger.info("Chat session created | id={} | user_id={}", chat_session.id, user_id)
    return chat_session


async def list_chat_sessions(
    session: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[ChatSession], int]:
    total = (
        await session.execute(
            select(ChatSession).where(ChatSession.user_id == user_id)
        )
    ).scalars().all()
    total_count = len(total)

    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = (await session.execute(stmt)).scalars().all()
    return list(items), total_count


async def get_chat_session(
    session: AsyncSession,
    session_id: UUID,
    user_id: int,
) -> ChatSession | None:
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == user_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def delete_chat_session(
    session: AsyncSession,
    session_id: UUID,
    user_id: int,
) -> bool:
    chat_session = await get_chat_session(session, session_id, user_id)
    if chat_session is None:
        return False

    await session.execute(
        delete(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    await session.delete(chat_session)
    await session.flush()
    logger.info("Chat session deleted | id={} | user_id={}", session_id, user_id)
    return True


async def get_chat_messages(
    session: AsyncSession,
    session_id: UUID,
) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return (await session.execute(stmt)).scalars().all()


async def save_chat_message(
    session: AsyncSession,
    session_id: UUID,
    role: str,
    content: str,
    tokens_used: int = 0,
    model_used: str | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        tokens_used=tokens_used,
        model_used=model_used,
    )
    session.add(msg)
    await session.flush()
    return msg
