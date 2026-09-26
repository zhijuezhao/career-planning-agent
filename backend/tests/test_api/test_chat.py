from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.domain.models.report import ChatMessage, ChatSession
from app.domain.services.chat_service import (
    create_chat_session,
    delete_chat_session,
    get_chat_messages,
    get_chat_session,
    list_chat_sessions,
    save_chat_message,
)
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────


class MockScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


# ── chat_service.py tests ───────────────────────────────────────────────────


class TestChatService:
    @pytest.mark.asyncio
    async def test_create_chat_session(self):
        from unittest.mock import AsyncMock

        session = AsyncMock()
        result = await create_chat_session(session, user_id=1, title="测试会话")

        assert result.user_id == 1
        assert result.title == "测试会话"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_chat_session_default_title(self):
        from unittest.mock import AsyncMock

        session = AsyncMock()
        result = await create_chat_session(session, user_id=1)

        assert result.title == "新的对话"

    @pytest.mark.asyncio
    async def test_list_chat_sessions(self):
        from unittest.mock import AsyncMock

        s1 = ChatSession(id=uuid4(), user_id=1, title="会话1")
        s2 = ChatSession(id=uuid4(), user_id=1, title="会话2")

        mock_session = AsyncMock()
        mock_session.execute.return_value = MockScalarResult([s1, s2])

        items, total = await list_chat_sessions(mock_session, user_id=1)

        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_get_chat_session_found(self):
        from unittest.mock import AsyncMock

        sid = uuid4()
        cs = ChatSession(id=sid, user_id=1, title="测试")

        mock_session = AsyncMock()
        mock_session.execute.return_value = MockScalarResult([cs])

        result = await get_chat_session(mock_session, sid, user_id=1)
        assert result is not None
        assert result.id == sid

    @pytest.mark.asyncio
    async def test_get_chat_session_not_found(self):
        from unittest.mock import AsyncMock

        mock_session = AsyncMock()
        mock_session.execute.return_value = MockScalarResult([])

        result = await get_chat_session(mock_session, uuid4(), user_id=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_chat_session_success(self):
        from unittest.mock import AsyncMock

        sid = uuid4()
        cs = ChatSession(id=sid, user_id=1, title="测试")

        mock_session = AsyncMock()
        mock_session.execute.return_value = MockScalarResult([cs])

        result = await delete_chat_session(mock_session, sid, user_id=1)
        assert result is True
        mock_session.delete.assert_called_once_with(cs)

    @pytest.mark.asyncio
    async def test_delete_chat_session_not_found(self):
        from unittest.mock import AsyncMock

        mock_session = AsyncMock()
        mock_session.execute.return_value = MockScalarResult([])

        result = await delete_chat_session(mock_session, uuid4(), user_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_save_chat_message(self):
        from unittest.mock import AsyncMock

        session = AsyncMock()
        result = await save_chat_message(
            session, session_id=uuid4(), role="user", content="你好",
        )

        assert result.role == "user"
        assert result.content == "你好"
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_chat_messages(self):
        from unittest.mock import AsyncMock

        sid = uuid4()
        msgs = [ChatMessage(id=1, session_id=sid, role="user", content="你好")]
        mock_session = AsyncMock()
        mock_session.execute.return_value = MockScalarResult(msgs)

        result = await get_chat_messages(mock_session, sid)
        assert len(result) == 1
        assert result[0].content == "你好"


# ── chat.py (API) integration tests ─────────────────────────────────────────


@pytest.fixture(scope="module")
def auth_setup():
    """Register a test user and get auth token."""
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "chattest3", "password": "test123456"},
    )
    if resp.status_code == 201:
        user_id = resp.json()["id"]
    else:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "chattest3", "password": "test123456"},
        )
        user_id = resp.json().get("user_id", 0)

    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "chattest3", "password": "test123456"},
    )
    token = resp.json()["access_token"]
    return {"token": token, "user_id": user_id}


