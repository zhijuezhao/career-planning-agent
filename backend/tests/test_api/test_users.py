import time

import pytest
from app.main import app
from fastapi.testclient import TestClient

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_token(client: TestClient) -> str:
    uname = f"t13_user_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "testpass123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "testpass123456",
    })
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def user_id(client: TestClient, auth_token: str) -> int:
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    return resp.json()["id"]


def test_list_users(client: TestClient, admin_token: str):
    """列表接口现为 **admin-only**。

    他人 dirty `api/v1/users.py` 把依赖从 `require_auth` 收紧为 `require_admin`
    （此前任何登录用户都能枚举全部账号）—— 这是正确的收紧，测试随之改用 admin token。
    学生 token 的行为见 `test_list_users_forbidden_for_student`。
    """
    resp = client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data
    assert data["total"] >= 1


def test_list_users_forbidden_for_student(client: TestClient, auth_token: str):
    """收紧的**意图行为**：学生不能枚举全部用户（锁住这条，避免以后被无意放开）。"""
    resp = client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 403


def test_get_user(client: TestClient, auth_token: str, user_id: int):
    resp = client.get(
        f"/api/v1/users/{user_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user_id
    assert "username" in data


def test_get_other_user_forbidden_for_student(
    client: TestClient, auth_token: str, other_user_id: int
):
    """学生读**别人**的资料 → 403（`非 admin 且 非本人` 才拒）。"""
    resp = client.get(
        f"/api/v1/users/{other_user_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 403


def test_admin_can_read_any_user(client: TestClient, admin_token: str, other_user_id: int):
    """admin 仍可读任意用户（收紧条件里的 `or current_user.role == "admin"` 这一半）。"""
    resp = client.get(
        f"/api/v1/users/{other_user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == other_user_id


def test_get_user_not_found(client: TestClient, admin_token: str):
    """不存在的用户 → 404。

    必须用 admin token：学生查别人的 id 会先被 403 拦住，根本走不到 404 分支。
    """
    resp = client.get(
        "/api/v1/users/999999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


def test_update_user_phone(client: TestClient, auth_token: str, user_id: int):
    resp = client.put(
        f"/api/v1/users/{user_id}",
        json={"phone": "13800138000"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] == "13800138000"


def test_update_user_empty_body(client: TestClient, auth_token: str, user_id: int):
    resp = client.put(
        f"/api/v1/users/{user_id}",
        json={},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 400


def test_delete_self(client: TestClient, auth_token: str, user_id: int):
    # Create a disposable user for deletion test
    uname = f"del_user_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "testpass123456",
    })
    login_resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "testpass123456",
    })
    token = login_resp.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    del_id = me.json()["id"]

    resp = client.delete(
        f"/api/v1/users/{del_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204


def test_list_unauthorized(client: TestClient):
    resp = client.get("/api/v1/users")
    assert resp.status_code == 422
