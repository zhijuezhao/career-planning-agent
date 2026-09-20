import time

import pytest
from app.main import app
from fastapi.testclient import TestClient

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestJobsAPI:
    def test_list_jobs(self, admin_token: str, client: TestClient):
        """Test listing job profiles."""
        resp = client.get(
            "/api/v1/admin/jobs",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_create_job(self, admin_token: str, client: TestClient):
        """Test creating a job profile."""
        resp = client.post(
            "/api/v1/admin/jobs",
            json={
                "title": f"测试岗位_{_ts}",
                "industry": "互联网",
                "level": "中级",
                "salary_range": "15000-25000",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == f"测试岗位_{_ts}"
        self.created_job_id = data["id"]

    def test_get_job(self, admin_token: str, client: TestClient):
        """Test getting a single job profile."""
        # First create a job
        resp = client.post(
            "/api/v1/admin/jobs",
            json={
                "title": f"测试岗位详情_{_ts}",
                "industry": "互联网",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        job_id = resp.json()["id"]

        # Get the job
        resp = client.get(
            f"/api/v1/admin/jobs/{job_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job_id

    def test_update_job(self, admin_token: str, client: TestClient):
        """Test updating a job profile."""
        # First create a job
        resp = client.post(
            "/api/v1/admin/jobs",
            json={
                "title": f"测试岗位更新_{_ts}",
                "industry": "互联网",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        job_id = resp.json()["id"]

        # Update the job
        resp = client.put(
            f"/api/v1/admin/jobs/{job_id}",
            json={"title": f"更新后岗位_{_ts}", "level": "高级"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == f"更新后岗位_{_ts}"
        assert data["level"] == "高级"

    def test_delete_job(self, admin_token: str, client: TestClient):
        """Test deleting a job profile."""
        # First create a job
        resp = client.post(
            "/api/v1/admin/jobs",
            json={
                "title": f"测试岗位删除_{_ts}",
                "industry": "互联网",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        job_id = resp.json()["id"]

        # Delete the job
        resp = client.delete(
            f"/api/v1/admin/jobs/{job_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

        # Verify it's deleted
        resp = client.get(
            f"/api/v1/admin/jobs/{job_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_filter_jobs(self, admin_token: str, client: TestClient):
        """Test filtering job profiles."""
        # Create jobs with different industries
        client.post(
            "/api/v1/admin/jobs",
            json={"title": f"互联网岗位_{_ts}", "industry": "互联网"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        client.post(
            "/api/v1/admin/jobs",
            json={"title": "金融岗位", "industry": "金融"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Filter by industry
        resp = client.get(
            "/api/v1/admin/jobs?industry=互联网",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["industry"] == "互联网" for item in data["items"])
