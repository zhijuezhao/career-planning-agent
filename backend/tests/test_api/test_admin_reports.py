
import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestReportsAPI:
    def test_list_reports(self, admin_token: str, client: TestClient):
        """Test listing reports."""
        resp = client.get(
            "/api/v1/admin/reports",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_filter_reports_by_user(self, admin_token: str, client: TestClient):
        """Test filtering reports by user_id."""
        resp = client.get(
            "/api/v1/admin/reports?user_id=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_get_report_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent report."""
        resp = client.get(
            "/api/v1/admin/reports/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501

    def test_download_report_not_found(self, admin_token: str, client: TestClient):
        """Test downloading a non-existent report."""
        resp = client.get(
            "/api/v1/admin/reports/999999/download",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 501


class TestReportsAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access reports endpoints."""
        resp = client.get(
            "/api/v1/admin/reports",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
