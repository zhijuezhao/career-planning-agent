
import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


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
        """Test match stats endpoint (501: depends on deleted JobMatch table)."""
        resp = client.get(
            "/api/v1/admin/dashboard/match-stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

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
