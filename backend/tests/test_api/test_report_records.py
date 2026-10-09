"""Task 6: report records CRUD + lazy Word + 6-module prompt — API tests.

Self-contained module: does NOT `import app.main` directly. Mirrors the
ratified pattern from test_profile_snapshot.py — installs a flat
`sys.modules["app.api.v1"]` stub package exposing ONLY the routers this
harness needs (profile/auth/reports), then `create_app()` + get_db override.
"""

import importlib
import os
import sys
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import starlette.testclient as _tc
from fastapi import APIRouter

# ── Build a flat `app.api.v1` package exposing ONLY auth + profile + reports ──
# The real `app.api.v1/__init__.py` imports the admin router
# (`admin/career.py → GrowthPath`, deleted in Task 1), so importing
# `app.api.v1` directly (and thus `app.main`) would ImportError pre-gate.
_API_V1_PKG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app", "api", "v1"))


def _build_v1_router():
    pkg = types.ModuleType("app.api.v1")
    pkg.__path__ = [_API_V1_PKG]
    sys.modules.setdefault("app.api.v1", pkg)
    outer = APIRouter()
    auth = importlib.import_module("app.api.v1.auth").router
    profile = importlib.import_module("app.api.v1.profile").router
    reports = importlib.import_module("app.api.v1.reports").router
    outer.include_router(auth, prefix="/auth", tags=["auth"])
    outer.include_router(profile, prefix="", tags=["profile"])
    outer.include_router(reports, prefix="/reports", tags=["reports"])
    pkg.router = outer
    return outer


_BUILD_LOCKED = False


def _locked_v1_router():
    """Build once (module scope), reuse across fixtures."""
    global _BUILD, _BUILD_LOCKED
    if not _BUILD_LOCKED:
        _BUILD = _build_v1_router()
        _BUILD_LOCKED = True
    return _BUILD


_BUILD = None


@pytest.fixture(scope="module")
def app():
    from app.infrastructure.database import async_session_factory

    # `_locked_v1_router()` 靠副作用替换 /api/v1 的 stub router，返回值不需要
    _locked_v1_router()
    main = importlib.import_module("app.main")
    fastapi_app = main.create_app()
    # The stub router is already included by create_app under /api/v1; the
    # dependency override pipes get_db through the TestClient's event loop.

    async def _override_get_db():
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    from app.infrastructure.database import get_db

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    return fastapi_app


@pytest.fixture(scope="module")
def client(app):
    with _tc.TestClient(app) as c:
        yield c


