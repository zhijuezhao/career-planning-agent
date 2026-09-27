from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.config import get_settings
from app.core.agent.langgraph_agent import compile_agent
from app.core.agent.nodes import AgentState
from app.core.agent.tools import get_agent_tools
from app.core.chat.router import route
from app.core.chat.viz import normalise_viz
from app.core.chat.workflows import WorkflowContext, run_workflow
from app.core.llm.gateway import LLMGatewayError, get_llm_gateway
from app.core.safety.filter import append_disclaimer, check_content
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
- 当用户询问岗位匹配、职业路线或报告生成时，主动使用相应工具
- **需要事实（岗位要求、知识库内容、报告数据）时先调用工具再回答**，不要只凭记忆作答
- 工具返回的是真实数据：要转述其中关键信息（岗位/公司/评分/结论），不要只说"我查到了\""""


def _sse(payload: dict[str, Any]) -> str:
    """统一的 SSE 事件编码（前端按 `data: ` 逐行解析）。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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

    SSE 事件契约：
    - ``{"type": "token", "content": "..."}`` — 文本增量（含最后追加的免责声明）
    - ``{"type": "tool", "phase": "start"|"end", "name": "..."}`` — **模型正在调用工具**
      （前端 switch 没有 default 分支 → 老版本前端会安全忽略它）
    - ``{"type": "viz", "kind": "radar|bar|line|pie|table", ...}`` — **可视化载荷**（C1）
      一条消息可以有多个；``kind`` 决定渲染方式（ECharts 图用 ``option``，表格用
      ``columns`` + ``rows``）。契约见 ``app/core/chat/viz.py``。同样靠"未知类型忽略"
      向后兼容。**同时落库**（``chat_messages.viz``），否则刷新后图就没了。
    - ``{"type": "done", "session_id": "...", "message_id": N}`` — 结束
    - ``{"type": "error", "content": "..."}`` — 出错

    执行链（2026-09-25 修复"agent 链失效"；2026-09-27 C1 加 L1 路由与 viz）：
    ① 输入侧内容安全（确定性规则，命中即拒答、不调模型）；
    ② **L1 意图路由**（``core/chat/router.py``，纯规则、0 token）：命中 → 跑
       **确定型工作流**（``core/chat/workflows.py``，只查 DB），**完全不碰模型**；
       未命中 → ReAct agent（模型自主决定是否/如何调用工具）；
    ③ 输出侧合规：追加免责声明（幂等），命中违规规则时额外提示并记 warning。
    """
    chat_session = await get_chat_session(db, session_id, current_user.id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    # Save user message
    await save_chat_message(db, session_id, "user", data.content)
    await db.commit()

    gateway = get_llm_gateway()
    settings_obj = get_settings()
    # L1 路由：纯函数、无 I/O、0 token。命中就**不建 agent、不调模型**（§11 原则）
    decision = route(data.content)

    async def event_stream():
        assistant_content = ""
        assistant_viz: list[dict[str, Any]] | None = None
        # 落库的 model_used：工作流答的会写成 "workflow:<名字>"，管理端一眼能分辨
        model_used: str | None = gateway.current_model
        message_id: int | None = None

        async def save_assistant() -> str:
            """落库助手消息并返回 done 事件（流式结束后才有完整内容）。"""
            nonlocal message_id
            assistant_msg = await save_chat_message(
                db,
                session_id,
                "assistant",
                assistant_content,
                tokens_used=0,
                model_used=model_used,
                viz=assistant_viz,
            )
            message_id = assistant_msg.id
            await db.commit()
            return _sse(
                {"type": "done", "session_id": str(session_id), "message_id": message_id}
            )

        try:
            # ── ① 输入侧内容安全：命中即拒答（不把违规诉求喂给模型）──────────────
            safety = check_content(data.content)
            if not safety.is_safe:
                assistant_content = (
                    f"抱歉，你提到的内容涉及「{safety.reason}」，我不能据此提供建议。"
                    "职业建议应当基于岗位要求与个人能力本身，而不是性别、地域、婚育等限制条件。"
                    "你可以把岗位要求原文发给我，我帮你分析需要补哪些能力。"
                )
                logger.info(
                    "Chat 输入命中安全规则，直接拒答 | session_id={} | type={}",
                    session_id,
                    safety.violation_type,
                )
                yield _sse({"type": "token", "content": assistant_content})
            elif decision.is_workflow:
                # ── ②-L1 确定型工作流：0 token，**不进 agent**（§11 原则）──────────
                result = await run_workflow(
                    decision.workflow or "",
                    db,
                    WorkflowContext(params=decision.params, user_id=current_user.id),
                )
                assistant_content = result.text
                assistant_viz = normalise_viz(result.viz) or None
                model_used = f"workflow:{decision.workflow}"
                logger.info(
                    "Chat L1 命中工作流（0 token，未调模型）| session_id={} | rule={} | workflow={} | viz={}",
                    session_id,
                    decision.rule,
                    decision.workflow,
                    len(assistant_viz or []),
                )
                yield _sse({"type": "token", "content": assistant_content})
                for item in assistant_viz or []:
                    yield _sse({"type": "viz", **item})
            else:
                # ── ② ReAct agent：模型自主决策调用哪些工具 ────────────────────
                tools = get_agent_tools()
                llm_with_tools = gateway.get_model().bind_tools(tools)
                agent = compile_agent(llm_with_tools, tools)

                config: dict[str, Any] = {
                    "configurable": {
                        "llm": llm_with_tools,
                        "tools_by_name": {t.name: t for t in tools},
                        # 工具需要的运行时身份（模型不可能自己知道）
                        "user_id": current_user.id,
                        "db": db,
                    },
                    # 步数上限：防 ReAct 反复调工具烧 token
                    "recursion_limit": settings_obj.chat_agent_recursion_limit,
                }

                messages_for_llm: list[BaseMessage] = [SystemMessage(content=_CAREER_SYSTEM_PROMPT)]
                for msg in await get_chat_messages(db, session_id):
                    if msg.role == "user":
                        messages_for_llm.append(HumanMessage(content=msg.content))
                    elif msg.role == "assistant":
                        messages_for_llm.append(AIMessage(content=msg.content))

                initial_state: AgentState = {"messages": messages_for_llm, "next": "tools"}

                async for event in agent.astream_events(
                    initial_state, config=config, version="v2"
                ):
                    # ⚠️ LangChain `astream_events` 的事件字典用 **`event`** 键表示事件名
                    # （键集合：data/event/metadata/name/parent_ids/run_id/tags）。
                    # 历史实现读的是 `kind` —— 该键根本不存在 → 所有事件都被当成 ""，
                    # token 与 tool 全被丢弃（线上表现：回答里只剩追加的免责声明）。
                    kind = event.get("event", "")

                    if kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk", {})
                        content = chunk.get("content", "") if isinstance(chunk, dict) else ""
                        if not content and hasattr(chunk, "content"):
                            content = chunk.content
                        if content:
                            assistant_content += content
                            yield _sse({"type": "token", "content": content})

                    elif kind in ("on_tool_start", "on_tool_end"):
                        tool_name = event.get("name", "unknown")
                        phase = "start" if kind == "on_tool_start" else "end"
                        logger.info(
                            "Agent tool {} | tool={} | session_id={}",
                            phase,
                            tool_name,
                            session_id,
                        )
                        yield _sse({"type": "tool", "phase": phase, "name": tool_name})

            # ── ③ 输出侧合规：统一追加免责声明（幂等）──────────────────────────
            output_safety = check_content(assistant_content)
            if not output_safety.is_safe:
                logger.warning(
                    "Chat 输出命中安全规则 | session_id={} | type={} | matched={!r}",
                    session_id,
                    output_safety.violation_type,
                    output_safety.matched_text,
                )

            tail = append_disclaimer(assistant_content)
            if not output_safety.is_safe:
                tail += (
                    f"\n\n> 提示：上文中「{output_safety.matched_text}」这类表述存在合规风险，"
                    "请以岗位实际要求为准。"
                )
            suffix = tail[len(assistant_content):]
            if suffix:
                assistant_content = tail
                yield _sse({"type": "token", "content": suffix})

            yield await save_assistant()

        except LLMGatewayError as exc:
            # ② 之后"没有默认模型"是常见配置态：给学生一句能懂的提示，细节留给日志
            await db.rollback()
            logger.error("Chat LLM 网关不可用 | session_id={} | error={}", session_id, exc)
            yield _sse(
                {
                    "type": "error",
                    "content": "AI 服务暂不可用（管理员尚未绑定默认模型），请稍后再试",
                }
            )
        except Exception:
            await db.rollback()
            logger.exception("Chat SSE error | session_id={}", session_id)
            yield _sse({"type": "error", "content": "服务暂时不可用，请稍后重试"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
