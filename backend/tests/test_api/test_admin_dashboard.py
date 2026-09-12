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
    uname = f"admin_dash_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "admin123456",
    })
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

    loop = asyncio.new_event_loop()
    loop.run_until_complete(set_admin())
    loop.close()

    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "admin123456",
    })
    return resp.json()["access_token"]


class TestDashboardAPI:
    def test_overview(self, admin_token: str, client: TestClient):
        """Test dashboard overview endpoint."""
        resp = client.get(
            "/api/v1/admin/dashboard/overview",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_users" in data
        assert "total_resumes" in data
        assert "total_job_profiles" in data
        assert "total_matches" in data
        assert "total_reports" in data
        assert "total_chat_sessions" in data

    def test_user_growth(self, admin_token: str, client: TestClient):
        """Test user growth endpoint."""
        resp = client.get(
            "/api/v1/admin/dashboard/user-growth",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_job_categories(self, admin_token: str, client: TestClient):
        """Test job categories endpoint."""
        resp = client.get(
            "/api/v1/admin/dashboard/job-categories",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_quality_distribution(self, admin_token: str, client: TestClient):
        """Test quality distribution endpoint."""
        resp = client.get(
            "/api/v1/admin/dashboard/quality-distribution",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_match_stats(self, admin_token: str, client: TestClient):
        """Test match stats endpoint."""
        resp = client.get(
            "/api/v1/admin/dashboard/match-stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "avg_score" in data
        assert "total_matches" in data
        assert "feedback_count" in data

    def test_system_health(self, admin_token: str, client: TestClient):
        """Test system health endpoint."""
        resp = client.get(
            "/api/v1/admin/dashboard/system-health",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "database" in data
        assert "scheduler" in data
        assert "llm_gateway" in data
