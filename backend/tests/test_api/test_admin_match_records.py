"""B2-3 管理端「匹配明细」API 测试 + 学生端落库串通（真实 dev DB）。

覆盖：
    * 列表/筛选（快照、岗位、状态、用户）与统计；
    * 详情（含 analysis）；
    * **学生端 `/matching/run` 落明细 → 管理端立刻可见**（打桩掉向量计算，其余走真代码）。
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from app.domain.models.job import JobProfile
from app.domain.models.match_record import JobMatchRecord
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.student_profile import StudentProfile
from app.domain.models.user import User
from app.domain.services.match_record_service import save_match_run
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from tests.conftest import test_session_factory

_ts = int(time.time())
_PREFIX = f"b23api_{_ts}"

_ANALYSIS = {
    "vector_similarity": 0.9,
    "dimension_score": 0.7,
    "dimension_matches": {
        "技术": {"user_score": 4.0, "job_score": 5.0, "weight": 1.0, "match_ratio": 0.8}
    },
    "weights_used": {"技术": 1.0},
}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


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
            await session.execute(delete(ProfileSnapshot).where(ProfileSnapshot.id.in_(snapshot_ids)))
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


@pytest.fixture(scope="module", autouse=True)
def clean_b23api_rows():
    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


async def _seed_user_with_snapshot() -> tuple[int, int]:
    """临时用户 + student_profile + 快照（非零向量），返回 (user_id, snapshot_id)。"""
    async with test_session_factory() as session:
        user = User(
            username=f"{_PREFIX}_{uuid.uuid4().hex[:8]}",
            password_hash="not-a-real-hash",
            role="student",
            status=1,
        )
        session.add(user)
        await session.flush()
        session.add(StudentProfile(user_id=user.id, resume_form={}))
        await session.flush()  # 必须先有 student_profiles 行（快照 profile_id 外键指向它）
        snap = ProfileSnapshot(
            user_id=user.id,
            profile_id=user.id,
            form_raw_json={},
            five_layers_json={},
            six_dim_scores_json={"技术": 4.0},
            embedding=[0.1] * 1024,
            serial_no=uuid.uuid4(),
            description=_PREFIX,
        )
        session.add(snap)
        await session.flush()
        await session.commit()
        return user.id, snap.id


async def _seed_records() -> dict[str, int]:
    """一个快照 + 两个岗位 + 1 成功 1 失败明细。"""
    snapshot_id = (await _seed_user_with_snapshot())[1]
    async with test_session_factory() as session:
        job_ok = JobProfile(title=f"{_PREFIX}_岗位OK", industry="互联网")
        job_bad = JobProfile(title=f"{_PREFIX}_岗位FAIL", industry="互联网")
        session.add_all([job_ok, job_bad])
        await session.flush()
        await save_match_run(
            session,
            snapshot_id=snapshot_id,
            results=[
                {
                    "job_profile_id": job_ok.id,
                    "match_score": 0.91,
                    "distance": 0.09,
                    "analysis": _ANALYSIS,
                }
            ],
            failures=[{"job_profile_id": job_bad.id, "error": "RuntimeError: boom"}],
            duration_ms=321,
        )
        await session.commit()
        return {
            "snapshot_id": snapshot_id,
            "job_ok": job_ok.id,
            "job_bad": job_bad.id,
        }


@pytest.fixture(scope="module")
def seeded() -> dict[str, int]:
    return asyncio.run(_seed_records())


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestMatchRecordAuth:
    def test_forbidden_for_student(self, client: TestClient, student_token: str):
        resp = client.get("/api/v1/admin/matching/records", headers=_headers(student_token))
        assert resp.status_code == 403

    def test_stats_forbidden_for_student(self, client: TestClient, student_token: str):
        resp = client.get("/api/v1/admin/matching/records/stats", headers=_headers(student_token))
        assert resp.status_code == 403


class TestMatchRecordList:
    def test_list_contains_seeded_rows(self, client: TestClient, admin_token: str, seeded):
        resp = client.get(
            "/api/v1/admin/matching/records",
            params={"snapshot_id": seeded["snapshot_id"]},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 2
        by_status = {item["status"]: item for item in data["items"]}
        assert by_status["success"]["score"] == 0.91
        assert by_status["success"]["job_title"] == f"{_PREFIX}_岗位OK"
        assert by_status["success"]["rank"] == 1
        assert by_status["success"]["duration_ms"] == 321
        assert by_status["failed"]["rank"] == 0
        assert by_status["failed"]["score"] is None
        # 列表刻意不带 analysis（体积大，走详情接口）
        assert "analysis" not in by_status["success"]

    def test_filter_by_status_and_job(self, client: TestClient, admin_token: str, seeded):
        resp = client.get(
            "/api/v1/admin/matching/records",
            params={"snapshot_id": seeded["snapshot_id"], "status": "failed"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["job_profile_id"] == seeded["job_bad"]

        resp = client.get(
            "/api/v1/admin/matching/records",
            params={"job_profile_id": seeded["job_ok"]},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200
        assert all(i["job_profile_id"] == seeded["job_ok"] for i in resp.json()["items"])

    def test_invalid_status_rejected(self, client: TestClient, admin_token: str):
        resp = client.get(
            "/api/v1/admin/matching/records",
            params={"status": "bogus"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 422

    def test_stats(self, client: TestClient, admin_token: str, seeded):
        resp = client.get("/api/v1/admin/matching/records/stats", headers=_headers(admin_token))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] >= 2
        assert data["success"] >= 1
        assert data["failed"] >= 1
        assert data["snapshots"] >= 1
        assert data["avg_duration_ms"] is not None


class TestMatchRecordDetail:
    def test_detail_has_analysis(self, client: TestClient, admin_token: str, seeded):
        listed = client.get(
            "/api/v1/admin/matching/records",
            params={"snapshot_id": seeded["snapshot_id"], "status": "success"},
            headers=_headers(admin_token),
        ).json()["items"]
        record_id = listed[0]["id"]

        resp = client.get(
            f"/api/v1/admin/matching/records/{record_id}", headers=_headers(admin_token)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["analysis"]["dimension_score"] == 0.7
        assert data["job_industry"] == "互联网"

    def test_detail_404(self, client: TestClient, admin_token: str):
        resp = client.get(
            "/api/v1/admin/matching/records/99999999", headers=_headers(admin_token)
        )
        assert resp.status_code == 404


class TestStudentRunPersistsRecords:
    def test_student_run_writes_records_visible_to_admin(
        self, client: TestClient, admin_token: str, monkeypatch
    ):
        """学生端跑一次匹配 → 明细落库 → 管理端立刻能查到（B2-3 验收点）。"""
        _user_id, snapshot_id = asyncio.run(_seed_user_with_snapshot())

        async def _seed_job() -> int:
            async with test_session_factory() as session:
                job = JobProfile(title=f"{_PREFIX}_学生端命中岗位", industry="互联网")
                session.add(job)
                await session.flush()
                await session.commit()
                return job.id

        job_id = asyncio.run(_seed_job())

        canned = (
            [
                {
                    "job_profile_id": job_id,
                    "match_score": 0.88,
                    "distance": 0.12,
                    "analysis": _ANALYSIS,
                }
            ],
            [],
        )

        async def _fake_match(**kwargs):
            return canned

        monkeypatch.setattr(
            "app.domain.services.matching_service.match_user_to_jobs_detailed", _fake_match
        )

        # 用快照属主的身份签发 token（require_auth 只读 payload["sub"] 并校验用户存在/启用）
        async def _owner_token() -> str:
            async with test_session_factory() as session:
                snap = await session.get(ProfileSnapshot, snapshot_id)
                assert snap is not None
                from app.infrastructure.security import create_access_token

                return create_access_token({"sub": str(snap.user_id)})

        token = asyncio.run(_owner_token())

        resp = client.post(
            "/api/v1/matching/run",
            json={"profile_snapshot_id": snapshot_id, "top_k": 3},
            headers=_headers(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 1

        admin_list = client.get(
            "/api/v1/admin/matching/records",
            params={"snapshot_id": snapshot_id},
            headers=_headers(admin_token),
        )
        assert admin_list.status_code == 200, admin_list.text
        items = admin_list.json()["items"]
        assert len(items) == 1
        assert items[0]["job_profile_id"] == job_id
        assert items[0]["score"] == 0.88
        assert items[0]["status"] == "success"
        assert items[0]["duration_ms"] is not None
