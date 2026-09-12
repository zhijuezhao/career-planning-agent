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
from langchain_core.messages import AIMessage

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
                "kind": "on_chat_model_stream",
                "data": {"chunk": {"content": "你好"}},
            }
            yield {
                "kind": "on_chat_model_stream",
                "data": {"chunk": {"content": "！"}},
            }
            yield {
                "kind": "on_chat_model_stream",
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
