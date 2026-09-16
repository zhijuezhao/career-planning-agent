"""Task 5: POST /api/v1/matching/run — snapshot-based matching endpoint.

Builds a flat `app.api.v1` package exposing ONLY auth + matching routers
(the real package is blocked by the R-2.1 admin gate in app.main), mirrors
test_profile_snapshot.py's module-proxy approach.
"""

import importlib
import os
import sys
import time
import types

import pytest
import starlette.testclient as _tc
from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

# ── Build a flat `app.api.v1` package exposing ONLY the auth + matching routers ──
_API_V1_PKG = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app", "api", "v1"))


def _build_v1_router():
    pkg = types.ModuleType("app.api.v1")
    pkg.__path__ = [_API_V1_PKG]
    sys.modules.setdefault("app.api.v1", pkg)
    outer = APIRouter()
    auth = importlib.import_module("app.api.v1.auth").router
    from app.api.v1.matching import router as matching_router
    outer.include_router(auth, prefix="/auth", tags=["auth"])
    outer.include_router(matching_router, prefix="/matching", tags=["matching"])
    pkg.router = outer
    return outer


_BUILD_LOCKED = False
_BUILD = None


def _locked_v1_router():
    global _BUILD, _BUILD_LOCKED
    if not _BUILD_LOCKED:
        _BUILD = _build_v1_router()
        _BUILD_LOCKED = True
    return _BUILD


@pytest.fixture(scope="module")
def app():
    from app.infrastructure.database import async_session_factory

    _locked_v1_router()
    main = importlib.import_module("app.main")
    fastapi_app = main.create_app()

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
    uname = f"match_{int(time.time() * 1000)}"
    r = client.post("/api/v1/auth/register", json={"username": uname, "password": "testpass123456"})
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]
    r = client.post("/api/v1/auth/login", json={"username": uname, "password": "testpass123456"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": user_id}


# ── R-2.1 test contract (offline, no LLM / embeddings / matching DB writes) ──


def test_run_matching_requires_snapshot_id(client, authed_user):
    # Legacy body (profile_id only) is ignored by extra=ignore -> 422.
    r = client.post("/api/v1/matching/run", json={"profile_id": 1}, headers=authed_user["headers"])
    assert r.status_code == 422


def test_run_matching_missing_snapshot_404(client, authed_user):
    r = client.post(
        "/api/v1/matching/run",
        json={"profile_snapshot_id": 999999},
        headers=authed_user["headers"],
    )
    assert r.status_code == 404


# ── matched_at success path (real DB session, empty JobMatchEmbedding table) ──


def seed_snapshot(user_id: int) -> int:
    """Seed a ProfileSnapshot row in its OWN event loop.

    Runs all asyncpg work inside one fresh loop + one NullPool engine so nothing
    is ever touched from a second loop (the TestClient portal loop owns the app
    engine's pooled connections). Returns the snapshot id.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import get_settings
    from app.domain.models import ProfileSnapshot, StudentProfile

    async def _inner() -> int:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                profile = await session.get(StudentProfile, user_id)
                if profile is None:
                    session.add(StudentProfile(user_id=user_id))
                    await session.flush()
                snap = ProfileSnapshot(
                    user_id=user_id,
                    profile_id=user_id,
                    form_raw_json={},
                    five_layers_json={},
                    six_dim_scores_json={},
                    embedding=[0.0] * 1024,
                )
                session.add(snap)
                await session.commit()
                await session.refresh(snap)
                return snap.id
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_inner())
    finally:
        loop.close()


def matched_at_is_set(snapshot_id: int) -> bool:
    """Read matched_at back in a self-contained loop (R-5.4 verification)."""
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import get_settings
    from app.domain.models import ProfileSnapshot

    async def _inner() -> bool:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as session:
                row = (
                    await session.execute(
                        select(ProfileSnapshot).where(ProfileSnapshot.id == snapshot_id)
                    )
                ).scalar_one_or_none()
                return row is not None and row.matched_at is not None
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_inner())
    finally:
        loop.close()


def test_run_matching_success_writes_matched_at(client, authed_user):
    """Seeded snapshot + EMPTY JobMatchEmbedding -> search [] -> 200 total 0, matched_at set (R-5.4)."""
    snap_id = seed_snapshot(authed_user["user_id"])
    r = client.post(
        "/api/v1/matching/run",
        json={"profile_snapshot_id": snap_id},
        headers=authed_user["headers"],
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 0
    assert data["results"] == []
    assert data["profile_snapshot_id"] == snap_id
    assert matched_at_is_set(snap_id)