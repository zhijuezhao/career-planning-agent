
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


class TestChatAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access chat endpoints."""
        resp = client.get(
            "/api/v1/admin/chat/sessions",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
