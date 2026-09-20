import asyncio
import time

import pytest
from app.config import get_settings
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

_settings = get_settings()
_test_engine = create_async_engine(_settings.database_url, poolclass=NullPool)

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


async def _get_user_id(username: str) -> int:
    from app.domain.models.user import User

    async with AsyncSession(_test_engine) as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one().id


def _create_user(client: TestClient, username: str) -> int:
    """Register a user and return their ID."""
    client.post("/api/v1/auth/register", json={
        "username": username,
        "password": "test123456",
    })
    return asyncio.run(_get_user_id(username))


class TestUsersAPI:
    def test_list_users(self, admin_token: str, client: TestClient):
        """Test listing users."""
        resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_filter_users_by_role(self, admin_token: str, client: TestClient):
        """Test filtering users by role."""
        resp = client.get(
            "/api/v1/admin/users?role=admin",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["role"] == "admin" for item in data["items"])

    def test_get_user(self, admin_token: str, client: TestClient):
        """Test getting a single user."""
        user_id = _create_user(client, f"test_get_{_ts}")

        resp = client.get(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == user_id
        assert data["username"] == f"test_get_{_ts}"

    def test_update_user(self, admin_token: str, client: TestClient):
        """Test updating a user."""
        user_id = _create_user(client, f"test_update_{_ts}")

        resp = client.put(
            f"/api/v1/admin/users/{user_id}",
            json={"phone": "13800138000", "status": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["phone"] == "13800138000"
        assert data["status"] == 1

    def test_reset_password(self, admin_token: str, client: TestClient):
        """Test resetting a user's password."""
        uname = f"test_reset_{_ts}"
        user_id = _create_user(client, uname)

        resp = client.post(
            f"/api/v1/admin/users/{user_id}/reset-password?new_password=newpass123",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

        # Verify new password works
        login_resp = client.post("/api/v1/auth/login", json={
            "username": uname,
            "password": "newpass123",
        })
        assert login_resp.status_code == 200

    def test_delete_user(self, admin_token: str, client: TestClient):
        """Test deleting a user."""
        user_id = _create_user(client, f"test_delete_{_ts}")

        resp = client.delete(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

        # Verify it's deleted
        resp = client.get(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_user_stats(self, admin_token: str, client: TestClient):
        """Test getting user statistics."""
        uname = f"test_stats_{_ts}"
        user_id = _create_user(client, uname)

        resp = client.get(
            f"/api/v1/admin/users/{user_id}/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == user_id
        assert data["username"] == uname
        assert "resume_count" in data
        assert "match_count" in data
        assert "report_count" in data
        assert "chat_session_count" in data

    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access admin user endpoints."""
        resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
