"""B2-3 测试：匹配明细落库（覆盖语义 / 失败行 / 服务层串通）。

真实 dev DB；数据用 `b23_<ts>_*` 前缀的用户与岗位 + 临时快照，跑完精确清理。
"""

from __future__ import annotations

import time
import uuid

import pytest
from app.domain.models.job import JobProfile
from app.domain.models.match_record import JobMatchRecord
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.student_profile import StudentProfile
from app.domain.models.user import User
from app.domain.services.match_record_service import save_match_run
from app.domain.services.matching_service import run_matching
from sqlalchemy import delete, func, select, text
from tests.conftest import test_session_factory

_ts = int(time.time())
_PREFIX = f"b23_{_ts}"

_ANALYSIS = {
    "vector_similarity": 0.81,
    "dimension_score": 0.66,
    "dimension_matches": {
        "技术": {"user_score": 4.0, "job_score": 5.0, "weight": 1.0, "match_ratio": 0.8}
    },
    "weights_used": {"技术": 1.0},
}


async def _cleanup() -> None:
    async with test_session_factory() as session:
        snapshot_ids = list(
            (
                await session.execute(
                    select(ProfileSnapshot.id).where(ProfileSnapshot.description == _PREFIX)
                )
            )
            .scalars()
            .all()
        )
        if snapshot_ids:
            await session.execute(
                delete(JobMatchRecord).where(JobMatchRecord.profile_snapshot_id.in_(snapshot_ids))
            )
            await session.execute(
                delete(ProfileSnapshot).where(ProfileSnapshot.id.in_(snapshot_ids))
            )
        await session.execute(
            text(
                "DELETE FROM student_profiles WHERE user_id IN "
                "(SELECT id FROM users WHERE username LIKE :p)"
            ),
            {"p": f"{_PREFIX}%"},
        )
        await session.execute(text("DELETE FROM users WHERE username LIKE :p"), {"p": f"{_PREFIX}%"})
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.commit()


async def _make_user(session) -> int:
    """建临时用户 + student_profile（快照对两者都有外键）。"""
    user = User(
        username=f"{_PREFIX}_{uuid.uuid4().hex[:8]}",
        password_hash="not-a-real-hash",
        role="student",
        status=1,
    )
    session.add(user)
    await session.flush()
    session.add(StudentProfile(user_id=user.id, resume_form={}))
    await session.flush()
    return user.id


async def _make_snapshot(session, *, vector: list[float] | None = None) -> ProfileSnapshot:
    """建一个临时快照（embedding 直接写 pgvector，避免依赖真实 embedding 服务）。"""
    user_id = await _make_user(session)
    snap = ProfileSnapshot(
        user_id=user_id,
        profile_id=user_id,
        form_raw_json={"seeded": True},
        five_layers_json={"hard_skills": {"tags": ["Python"]}},
        six_dim_scores_json={"技术": 4.0, "实践": 3.0},
        embedding=vector or [0.0] * 1024,
        serial_no=uuid.uuid4(),
        description=_PREFIX,
    )
    session.add(snap)
    await session.flush()
    return snap


async def _make_job(session, name: str) -> JobProfile:
    job = JobProfile(title=f"{_PREFIX}_{name}", industry="互联网")
    session.add(job)
    await session.flush()
    return job


@pytest.fixture(autouse=True)
def clean_b23_rows():
    import asyncio

    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


