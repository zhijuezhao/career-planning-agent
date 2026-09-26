"""系统配置接口的回归用例（旧版 `/configs` 已随「旧版配置」面板一并移除，2026-09-26）。

- `/scheduler/status`：调度器状态仍可用；
- 越权：普通学生访问系统配置类接口一律 403（用仍在用的 `/providers` 作为代表）。
"""

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestSchedulerStatusAPI:
    def test_get_scheduler_status(self, admin_token: str, client: TestClient):
        """Test getting scheduler status."""
        resp = client.get(
            "/api/v1/admin/system/scheduler/status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "jobs" in data


class TestSystemAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access system endpoints."""
        resp = client.get(
            "/api/v1/admin/system/providers",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
