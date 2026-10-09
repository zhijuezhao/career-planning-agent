import time

import pytest
from app.main import app
from fastapi.testclient import TestClient

# 本模块要走「上传 → 解析落库」链路，而 CI 没有任何 LLM key：
# 用 conftest 的确定性替身（零网络、零计费）替换解析 LLM，见 offline_resume_parser 注释。
pytestmark = pytest.mark.usefixtures("offline_resume_parser")

_ts = str(int(time.time()))

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
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_token(client: TestClient) -> str:
    uname = f"resume_user_{_ts}"
    client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": "testpass123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": "testpass123456",
    })
    return resp.json()["access_token"]


def test_upload_pdf_success(client: TestClient, auth_token: str):
    resp = client.post(
        "/api/v1/resume/upload",
        files={"file": ("resume.pdf", MINIMAL_PDF, "application/pdf")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "resume_id" in data
    assert data["status"] == "parsed"


def test_upload_non_pdf_rejected(client: TestClient, auth_token: str):
    resp = client.post(
        "/api/v1/resume/upload",
        files={"file": ("readme.txt", b"not a pdf", "text/plain")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_upload_invalid_pdf_magic(client: TestClient, auth_token: str):
    fake_pdf = b"NOT_A_PDF_FILE_CONTENT_HERE"
    resp = client.post(
        "/api/v1/resume/upload",
        files={"file": ("fake.pdf", fake_pdf, "application/pdf")},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 400
    assert "Invalid PDF" in resp.json()["detail"]


def test_upload_unauthorized(client: TestClient):
    resp = client.post(
        "/api/v1/resume/upload",
        files={"file": ("resume.pdf", MINIMAL_PDF, "application/pdf")},
    )
    assert resp.status_code == 422
