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
    uname = f"admin_reports_{_ts}"
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
    uname = f"student_reports_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "student123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "student123456",
    })
    return resp.json()["access_token"]


class TestReportsAPI:
    def test_list_reports(self, admin_token: str, client: TestClient):
        """Test listing reports."""
        resp = client.get(
            "/api/v1/admin/reports",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_filter_reports_by_user(self, admin_token: str, client: TestClient):
        """Test filtering reports by user_id."""
        resp = client.get(
            "/api/v1/admin/reports?user_id=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["user_id"] == 1 for item in data["items"])

    def test_get_report_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent report."""
        resp = client.get(
            "/api/v1/admin/reports/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_download_report_not_found(self, admin_token: str, client: TestClient):
        """Test downloading a non-existent report."""
        resp = client.get(
            "/api/v1/admin/reports/999999/download",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


class TestReportsAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access reports endpoints."""
        resp = client.get(
            "/api/v1/admin/reports",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
