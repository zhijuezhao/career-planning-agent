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
    uname = f"admin_match_{_ts}"
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
    uname = f"student_match_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "student123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "student123456",
    })
    return resp.json()["access_token"]


async def _get_user_id(username: str) -> int:
    from app.domain.models.user import User

    async with AsyncSession(_test_engine) as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one().id


def _create_user(client: TestClient, username: str) -> int:
    client.post("/api/v1/auth/register", json={
        "username": username,
        "password": "test123456",
    })
    loop = asyncio.new_event_loop()
    user_id = loop.run_until_complete(_get_user_id(username))
    loop.close()
    return user_id


class TestMatchResultsAPI:
    def test_list_match_results(self, admin_token: str, client: TestClient):
        """Test listing match results (501: depends on deleted JobMatch table)."""
        resp = client.get(
            "/api/v1/admin/matching/results",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_filter_match_results_by_user(self, admin_token: str, client: TestClient):
        """Test filtering match results by user_id (501: deleted JobMatch table)."""
        resp = client.get(
            "/api/v1/admin/matching/results?user_id=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_get_match_result_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent match result (501: deleted JobMatch table)."""
        resp = client.get(
            "/api/v1/admin/matching/results/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501


class TestFeedbacksAPI:
    def test_list_feedbacks(self, admin_token: str, client: TestClient):
        """Test listing feedbacks (501: depends on deleted UserFeedback table)."""
        resp = client.get(
            "/api/v1/admin/matching/feedbacks",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_filter_feedbacks_by_type(self, admin_token: str, client: TestClient):
        """Test filtering feedbacks by type (501: deleted UserFeedback table)."""
        resp = client.get(
            "/api/v1/admin/matching/feedbacks?feedback_type=like",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_get_feedback_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent feedback (501: deleted UserFeedback table)."""
        resp = client.get(
            "/api/v1/admin/matching/feedbacks/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501


class TestDimensionWeightsAPI:
    def test_list_dimension_weights(self, admin_token: str, client: TestClient):
        """Test listing dimension weights."""
        resp = client.get(
            "/api/v1/admin/matching/weights",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_create_dimension_weight(self, admin_token: str, client: TestClient):
        """Test creating a dimension weight."""
        resp = client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": f"测试类别_{_ts}",
                "top_dimension": "技术能力",
                "weight": 0.3,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["job_category"] == f"测试类别_{_ts}"
        assert data["top_dimension"] == "技术能力"
        assert data["weight"] == 0.3

    def test_create_duplicate_weight_conflict(self, admin_token: str, client: TestClient):
        """Test creating a duplicate dimension weight returns 409."""
        category = f"重复类别_{_ts}"
        client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": category,
                "top_dimension": "沟通能力",
                "weight": 0.2,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": category,
                "top_dimension": "沟通能力",
                "weight": 0.4,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    def test_update_dimension_weight(self, admin_token: str, client: TestClient):
        """Test updating a dimension weight."""
        create_resp = client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": f"更新类别_{_ts}",
                "top_dimension": "领导力",
                "weight": 0.15,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        weight_id = create_resp.json()["id"]

        resp = client.put(
            f"/api/v1/admin/matching/weights/{weight_id}",
            json={"weight": 0.25},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["weight"] == 0.25

    def test_delete_dimension_weight(self, admin_token: str, client: TestClient):
        """Test deleting a dimension weight."""
        create_resp = client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": f"删除类别_{_ts}",
                "top_dimension": "团队协作",
                "weight": 0.1,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        weight_id = create_resp.json()["id"]

        resp = client.delete(
            f"/api/v1/admin/matching/weights/{weight_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

        resp = client.get(
            f"/api/v1/admin/matching/weights/{weight_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_filter_weights_by_category(self, admin_token: str, client: TestClient):
        """Test filtering dimension weights by category."""
        category = f"筛选类别_{_ts}"
        client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": category,
                "top_dimension": "创新能力",
                "weight": 0.2,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        resp = client.get(
            f"/api/v1/admin/matching/weights?job_category={category}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["job_category"] == category for item in data["items"])


class TestMatchingAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access matching endpoints."""
        resp = client.get(
            "/api/v1/admin/matching/results",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
