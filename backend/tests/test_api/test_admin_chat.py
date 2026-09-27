
from unittest.mock import MagicMock, patch

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestChatSessionsAPI:
    def test_list_chat_sessions(self, admin_token: str, client: TestClient):
        """Test listing chat sessions."""
        resp = client.get(
            "/api/v1/admin/chat/sessions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_filter_sessions_by_user(self, admin_token: str, client: TestClient):
        """Test filtering chat sessions by user_id."""
        resp = client.get(
            "/api/v1/admin/chat/sessions?user_id=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["user_id"] == 1 for item in data["items"])

    def test_get_chat_session_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent chat session."""
        resp = client.get(
            "/api/v1/admin/chat/sessions/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


class TestChatMessagesAPI:
    def test_list_chat_messages(self, admin_token: str, client: TestClient):
        """Test listing chat messages."""
        resp = client.get(
            "/api/v1/admin/chat/messages",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_get_chat_message_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent chat message."""
        resp = client.get(
            "/api/v1/admin/chat/messages/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


class TestChatVizExposureC1:
    """C1：L1 工作流产出的 viz，管理端「对话记录」必须读得到。

    这条链路就是**挂载点 A 的数据源**：学生端提问 → L1 命中工作流 → viz 落库 →
    管理端拿 `GET /admin/chat/messages?session_id=...` 渲染图表。
    """

    def test_workflow_viz_reaches_admin_message_list(
        self, student_token: str, admin_token: str, client: TestClient
    ):
        created = client.post(
            "/api/v1/chat/sessions",
            json={"title": "C1 viz 落库验证"},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert created.status_code == 201, created.text
        sid = created.json()["id"]

        mock_gateway = MagicMock()
        mock_gateway.current_model = "deepseek"
        with patch("app.api.v1.chat.get_llm_gateway", return_value=mock_gateway), patch(
            "app.api.v1.chat.compile_agent"
        ) as mock_compile:
            resp = client.post(
                f"/api/v1/chat/sessions/{sid}/messages",
                json={"content": "有哪些岗位"},
                headers={"Authorization": f"Bearer {student_token}"},
            )
            mock_compile.assert_not_called()  # 0 token 路径不进 agent
        assert resp.status_code == 200, resp.text

        listing = client.get(
            f"/api/v1/admin/chat/messages?session_id={sid}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert listing.status_code == 200, listing.text
        assistant = [i for i in listing.json()["items"] if i["role"] == "assistant"]
        assert assistant, "助手消息没落库"

        viz = assistant[0]["viz"]
        assert isinstance(viz, list) and viz, "管理端读不到 viz"
        assert viz[0]["kind"] == "table"
        assert viz[0]["columns"] == ["#", "岗位名称"]
        # 管理端还能看到"这条是工作流答的、没花 token"
        assert assistant[0]["model_used"].startswith("workflow:")
        assert assistant[0]["tokens_used"] == 0

    def test_messages_without_viz_are_null(self, admin_token: str, client: TestClient):
        """老消息（C1 之前）没有 viz 字段值 → 必须是 null，不能是 [] 之外的怪东西。"""
        resp = client.get(
            "/api/v1/admin/chat/messages?limit=100",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        for item in resp.json()["items"]:
            assert "viz" in item
            assert item["viz"] is None or isinstance(item["viz"], list)


class TestChatAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access chat endpoints."""
        resp = client.get(
            "/api/v1/admin/chat/sessions",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403


class TestChatFiltersP15:
    """P1-5：时间范围 / 角色 / 关键字筛选。

    不断言具体条数（库里数据会变），只断言「筛选语义自洽」：
    未来窗口必空、role 全一致、keyword 全命中。
    """

    def test_sessions_future_window_is_empty(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/chat/sessions?start=2999-01-01T00:00:00.000Z",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["items"] == []

    def test_sessions_past_window_is_empty(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/chat/sessions?end=2000-01-01T00:00:00.000Z",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_messages_role_filter_consistent(self, admin_token: str, client: TestClient):
        for role in ("user", "assistant"):
            resp = client.get(
                f"/api/v1/admin/chat/messages?role={role}&limit=100",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200, resp.text
            for item in resp.json()["items"]:
                assert item["role"] == role

    def test_messages_invalid_role_rejected(self, admin_token: str, client: TestClient):
        """Literal 白名单：非法 role 直接 422（而不是静默返回全部）。"""
        resp = client.get(
            "/api/v1/admin/chat/messages?role=robot",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    def test_messages_keyword_only_matches(self, admin_token: str, client: TestClient):
        """关键字筛选：返回的每一条内容都必须包含关键字（用极常见字符保证有命中）。"""
        keyword = "的"
        resp = client.get(
            f"/api/v1/admin/chat/messages?keyword={keyword}&limit=100",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        for item in items:
            assert keyword in item["content"]
        # 该字符在中文语料里几乎必然出现；若库里全无中文则退化为 0，仍算通过
        assert resp.json()["total"] == len(items)

    def test_messages_time_window_filters(self, admin_token: str, client: TestClient):
        """取一条真实消息的创建时间作为边界，闭区间应能命中它自身。"""
        listing = client.get(
            "/api/v1/admin/chat/messages?limit=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        ).json()
        if not listing["items"]:
            pytest.skip("库里没有聊天消息")

        created = listing["items"][0]["created_at"]
        resp = client.get(
            f"/api/v1/admin/chat/messages?start={created}&end={created}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        assert any(item["created_at"] == created for item in resp.json()["items"])
