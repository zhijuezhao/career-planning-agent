
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
        # S4: total_matches / total_reports 已由写死的 0 改为真实计数，
        # 并与 /snapshot-stats 的已匹配快照数交叉校验（防止再次写死）
        assert data["total_matches"] >= 0
        assert data["total_reports"] >= 0
        stats = client.get(
            "/api/v1/admin/dashboard/snapshot-stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert stats.status_code == 200
        assert data["total_matches"] == stats.json()["matched_snapshots"]

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

    def test_snapshot_stats(self, admin_token: str, client: TestClient):
        """S4/D8: /snapshot-stats 取代原 /match-stats（匹配明细不再落表）。"""
        resp = client.get(
            "/api/v1/admin/dashboard/snapshot-stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"total_snapshots", "matched_snapshots", "pending_snapshots"}
        assert data["total_snapshots"] == data["matched_snapshots"] + data["pending_snapshots"]
        assert data["total_snapshots"] >= 0

    def test_match_stats_removed(self, admin_token: str, client: TestClient):
        """原 /match-stats 已按 D8 删除 -> 404（不是 501）。"""
        resp = client.get(
            "/api/v1/admin/dashboard/match-stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_system_health(self, admin_token: str, client: TestClient):
        """Test system health endpoint."""
        resp = client.get(
            "/api/v1/admin/dashboard/system-health",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["database"] == "healthy"
        # S4: 改为读 app.state.scheduler（旧实现现场 new 且无公开 running 属性 -> 恒 unknown）
        assert data["scheduler"] in {"running", "stopped", "not_initialized"}
        assert "llm_gateway" in data
