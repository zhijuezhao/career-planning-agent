import time

import pytest
from app.main import app
from fastapi.testclient import TestClient

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_register_success(client):
    resp = client.post("/api/v1/auth/register", json={
        "username": f"reg_{_ts}",
        "password": "test123456",
        "email": f"reg{_ts}@example.com",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == f"reg_{_ts}"
    assert data["email"] == f"reg{_ts}@example.com"
    assert "id" in data
    assert "password_hash" not in data


def test_register_duplicate_username(client):
    uname = f"dup_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "test123456",
    })
    resp = client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "otherpass123",
    })
    assert resp.status_code == 400
    assert "Username already exists" in resp.json()["detail"]


def test_login_success(client):
    uname = f"login_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "mypassword123",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "mypassword123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    uname = f"wrongpw_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "correctpass123",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_get_me_authenticated(client):
    uname = f"meuser_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "mepass123456",
    })
    login_resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "mepass123456",
    })
    token = login_resp.json()["access_token"]

    resp = client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {token}"
    })
    assert resp.status_code == 200
    assert resp.json()["username"] == uname


def test_get_me_unauthorized(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 422


def test_get_me_invalid_token(client):
    resp = client.get("/api/v1/auth/me", headers={
        "Authorization": "Bearer invalid.token.here"
    })
    assert resp.status_code == 401
