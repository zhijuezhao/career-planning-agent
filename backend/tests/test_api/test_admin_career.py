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


@pytest.fixture(scope="module")
def admin_token(client: TestClient) -> str:
    uname = f"admin_career_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "admin123456",
    })
    from app.domain.models.user import User

    async def set_admin():
        async with AsyncSession(_test_engine) as session:
            result = await session.execute(select(User).where(User.username == uname))
            user = result.scalar_one_or_none()
            if user:
                user.role = "admin"
                await session.commit()

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
    uname = f"student_career_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "student123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "student123456",
    })
    return resp.json()["access_token"]


class TestCareerPathsAPI:
    def test_list_career_paths(self, admin_token: str, client: TestClient):
        """Test listing career paths."""
        resp = client.get(
            "/api/v1/admin/career/paths",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_filter_paths_by_type(self, admin_token: str, client: TestClient):
        """Test filtering career paths by type."""
        resp = client.get(
            "/api/v1/admin/career/paths?path_type=upgrade",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_get_career_path_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent career path."""
        resp = client.get(
            "/api/v1/admin/career/paths/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501


class TestGrowthPlansAPI:
    def test_list_growth_plans(self, admin_token: str, client: TestClient):
        """Test listing growth plans."""
        resp = client.get(
            "/api/v1/admin/career/plans",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_filter_plans_by_user(self, admin_token: str, client: TestClient):
        """Test filtering growth plans by user_id."""
        resp = client.get(
            "/api/v1/admin/career/plans?user_id=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_get_growth_plan_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent growth plan."""
        resp = client.get(
            "/api/v1/admin/career/plans/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501


class TestCareerAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access career endpoints."""
        resp = client.get(
            "/api/v1/admin/career/paths",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
