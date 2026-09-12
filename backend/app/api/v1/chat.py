from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.core.agent.langgraph_agent import compile_agent
from app.core.agent.tools import AGENT_TOOLS
from app.core.llm.gateway import get_llm_gateway
from app.domain.models.user import User
from app.domain.services.chat_service import (
    create_chat_session,
    delete_chat_session,
    get_chat_messages,
    get_chat_session,
    list_chat_sessions,
    save_chat_message,
)
from app.infrastructure.database import get_db
from app.schemas.chat import (
    ChatRequest,
    ChatSessionCreate,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
)

router = APIRouter()

_CAREER_SYSTEM_PROMPT = """你是一名专业的大学生职业规划助手。你的职责是：
1. 帮助大学生了解不同职业方向的发展路径和技能要求
2. 根据学生的专业背景和兴趣，提供个性化的职业建议
3. 分析行业趋势，推荐适合的实习和就业方向
4. 指导简历优化、面试准备和职业素养提升
5. 可以使用工具查询职业知识库、用户画像、人岗匹配、职业路线规划和报告生成

回答时请注意：
- 保持专业、客观、鼓励的态度
- 基于事实和数据提供建议
- 如果涉及具体岗位要求，引用可靠来源
- 对于不确定的信息，明确说明
- 语言简洁明了，适合大学生理解
- 当用户询问岗位匹配、职业路线或报告生成时，主动使用相应工具"""


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def api_create_session(
    data: ChatSessionCreate,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session."""
    chat_session = await create_chat_session(db, current_user.id, data.title)
    await db.commit()
    return chat_session


@router.get("/sessions", response_model=ChatSessionListResponse)
async def api_list_sessions(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all chat sessions for the current user."""
    items, total = await list_chat_sessions(db, current_user.id, skip, limit)
    return {"total": total, "items": items}


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def api_get_session(
    session_id: UUID,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get a chat session with all its messages."""
    chat_session = await get_chat_session(db, session_id, current_user.id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await get_chat_messages(db, session_id)
    return {
        "id": chat_session.id,
        "title": chat_session.title,
        "messages": messages,
        "created_at": chat_session.created_at,
        "updated_at": chat_session.updated_at,
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def api_delete_session(
    session_id: UUID,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Delete a chat session and all its messages."""
    deleted = await delete_chat_session(db, session_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.commit()


@router.post("/sessions/{session_id}/messages")
async def api_send_message(
    session_id: UUID,
    data: ChatRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Send a message and stream the AI response via SSE.

    Returns a Server-Sent Events stream with events:
    - ``{"type": "token", "content": "..."}`` — each token chunk.
    - ``{"type": "done", "session_id": "...", "message_id": N}`` — stream complete.
    - ``{"type": "error", "content": "..."}`` — error occurred.
    """
    chat_session = await get_chat_session(db, session_id, current_user.id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # Save user message
    await save_chat_message(db, session_id, "user", data.content)
    await db.commit()

    gateway = get_llm_gateway()
    llm = gateway.get_model()
    llm_with_tools = llm.bind_tools(AGENT_TOOLS)

    async def event_stream():
        assistant_content = ""
        message_id: int | None = None

        try:
            # Build message list: system prompt + history + current user message
            messages_for_llm = [SystemMessage(content=_CAREER_SYSTEM_PROMPT)]

            history = await get_chat_messages(db, session_id)
            for msg in history:
                if msg.role == "user":
                    messages_for_llm.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    from langchain_core.messages import AIMessage

                    messages_for_llm.append(AIMessage(content=msg.content))

            # Create tools lookup dict with db session injected
            tools_by_name = {}
            for tool in AGENT_TOOLS:
                tools_by_name[tool.name] = tool

            # Use LangGraph Agent with streaming
            from app.core.agent.nodes import AgentState

            initial_state: AgentState = {
                "messages": messages_for_llm,
                "next": "tools",
            }

            agent = compile_agent(llm_with_tools, AGENT_TOOLS)

            async for event in agent.astream_events(initial_state, version="v2"):
                kind = event.get("kind", "")

                # Handle chat model stream events (token chunks)
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", {})
                    content = chunk.get("content", "") if isinstance(chunk, dict) else ""
                    if not content and hasattr(chunk, "content"):
                        content = chunk.content
                    if content:
                        assistant_content += content
                        yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"

                # Handle tool execution events
                elif kind == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    logger.info("Agent tool executed | tool={}", tool_name)

            # Save assistant message
            assistant_msg = await save_chat_message(
                db, session_id, "assistant", assistant_content,
                tokens_used=0, model_used=gateway.current_model,
            )
            message_id = assistant_msg.id
            await db.commit()

            done_data = {
                "type": "done",
                "session_id": str(session_id),
                "message_id": message_id,
            }
            yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

        except Exception as exc:
            await db.rollback()
            logger.error("Chat SSE error | session_id={} | error={}", session_id, exc)
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
