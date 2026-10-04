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
    uname = f"t12_2_user_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "testpass123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "testpass123456",
    })
    return resp.json()["access_token"]


MINIMAL_PDF = b"""\
%PDF-1.0
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Contents 4 0 R\
/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>
stream
BT /F1 12 Tf 100 700 Td (Hello Resume) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000360 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
434
%%EOF"""


@pytest.fixture(scope="module")
def uploaded_resume_id(client: TestClient, auth_token: str) -> int:
    resp = client.post(
        "/api/v1/resume/upload",
        files={"file": ("test.pdf", MINIMAL_PDF, "application/pdf")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "parsed"
    return resp.json()["resume_id"]


def test_same_pdf_uploaded_twice_reuses_parsed_result(
    client: TestClient, auth_token: str, uploaded_resume_id: int
):
    """回归（2026-10-04 事故）：同一份 PDF 重复上传必须**复用**已解析结果。

    事故链条：本接口是**同步解析**（LLM 跑完才返回，实测 1 页 PDF 35–40 秒），
    而学生端 axios 全局超时是 **30 秒** → 客户端先 abort、后端照常跑完并落库，
    用户看到"解析失败，请重试"就再传一次。实测同一份简历（content_hash 相同）
    被完整解析 **3 次**：3 条重复记录 + 3 次 LLM 花费。

    修法：上传前按 `(user_id, content_hash, status='parsed')` 查已有记录，命中就复用
    （`five_layers` 由 `parsed_data` 本地重算，零 LLM）。所以这里断言 resume_id 不变。
    """
    resp = client.post(
        "/api/v1/resume/upload",
        files={"file": ("again.pdf", MINIMAL_PDF, "application/pdf")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["resume_id"] == uploaded_resume_id, "重复上传不该新建简历记录"
    assert body["status"] == "parsed"
    # 复用路径要能把 five_layers 还原出来（纯本地映射）；还原失败会被降级成 None
    assert body["five_layers"] is not None


def test_get_latest_resume(client: TestClient, auth_token: str, uploaded_resume_id: int):
    resp = client.get(
        "/api/v1/resume/latest",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == uploaded_resume_id
    assert "status" in data
    assert "created_at" in data


def test_get_resume_detail(client: TestClient, auth_token: str, uploaded_resume_id: int):
    resp = client.get(
        f"/api/v1/resume/{uploaded_resume_id}",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == uploaded_resume_id
    assert data["file_name"] == "test.pdf"
    assert "parsed_data" in data


def test_get_resume_not_found(client: TestClient, auth_token: str):
    resp = client.get(
        "/api/v1/resume/999999",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 404


def test_get_report_no_profile(client: TestClient, auth_token: str, uploaded_resume_id: int):
    resp = client.get(
        f"/api/v1/resume/{uploaded_resume_id}/radar",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 200


def test_latest_unauthorized(client: TestClient):
    resp = client.get("/api/v1/resume/latest")
    assert resp.status_code == 422


def test_detail_unauthorized(client: TestClient):
    resp = client.get("/api/v1/resume/1")
    assert resp.status_code == 422