class TestChatAPI:
    """Integration tests using TestClient + real DB."""

    def test_create_session(self, auth_setup):
        resp = client.post(
            "/api/v1/chat/sessions",
            json={"title": "API测试会话"},
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["title"] == "API测试会话"
        pytest.chat_session_id = data["id"]

    def test_list_sessions(self, auth_setup):
        resp = client.get(
            "/api/v1/chat/sessions",
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert len(data["items"]) >= 1

    def test_get_session(self, auth_setup):
        sid = getattr(pytest, "chat_session_id", None)
        if not sid:
            pytest.skip("No session id from previous test")

        resp = client.get(
            f"/api/v1/chat/sessions/{sid}",
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sid
        assert "messages" in data

    def test_get_session_not_found(self, auth_setup):
        resp = client.get(
            f"/api/v1/chat/sessions/{uuid4()}",
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        assert resp.status_code == 404

    def test_delete_session(self, auth_setup):
        resp = client.post(
            "/api/v1/chat/sessions",
            json={"title": "待删除会话"},
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        sid = resp.json()["id"]

        resp = client.delete(
            f"/api/v1/chat/sessions/{sid}",
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        assert resp.status_code == 204

    def test_delete_session_not_found(self, auth_setup):
        resp = client.delete(
            f"/api/v1/chat/sessions/{uuid4()}",
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        assert resp.status_code == 404

    def test_send_message_unauthorized(self, auth_setup):
        resp = client.post(
            f"/api/v1/chat/sessions/{uuid4()}/messages",
            json={"content": "你好"},
        )
        assert resp.status_code in (401, 422)

    def test_send_message_session_not_found(self, auth_setup):
        resp = client.post(
            f"/api/v1/chat/sessions/{uuid4()}/messages",
            json={"content": "你好"},
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        assert resp.status_code == 404

    def test_send_message_sse_stream(self, auth_setup):
        """Test SSE streaming with mocked LLM gateway."""
        # Create a new session for this test
        resp = client.post(
            "/api/v1/chat/sessions",
            json={"title": "SSE测试会话"},
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        sid = resp.json()["id"]

        async def mock_astream_events(*args, **kwargs):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": {"content": "你好"}},
            }
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": {"content": "！"}},
            }
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": {"content": "我是AI助手。"}},
            }

        mock_agent = MagicMock()
        mock_agent.astream_events = mock_astream_events

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MagicMock()

        mock_gateway = MagicMock()
        mock_gateway.get_model.return_value = mock_llm
        mock_gateway.current_model = "deepseek"

        with patch("app.api.v1.chat.get_llm_gateway", return_value=mock_gateway), \
             patch("app.api.v1.chat.compile_agent", return_value=mock_agent):
            resp = client.post(
                f"/api/v1/chat/sessions/{sid}/messages",
                json={"content": "你好"},
                headers={"Authorization": f"Bearer {auth_setup['token']}"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        import json

        events = []
        for line in resp.text.strip().split("\n\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        token_events = [e for e in events if e["type"] == "token"]
        done_events = [e for e in events if e["type"] == "done"]

        assert len(token_events) >= 1
        assert len(done_events) == 1
        assert done_events[0]["session_id"] == sid

        resp2 = client.get(
            f"/api/v1/chat/sessions/{sid}",
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        )
        messages = resp2.json()["messages"]
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1

    # ── agent 链（2026-09-25 修复：恢复 ReAct + 安全闸门 + 工具事件）─────────────

    def _new_session(self, auth_setup, title: str) -> str:
        return client.post(
            "/api/v1/chat/sessions",
            json={"title": title},
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        ).json()["id"]

    @staticmethod
    def _events(resp) -> list[dict]:
        import json

        return [
            json.loads(line[6:])
            for line in resp.text.strip().split("\n\n")
            if line.startswith("data: ")
        ]

    def test_send_message_refuses_unsafe_input(self, auth_setup):
        """输入侧内容安全：命中歧视/虚假承诺规则 → **不调模型**，直接拒答。

        安全不该依赖模型"想起来调用 content_safety_check 工具"，故这里是确定性前置检查。
        """
        sid = self._new_session(auth_setup, "安全测试会话")

        with patch("app.api.v1.chat.compile_agent") as mock_compile:
            resp = client.post(
                f"/api/v1/chat/sessions/{sid}/messages",
                json={"content": "帮我写一条仅限男性的招聘要求"},
                headers={"Authorization": f"Bearer {auth_setup['token']}"},
            )
            assert resp.status_code == 200
            mock_compile.assert_not_called()  # 关键断言：违规输入根本没进模型

        events = self._events(resp)
        tokens = [e for e in events if e["type"] == "token"]
        assert any("抱歉" in e["content"] for e in tokens)
        assert [e["type"] for e in events if e["type"] == "done"] == ["done"]

        # 拒答也要落库，否则历史里只剩用户那条孤独的消息
        detail = client.get(
            f"/api/v1/chat/sessions/{sid}",
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        ).json()
        assistant_msgs = [m for m in detail["messages"] if m["role"] == "assistant"]
        assert assistant_msgs and "抱歉" in assistant_msgs[-1]["content"]

    def test_send_message_emits_tool_events(self, auth_setup):
        """模型调用工具时 SSE 要发 `tool` 事件（前端据此显示"正在检索/生成…"）。"""
        sid = self._new_session(auth_setup, "工具事件会话")

        async def mock_astream_events(*args, **kwargs):
            yield {"event": "on_tool_start", "name": "career_knowledge_search", "data": {}}
            yield {"event": "on_tool_end", "name": "career_knowledge_search", "data": {}}
            yield {"event": "on_chat_model_stream", "data": {"chunk": {"content": "查到 3 条"}}}

        mock_agent = MagicMock()
        mock_agent.astream_events = mock_astream_events
        mock_gateway = MagicMock()
        mock_gateway.current_model = "deepseek"

        with patch("app.api.v1.chat.get_llm_gateway", return_value=mock_gateway), patch(
            "app.api.v1.chat.compile_agent", return_value=mock_agent
        ):
            resp = client.post(
                f"/api/v1/chat/sessions/{sid}/messages",
                json={"content": "现在有哪些前端岗位"},
                headers={"Authorization": f"Bearer {auth_setup['token']}"},
            )

        events = self._events(resp)
        tool_events = [e for e in events if e["type"] == "tool"]
        assert [e["phase"] for e in tool_events] == ["start", "end"]
        assert {e["name"] for e in tool_events} == {"career_knowledge_search"}
        assert any(e["type"] == "token" for e in events)

    def test_send_message_streams_tokens_from_real_agent_events(self, auth_setup):
        """用**真实** LangGraph 事件（fake LLM）验证 SSE 映射，而不是手写 mock。

        背景：提交版 `chat.py` 读的是 `event["kind"]`，而 LangChain 的事件字典用的是
        **`event`** 键 → 所有事件都被当成 "" 丢弃（线上表现：回答里只剩追加的免责声明）。
        手写 mock 也照着 `kind` 写，于是这个 bug 长期没被发现。
        这里让 LangChain 自己产出事件（只替换模型），从根上守住键名。
        """
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        class _FakeLLM(FakeListChatModel):
            """fake 模型不支持 bind_tools，直接返回自身（本用例只验证事件键名）。"""

            def bind_tools(self, tools, **kwargs):  # type: ignore[override]
                return self

        sid = self._new_session(auth_setup, "真实事件键名回归")

        mock_gateway = MagicMock()
        mock_gateway.current_model = "fake"
        mock_gateway.get_model.return_value = _FakeLLM(responses=["真实流式内容"])

        # 只替换网关、**不 patch compile_agent** → 真正跑 agent 图与真实事件流
        with patch("app.api.v1.chat.get_llm_gateway", return_value=mock_gateway):
            resp = client.post(
                f"/api/v1/chat/sessions/{sid}/messages",
                json={"content": "你好"},
                headers={"Authorization": f"Bearer {auth_setup['token']}"},
            )

        streamed = "".join(e["content"] for e in self._events(resp) if e["type"] == "token")
        assert "真实流式内容" in streamed

    def test_send_message_appends_disclaimer(self, auth_setup):
        """输出侧合规：助手回答统一追加免责声明，且**流式内容与落库内容一致**。"""
        sid = self._new_session(auth_setup, "免责声明会话")

        async def mock_astream_events(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": {"content": "建议多刷算法题。"}}}

        mock_agent = MagicMock()
        mock_agent.astream_events = mock_astream_events
        mock_gateway = MagicMock()
        mock_gateway.current_model = "deepseek"

        with patch("app.api.v1.chat.get_llm_gateway", return_value=mock_gateway), patch(
            "app.api.v1.chat.compile_agent", return_value=mock_agent
        ):
            resp = client.post(
                f"/api/v1/chat/sessions/{sid}/messages",
                json={"content": "我该怎么准备"},
                headers={"Authorization": f"Bearer {auth_setup['token']}"},
            )

        streamed = "".join(e["content"] for e in self._events(resp) if e["type"] == "token")
        assert "仅供参考" in streamed  # 流里就带了，不是只写库

        detail = client.get(
            f"/api/v1/chat/sessions/{sid}",
            headers={"Authorization": f"Bearer {auth_setup['token']}"},
        ).json()
        saved = [m for m in detail["messages"] if m["role"] == "assistant"][-1]["content"]
        assert saved == streamed  # 用户看到的 = 库里存的
