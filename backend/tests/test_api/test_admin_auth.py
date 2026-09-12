import asyncio
import time

import pytest
from app.main import app
from fastapi.testclient import TestClient

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def admin_token(client: TestClient) -> str:
    # Register admin user
    uname = f"admin_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "admin123456",
    })
    # Manually set role to admin (in real scenario, this would be done via DB or admin API)
    from app.infrastructure.database import async_session_factory
    from app.domain.models.user import User

    async def set_admin():
        async with async_session_factory() as session:
            result = await session.execute(
                __import__("sqlalchemy").select(User).where(User.username == uname)
            )
            user = result.scalar_one_or_none()
            if user:
                user.role = "admin"
                await session.commit()

    # Use a new event loop for setup
    loop = asyncio.new_event_loop()
    loop.run_until_complete(set_admin())
    loop.close()

    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "admin123456",
    })
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def student_token(client: TestClient) -> str:
    uname = f"student_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "student123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "student123456",
    })
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def other_user_id(client: TestClient, student_token: str) -> int:
    """Create another user and return their ID."""
    uname = f"other_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "other123456",
    })

    from app.infrastructure.database import async_session_factory
    from app.domain.models.user import User

    async def get_user_id():
        async with async_session_factory() as session:
            result = await session.execute(
                __import__("sqlalchemy").select(User).where(User.username == uname)
            )
            user = result.scalar_one_or_none()
            return user.id if user else None

    loop = asyncio.new_event_loop()
    user_id = loop.run_until_complete(get_user_id())
    loop.close()
    return user_id


class TestRequireAdmin:
    def test_admin_access_granted(self, admin_token: str, client: TestClient):
        """Admin user should be able to access admin endpoints."""
        resp = client.get(
            "/api/v1/admin/dashboard/health",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Should not be 403 (may be 200 or 404 depending on implementation)
        assert resp.status_code != 403

    def test_student_access_denied(self, student_token: str, client: TestClient):
        """Non-admin user should be denied access to admin endpoints."""
        resp = client.get(
            "/api/v1/admin/dashboard/health",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403

    def test_unauthorized_access_denied(self, client: TestClient):
        """Unauthenticated request should be denied."""
        resp = client.get("/api/v1/admin/dashboard/health")
        assert resp.status_code in (401, 422)


class TestUserUpdateSecurity:
    def test_user_cannot_update_other_user(self, student_token: str, other_user_id: int, client: TestClient):
        """Regular user should not be able to update another user."""
        resp = client.put(
            f"/api/v1/users/{other_user_id}",
            json={"phone": "13800138000"},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403

    def test_user_cannot_change_own_role(self, student_token: str, client: TestClient):
        """Regular user should not be able to change their own role."""
        # Get current user's ID
        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        my_id = me.json()["id"]

        # Try to change role
        resp = client.put(
            f"/api/v1/users/{my_id}",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
