
import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestRequireAdmin:
    def test_admin_access_granted(self, admin_token: str, client: TestClient):
        """Admin user should be able to access admin endpoints."""
        resp = client.get(
            "/api/v1/admin/dashboard/health",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Should not be 403 (may be 200 or 404 depending on implementation)
        assert resp.status_code != 403

    def test_student_access_denied(self, student_token: str, client: TestClient):
        """Non-admin user should be denied access to admin endpoints."""
        resp = client.get(
            "/api/v1/admin/dashboard/health",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403

    def test_unauthorized_access_denied(self, client: TestClient):
        """Unauthenticated request should be denied."""
        resp = client.get("/api/v1/admin/dashboard/health")
        assert resp.status_code in (401, 422)


class TestUserUpdateSecurity:
    def test_user_cannot_update_other_user(self, student_token: str, other_user_id: int, client: TestClient):
        """Regular user should not be able to update another user."""
        resp = client.put(
            f"/api/v1/users/{other_user_id}",
            json={"phone": "13800138000"},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403

    def test_user_cannot_change_own_role(self, student_token: str, client: TestClient):
        """Regular user should not be able to change their own role."""
        # Get current user's ID
        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        my_id = me.json()["id"]

        # Try to change role
        resp = client.put(
            f"/api/v1/users/{my_id}",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
