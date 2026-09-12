import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.main import app
from fastapi.testclient import TestClient

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_token(client: TestClient) -> str:
    uname = f"report_user_{_ts}"
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


def test_generate_report_unauthorized(client: TestClient):
    resp = client.post("/api/v1/reports/generate", json={"profile_id": 1})
    assert resp.status_code == 422


def test_list_reports_unauthorized(client: TestClient):
    resp = client.get("/api/v1/reports")
    assert resp.status_code == 422


def test_get_report_detail_unauthorized(client: TestClient):
    resp = client.get("/api/v1/reports/1")
    assert resp.status_code == 422


def test_download_report_unauthorized(client: TestClient):
    resp = client.get("/api/v1/reports/1/download")
    assert resp.status_code == 422


def test_list_reports_empty(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/reports",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data


def test_get_report_not_found(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/reports/999999",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 404


def test_download_report_not_found(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/reports/999999/download",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 404


def test_generate_report_failure(client: TestClient, auth_token: str):
    """测试生成失败时返回 400。"""
    with patch("app.api.v1.reports.create_report", new_callable=AsyncMock) as mock_gen:
        mock_gen.side_effect = ValueError("用户能力画像不存在")
        resp = client.post(
            "/api/v1/reports/generate",
            json={"profile_id": 99999},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
    assert resp.status_code == 400


def test_generate_report_with_mock(client: TestClient, auth_token: str, user_id: int):
    """测试成功生成报告（mock LLM 和文件生成）。"""
    mock_report = MagicMock()
    mock_report.id = 1
    mock_report.user_id = user_id
    mock_report.profile_id = 1
    mock_report.target_job = "前端工程师"
    mock_report.report_content = {"report_text": "测试报告"}
    mock_report.word_file_path = "/tmp/test_report.docx"
    mock_report.version = 1
    mock_report.created_at = "2026-09-08T00:00:00"

    with patch("app.api.v1.reports.create_report", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = mock_report
        resp = client.post(
            "/api/v1/reports/generate",
            json={"profile_id": 1, "target_job": "前端工程师"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["target_job"] == "前端工程师"
    assert data["version"] == 1
