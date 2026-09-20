import time

import pytest
from app.main import app
from fastapi.testclient import TestClient

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestAIConfigAPI:
    def test_list_configs(self, admin_token: str, client: TestClient):
        """Test listing AI configs."""
        resp = client.get(
            "/api/v1/admin/system/configs",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_create_config(self, admin_token: str, client: TestClient):
        """Test creating an AI config."""
        resp = client.post(
            "/api/v1/admin/system/configs",
            json={
                "function_key": f"test_model_{_ts}",
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "temperature": 0.7,
                "max_tokens": 4096,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["function_key"] == f"test_model_{_ts}"
        assert data["provider"] == "deepseek"

    def test_create_duplicate_config_conflict(self, admin_token: str, client: TestClient):
        """Test creating a duplicate AI config returns 409."""
        function_key = f"dup_model_{_ts}"
        client.post(
            "/api/v1/admin/system/configs",
            json={
                "function_key": function_key,
                "provider": "openai",
                "model_name": "gpt-4",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = client.post(
            "/api/v1/admin/system/configs",
            json={
                "function_key": function_key,
                "provider": "openai",
                "model_name": "gpt-3.5",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    def test_update_config(self, admin_token: str, client: TestClient):
        """Test updating an AI config."""
        create_resp = client.post(
            "/api/v1/admin/system/configs",
            json={
                "function_key": f"update_model_{_ts}",
                "provider": "qwen",
                "model_name": "qwen-turbo",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        config_id = create_resp.json()["id"]

        resp = client.put(
            f"/api/v1/admin/system/configs/{config_id}",
            json={"temperature": 0.5, "max_tokens": 2048},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["temperature"] == 0.5
        assert data["max_tokens"] == 2048

    def test_delete_config(self, admin_token: str, client: TestClient):
        """Test deleting an AI config."""
        create_resp = client.post(
            "/api/v1/admin/system/configs",
            json={
                "function_key": f"delete_model_{_ts}",
                "provider": "test",
                "model_name": "test-model",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        config_id = create_resp.json()["id"]

        resp = client.delete(
            f"/api/v1/admin/system/configs/{config_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

        resp = client.get(
            f"/api/v1/admin/system/configs/{config_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404


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
            "/api/v1/admin/system/configs",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