def _register_and_login(client, prefix):
    uname = f"{prefix}_{int(time.time() * 1000)}"
    r = client.post("/api/v1/auth/register", json={"username": uname, "password": "testpass123456"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"username": uname, "password": "testpass123456"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "id": None}


@pytest.fixture(scope="module")
def authed_user(client):
    return _register_and_login(client, "rec")


def _poll_until_done(client, headers, task_id, tries=40, interval=0.1):
    for _ in range(tries):
        time.sleep(interval)
        r = client.get(f"/api/v1/profile/snapshot/{task_id}", headers=headers)
        if r.status_code == 200 and r.json().get("status") == "done":
            return r
    return r


def make_snap(client, authed_user):
    """Seed resume_form → snapshot → poll done → return snapshot_id."""
    headers = authed_user["headers"]
    form = {
        "basic_info": {"name": "张三", "school": "XX大学", "degree": "本科"},
        "intention": {"target_position": ["后端开发"], "target_city": ["上海"]},
    }
    r = client.put("/api/v1/profile", json={"resume_form": form}, headers=headers)
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/profile/snapshot", headers=headers)
    assert r.status_code == 200, r.text
    task_id = r.json()["task_id"]
    poll = _poll_until_done(client, headers, task_id)
    assert poll.status_code == 200, poll.text
    assert poll.json()["status"] == "done", poll.text
    return poll.json()["snapshot_id"]


def _threerec():
    return [
        {"job_profile_id": 1, "match_score": 0.85},
        {"job_profile_id": 2, "match_score": 0.72},
        {"job_profile_id": 3, "match_score": 0.68},
    ]


MOCK_REPORT_TEXT = (
    "# 生涯发展报告\n\n"
    "## 模块一 个人概况\n张三的基本信息。\n\n"
    "## 模块二 能力优势分析\n优势分析。\n\n"
    "## 模块三 待提升领域\n待提升领域。\n\n"
    "## 模块四 岗位匹配对比分析\n三个岗位对比。\n\n"
    "## 模块五 职业匹配建议\n匹配建议。\n\n"
    "## 模块六 成长路径建议\n成长路径建议。\n"
)


@pytest.fixture
def mock_report_text():
    """Patch the LLM seam: _build_report_modern returns fixed text (no network)."""
    with patch(
        "app.domain.services.report_service._build_report_modern",
        new=AsyncMock(return_value=MOCK_REPORT_TEXT),
    ):
        yield MOCK_REPORT_TEXT


# ── tests ────────────────────────────────────────────────────────────────────


def test_generate_requires_exact_3_matching_results(client, authed_user, mock_report_text):
    sid = make_snap(client, authed_user)
    headers = authed_user["headers"]

    # (a) matching_results is a REQUIRED field — absent → 422 via validation
    r = client.post("/api/v1/reports/generate", json={"profile_snapshot_id": sid}, headers=headers)
    assert r.status_code == 422, r.text
    assert "matching_results" in str(r.json()["detail"])

    # (b) len != 3 → 422 (exactly-3 contract)
    r = client.post(
        "/api/v1/reports/generate",
        json={"profile_snapshot_id": sid, "matching_results": _threerec()[:2]},
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert "必须恰为 3 项" in r.json()["detail"]


def test_generate_other_users_snapshot_404(client, authed_user, mock_report_text):
    sid = make_snap(client, authed_user)
    stranger = _register_and_login(client, "other")
    r = client.post(
        "/api/v1/reports/generate",
        json={"profile_snapshot_id": sid, "matching_results": _threerec()},
        headers=stranger["headers"],
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "快照不存在"


def test_generate_record_not_found_404(client, authed_user):
    r = client.get("/api/v1/reports/records/99999999", headers=authed_user["headers"])
    assert r.status_code == 404, r.text


def test_generate_and_list_and_download(client, authed_user, mock_report_text):
    sid = make_snap(client, authed_user)
    headers = authed_user["headers"]

    r = client.post(
        "/api/v1/reports/generate",
        json={"profile_snapshot_id": sid, "matching_results": _threerec()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_text"]
    assert "模块四 岗位匹配对比分析" in body["report_text"]
    rid = body["id"]
    assert body["version"] == 1
    assert body["serial_no"]
    assert body["description"] == "第1版"

    # list (summary, no report_text)
    lst = client.get("/api/v1/reports/records", headers=headers)
    assert lst.status_code == 200, lst.text
    items = lst.json()
    assert isinstance(items, list)
    match = next(x for x in items if x["id"] == rid)
    assert match["version"] == 1
    assert "report_text" not in match

    # detail (full text)
    det = client.get(f"/api/v1/reports/records/{rid}", headers=headers)
    assert det.status_code == 200, det.text
    assert det.json()["report_text"] == MOCK_REPORT_TEXT

    # lazy Word download: real docx generated offline
    dl = client.get(f"/api/v1/reports/records/{rid}/download", headers=headers)
    assert dl.status_code == 200, dl.text
    assert dl.headers["content-type"].startswith("application/vnd")
    assert dl.content[:2] == b"PK"  # zip magic: valid docx container

    # download set word_file_path — verify persisted + file on disk
    det2 = client.get(f"/api/v1/reports/records/{rid}", headers=headers)
    wfp = det2.json()["word_file_path"]
    assert wfp, "word_file_path must be filled after lazy generation"
    assert Path(wfp).exists()
    assert wfp.endswith(f"{body['serial_no']}.docx")

    # second download short-circuits (cached path, still 200)
    dl2 = client.get(f"/api/v1/reports/records/{rid}/download", headers=headers)
    assert dl2.status_code == 200, dl2.text
