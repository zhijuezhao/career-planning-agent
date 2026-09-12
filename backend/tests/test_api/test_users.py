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


def test_list_users(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data
    assert data["total"] >= 1


def test_get_user(client: TestClient, auth_token: str, user_id: int):
    resp = client.get(
        f"/api/v1/users/{user_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user_id
    assert "username" in data


def test_get_user_not_found(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/users/999999",
        headers={"Authorization": f"Bearer {auth_token}"},
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