class TestSaveMatchRun:
    async def test_saves_ranked_records(self):
        async with test_session_factory() as session:
            snap = await _make_snapshot(session)
            job_a = await _make_job(session, "岗位A")
            job_b = await _make_job(session, "岗位B")

            stats = await save_match_run(
                session,
                snapshot_id=snap.id,
                results=[
                    {"job_profile_id": job_a.id, "match_score": 0.9, "distance": 0.1, "analysis": _ANALYSIS},
                    {"job_profile_id": job_b.id, "match_score": 0.7, "distance": 0.3, "analysis": _ANALYSIS},
                ],
                duration_ms=1234,
            )
            await session.commit()

            assert stats == {"replaced": 0, "saved": 2, "failed": 0}

            rows = list(
                (
                    await session.execute(
                        select(JobMatchRecord)
                        .where(JobMatchRecord.profile_snapshot_id == snap.id)
                        .order_by(JobMatchRecord.rank)
                    )
                )
                .scalars()
                .all()
            )
            assert [(r.rank, r.status, r.score) for r in rows] == [
                (1, "success", 0.9),
                (2, "success", 0.7),
            ]
            assert all(r.duration_ms == 1234 for r in rows)
            assert rows[0].analysis["dimension_score"] == 0.66

    async def test_rerun_replaces_previous_records(self):
        """同一快照重复匹配 → 覆盖，不追加（避免明细表膨胀 / 页面混着多次运行）。"""
        async with test_session_factory() as session:
            snap = await _make_snapshot(session)
            job_a = await _make_job(session, "岗位C")

            await save_match_run(
                session,
                snapshot_id=snap.id,
                results=[
                    {"job_profile_id": job_a.id, "match_score": 0.5, "distance": 0.4, "analysis": _ANALYSIS}
                ],
                duration_ms=10,
            )
            await session.commit()

            second = await save_match_run(
                session,
                snapshot_id=snap.id,
                results=[
                    {"job_profile_id": job_a.id, "match_score": 0.95, "distance": 0.05, "analysis": _ANALYSIS}
                ],
                duration_ms=20,
            )
            await session.commit()

            assert second == {"replaced": 1, "saved": 1, "failed": 0}
            rows = list(
                (
                    await session.execute(
                        select(JobMatchRecord).where(JobMatchRecord.profile_snapshot_id == snap.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].score == 0.95
            assert rows[0].duration_ms == 20

    async def test_failed_rows_recorded_without_rank(self):
        async with test_session_factory() as session:
            snap = await _make_snapshot(session)
            job_ok = await _make_job(session, "岗位D")
            job_bad = await _make_job(session, "岗位E")

            stats = await save_match_run(
                session,
                snapshot_id=snap.id,
                results=[
                    {"job_profile_id": job_ok.id, "match_score": 0.8, "distance": 0.2, "analysis": _ANALYSIS}
                ],
                failures=[{"job_profile_id": job_bad.id, "error": "RuntimeError: boom"}],
                duration_ms=99,
            )
            await session.commit()

            assert stats == {"replaced": 0, "saved": 1, "failed": 1}
            failed = (
                await session.execute(
                    select(JobMatchRecord).where(
                        JobMatchRecord.profile_snapshot_id == snap.id,
                        JobMatchRecord.status == "failed",
                    )
                )
            ).scalar_one()
            assert failed.rank == 0
            assert failed.score is None
            assert failed.analysis == {"error": "RuntimeError: boom"}


class TestRunMatchingPersists:
    async def test_zero_vector_snapshot_persists_nothing_but_succeeds(self):
        """全零向量（embedding 降级）→ 无命中，但服务层仍正常返回（不落任何明细）。"""
        async with test_session_factory() as session:
            snap = await _make_snapshot(session)
            await session.commit()

            outcome = await run_matching(snap.user_id, snap, top_k=5, max_distance=0.65, db=session)
            await session.commit()

            assert outcome.items == []
            assert outcome.records_saved == 0
            assert outcome.duration_ms >= 0
            total = (
                await session.execute(
                    select(func.count())
                    .select_from(JobMatchRecord)
                    .where(JobMatchRecord.profile_snapshot_id == snap.id)
                )
            ).scalar_one()
            assert total == 0

    async def test_without_session_skips_persistence(self):
        """不传 session（纯计算）时不落库、也不报错。"""
        async with test_session_factory() as session:
            snap = await _make_snapshot(session)
            await session.commit()
            snap_id = snap.id
            user_id = snap.user_id

        async with test_session_factory() as session:
            fresh = await session.get(ProfileSnapshot, snap_id)
            assert fresh is not None
            outcome = await run_matching(user_id, fresh, db=None)

        assert outcome.records_saved == 0
        async with test_session_factory() as session:
            total = (
                await session.execute(
                    select(func.count())
                    .select_from(JobMatchRecord)
                    .where(JobMatchRecord.profile_snapshot_id == snap_id)
                )
            ).scalar_one()
            assert total == 0
