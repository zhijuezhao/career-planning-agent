import time
from unittest.mock import AsyncMock, patch

import pytest
from app.main import app
from fastapi.testclient import TestClient

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_token(client: TestClient) -> str:
    uname = f"match_user_{_ts}"
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


def test_run_match_unauthorized(client: TestClient):
    resp = client.post("/api/v1/matching/run", json={"profile_id": 1})
    assert resp.status_code == 422


def test_list_results_unauthorized(client: TestClient):
    resp = client.get("/api/v1/matching/results")
    assert resp.status_code == 422


def test_list_feedbacks_unauthorized(client: TestClient):
    resp = client.get("/api/v1/matching/feedback")
    assert resp.status_code == 422


def test_submit_feedback_unauthorized(client: TestClient):
    resp = client.post("/api/v1/matching/feedback", json={
        "match_id": 1,
        "feedback_type": "like",
    })
    assert resp.status_code == 422


def test_list_results_empty(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/matching/results",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data


def test_list_feedbacks_empty(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/matching/feedback",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data


def test_run_match_no_vector(client: TestClient, auth_token: str):
    """测试无用户向量时返回 400。"""
    resp = client.post(
        "/api/v1/matching/run",
        json={"profile_id": 99999, "top_k": 5},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 400
    assert "向量" in resp.json()["detail"] or "不存在" in resp.json()["detail"]


def test_get_match_detail_not_found(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/matching/results/999999",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 404


def test_submit_feedback_invalid_type(client: TestClient, auth_token: str):
    """测试无效反馈类型返回 422。"""
    resp = client.post(
        "/api/v1/matching/feedback",
        json={"match_id": 1, "feedback_type": "invalid"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 422


def test_submit_feedback_match_not_found(client: TestClient, auth_token: str):
    """测试匹配不存在时返回 404。"""
    resp = client.post(
        "/api/v1/matching/feedback",
        json={"match_id": 999999, "feedback_type": "like"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 404


def test_run_match_with_mock_vector(client: TestClient, auth_token: str, user_id: int):
    """测试有用户向量时的匹配流程（mock）。"""
    mock_vector = [0.1] * 1024
    mock_match_result = [{
        "job_profile_id": 1,
        "match_score": 0.85,
        "distance": 0.15,
        "analysis": {
            "vector_similarity": 0.85,
            "dimension_score": 0.80,
            "dimension_matches": {
                "技术": {"user_score": 4.0, "job_score": 5.0, "weight": 0.5, "match_ratio": 0.8},
            },
            "weights_used": {"技术": 0.5},
        },
    }]

    with patch("app.domain.services.matching_service.get_user_vector", new_callable=AsyncMock) as mock_vector_fn, \
         patch("app.domain.services.matching_service.match_user_to_jobs", new_callable=AsyncMock) as mock_match_fn:
        mock_vector_fn.return_value = mock_vector
        mock_match_fn.return_value = mock_match_result

        resp = client.post(
            "/api/v1/matching/run",
            json={"profile_id": 1, "top_k": 5},
            headers={"Authorization": f"Bearer {auth_token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == user_id
    assert data["profile_id"] == 1
    assert data["total"] == 1
    assert len(data["results"]) == 1
    assert data["results"][0]["job_profile_id"] == 1
    assert data["results"][0]["match_score"] == 0.85
