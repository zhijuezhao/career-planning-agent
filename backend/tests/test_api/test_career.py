import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.main import app
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skip(reason="旧表已删除，新端点待 Task 5/6")

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_token(client: TestClient) -> str:
    uname = f"career_user_{_ts}"
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


def test_create_career_path_unauthorized(client: TestClient):
    resp = client.post("/api/v1/career/paths", json={
        "profile_id": 1,
        "target_job_id": 1,
    })
    assert resp.status_code == 422


def test_list_career_paths_unauthorized(client: TestClient):
    resp = client.get("/api/v1/career/paths")
    assert resp.status_code == 422


def test_list_growth_plans_unauthorized(client: TestClient):
    resp = client.get("/api/v1/career/plans")
    assert resp.status_code == 422


def test_create_growth_plan_unauthorized(client: TestClient):
    resp = client.post("/api/v1/career/plans", json={
        "growth_path_id": 1,
    })
    assert resp.status_code == 422


def test_list_career_paths_empty(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/career/paths",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data


def test_list_growth_plans_empty(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/career/plans",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data


def test_get_career_path_not_found(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/career/paths/999999",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 404


def test_get_growth_plan_not_found(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/career/plans/999999",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 404


def test_create_career_path_failure(client: TestClient, auth_token: str):
    """测试生成失败时返回 400。"""
    with patch("app.api.v1.career.generate_career_path", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = None
        resp = client.post(
            "/api/v1/career/paths",
            json={"profile_id": 99999, "target_job_id": 99999},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
    assert resp.status_code == 400


def test_create_growth_plan_failure(client: TestClient, auth_token: str):
    """测试生成失败时返回 400。"""
    with patch("app.api.v1.career.generate_growth_plan", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = None
        resp = client.post(
            "/api/v1/career/plans",
            json={"growth_path_id": 99999},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
    assert resp.status_code == 400


def test_create_career_path_with_mock(client: TestClient, auth_token: str, user_id: int):
    """测试成功生成职业路线（mock LLM）。"""
    mock_path = MagicMock()
    mock_path.id = 1
    mock_path.user_id = user_id
    mock_path.target_position = "前端工程师"
    mock_path.path_type = "技术专家"
    mock_path.current_abilities = {}
    mock_path.target_abilities = {}
    mock_path.milestones = []
    mock_path.generated_plan = {}
    mock_path.learning_resources = {}
    mock_path.created_at = "2026-09-08T00:00:00"

    with patch("app.api.v1.career.generate_career_path", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = mock_path
        resp = client.post(
            "/api/v1/career/paths",
            json={"profile_id": 1, "target_job_id": 1, "current_stage": "在校学生"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["target_position"] == "前端工程师"
    assert data["path_type"] == "技术专家"


def test_create_growth_plan_with_mock(client: TestClient, auth_token: str, user_id: int):
    """测试成功生成成长计划（mock LLM）。"""
    mock_plan = MagicMock()
    mock_plan.id = 1
    mock_plan.user_id = user_id
    mock_plan.growth_path_id = 1
    mock_plan.cycle_weeks = 12
    mock_plan.intensity = "中等强度"
    mock_plan.tasks = []
    mock_plan.progress = {}
    mock_plan.weekly_reviews = {}
    mock_plan.created_at = "2026-09-08T00:00:00"

    with patch("app.api.v1.career.generate_growth_plan", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = mock_plan
        resp = client.post(
            "/api/v1/career/plans",
            json={"growth_path_id": 1, "weekly_hours": 10, "cycle_weeks": 12},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["cycle_weeks"] == 12
    assert data["intensity"] == "中等强度"
