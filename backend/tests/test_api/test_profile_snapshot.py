import importlib
import os
import sys
import time
import types

import pytest
import starlette.testclient as _tc
from fastapi import APIRouter

# ── Build a flat `app.api.v1` package exposing ONLY the auth + profile routers ──
# The real `app.api.v1/__init__.py` imports the R-2.1-would-block admin router
# (`admin/career.py → GrowthPath`, deleted in Task 1), so `import app.main`
# must see a stub module that provides `router` without the wall.
_API_V1_PKG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app", "api", "v1"))


def _build_v1_router():
    pkg = types.ModuleType("app.api.v1")
    pkg.__path__ = [_API_V1_PKG]
    sys.modules.setdefault("app.api.v1", pkg)
    outer = APIRouter()
    profile = importlib.import_module("app.api.v1.profile").router
    auth = importlib.import_module("app.api.v1.auth").router
    from app.infrastructure.database import get_db  # resolve against real module
    outer.include_router(profile, prefix="", tags=["profile"])
    outer.include_router(auth, prefix="/auth", tags=["auth"])
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

    v1 = _locked_v1_router()
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


@pytest.fixture(scope="module")
def authed_user(client):
    uname = f"snap_{int(time.time() * 1000)}"
    r = client.post("/api/v1/auth/register", json={"username": uname, "password": "testpass123456"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"username": uname, "password": "testpass123456"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}}


def _poll_until_done(client, headers, task_id, tries=20, interval=0.2):
    for _ in range(tries):
        time.sleep(interval)
        r = client.get(f"/api/v1/profile/snapshot/{task_id}", headers=headers)
        if r.status_code == 200 and r.json().get("status") == "done":
            return r
    return r


# ── tests ────────────────────────────────────────────────────────────────────


def test_profile_put_get_roundtrip(client, authed_user):
    headers = authed_user["headers"]
    form = {"basic": {"name": "Zhang San"}, "intention": {"positions": ["backend"]}}
    r = client.put("/api/v1/profile", json={"resume_form": form}, headers=headers)
    assert r.status_code == 200
    assert r.json()["resume_form"] == form
    r = client.get("/api/v1/profile", headers=headers)
    assert r.status_code == 200
    assert r.json()["resume_form"] == form


def test_snapshot_create_poll_list_detail(client, authed_user):
    headers = authed_user["headers"]
    form = {"basic": {"name": "Zhang San"}}
    client.put("/api/v1/profile", json={"resume_form": form}, headers=headers)

    r = client.post("/api/v1/profile/snapshot", headers=headers)
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    poll = _poll_until_done(client, headers, task_id)
    assert poll.status_code == 200
    assert poll.json()["status"] == "done"
    sid1 = poll.json()["snapshot_id"]

    lst = client.get("/api/v1/profile/snapshots", headers=headers)
    assert lst.status_code == 200
    items = lst.json()
    assert isinstance(items, list)
    assert any(item["id"] == sid1 for item in items)
    assert "serial_no" in items[0]
    assert "form" not in items[0]

    det = client.get(f"/api/v1/profile/snapshots/{sid1}", headers=headers)
    assert det.status_code == 200
    data = det.json()
    assert data["id"] == sid1
    assert data["form"] == form
    assert isinstance(data["has_embedding"], bool)


def test_snapshot_dedup_same_id(client, authed_user):
    headers = authed_user["headers"]
    r1 = client.post("/api/v1/profile/snapshot", headers=headers)
    assert r1.status_code == 200
    task_id1 = r1.json()["task_id"]
    poll1 = _poll_until_done(client, headers, task_id1)
    sid1 = poll1.json()["snapshot_id"]

    r2 = client.post("/api/v1/profile/snapshot", headers=headers)
    assert r2.status_code == 200
    task_id2 = r2.json()["task_id"]
    assert task_id2 != task_id1
    poll2 = _poll_until_done(client, headers, task_id2)
    assert poll2.json()["snapshot_id"] == sid1

    lst = client.get("/api/v1/profile/snapshots", headers=headers)
    assert len(lst.json()) == 1


def test_unknown_task_404(client, authed_user):
    r = client.get("/api/v1/profile/snapshot/deadbeef", headers=authed_user["headers"])
    assert r.status_code == 404