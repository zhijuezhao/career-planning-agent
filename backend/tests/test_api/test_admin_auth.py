
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


class TestAdminLogin:
    """S2: 管理员登录端点 POST /api/v1/admin/auth/login。"""

    def test_admin_login_success_and_token_usable(
        self, client: TestClient, admin_credentials: tuple[str, str]
    ):
        """管理员凭据可换 token，且该 token 能访问管理端点。"""
        uname, password = admin_credentials
        resp = client.post(
            "/api/v1/admin/auth/login", json={"username": uname, "password": password}
        )
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        assert token

        health = client.get(
            "/api/v1/admin/dashboard/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert health.status_code == 200
        assert health.json()["admin"] == uname

    def test_student_login_rejected(
        self, client: TestClient, student_credentials: tuple[str, str]
    ):
        """学生账号走管理端登录必须被拒（403），且不得拿到 token。"""
        uname, password = student_credentials
        resp = client.post(
            "/api/v1/admin/auth/login", json={"username": uname, "password": password}
        )
        assert resp.status_code == 403
        assert "access_token" not in resp.json()

    def test_wrong_password_rejected(
        self, client: TestClient, admin_credentials: tuple[str, str]
    ):
        """密码错误返回 401。"""
        uname, _ = admin_credentials
        resp = client.post(
            "/api/v1/admin/auth/login",
            json={"username": uname, "password": "definitely-wrong"},
        )
        assert resp.status_code == 401

    def test_unknown_user_rejected(self, client: TestClient):
        """账号不存在同样返回 401（与密码错误不可区分，避免探测账号）。"""
        resp = client.post(
            "/api/v1/admin/auth/login",
            json={"username": "no_such_admin_user_xyz", "password": "whatever123"},
        )
        assert resp.status_code == 401
