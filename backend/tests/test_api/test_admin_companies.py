"""B2-2 管理端「公司信息导航」API 测试（真实 dev DB）。

数据准备直接走服务层（`upsert_job_profile`）——管理端**没有**新建公司的入口是刻意的：
公司由导入/岗位落库时自动识别，管理端只做人工修正（PUT）、重算（sync）与删除。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from app.domain.services.job_persist_service import upsert_job_profile
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.conftest import test_session_factory

_ts = str(int(time.time()))
_PREFIX = f"b22api_{_ts}"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _company(name: str) -> str:
    return f"{_PREFIX}_{name}"


def _title(name: str) -> str:
    return f"{_PREFIX}_{name}"


async def _cleanup() -> None:
    async with test_session_factory() as session:
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM job_raw_data WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.commit()


async def _seed() -> dict[str, int]:
    """两家公司：甲公司 2 个岗位、乙公司 1 个岗位。返回 {公司名: id}。"""
    async with test_session_factory() as session:
        for name, title, industry, city in (
            ("甲", "Java 工程师", "互联网", "北京"),
            ("甲", "Java 架构师", "互联网", "北京"),
            ("乙", "数据分析师", "金融", "上海"),
        ):
            await upsert_job_profile(
                session,
                {
                    "title": _title(title),
                    "company": _company(name),
                    "industry": industry,
                    "city": city,
                    "salary": "20-30K",
                },
            )
        await session.commit()

        rows = (
            await session.execute(
                text("SELECT id, name FROM companies WHERE name LIKE :p"), {"p": f"{_PREFIX}%"}
            )
        ).all()
        return {row[1]: row[0] for row in rows}


@pytest.fixture(scope="module", autouse=True)
def clean_b22api_rows():
    """进模块先清一次（防上次中断残留），出模块彻底清理本前缀数据。"""
    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


@pytest.fixture(scope="module")
def seeded() -> dict[str, int]:
    return asyncio.run(_seed())


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestCompanyAuth:
    def test_list_forbidden_for_student(self, client: TestClient, student_token: str):
        resp = client.get("/api/v1/admin/companies", headers=_headers(student_token))
        assert resp.status_code == 403


class TestCompanyList:
    def test_list_orders_by_job_count(self, client: TestClient, admin_token: str, seeded):
        resp = client.get("/api/v1/admin/companies", headers=_headers(admin_token))
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        mine = [i for i in items if i["name"].startswith(_PREFIX)]
        assert [i["name"] for i in mine] == [_company("甲"), _company("乙")]  # 2 个岗位在前
        assert [i["job_count"] for i in mine] == [2, 1]

    def test_search_and_only_with_jobs(self, client: TestClient, admin_token: str, seeded):
        resp = client.get(
            "/api/v1/admin/companies",
            params={"q": _company("乙")},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200
        names = [i["name"] for i in resp.json()["items"]]
        assert names == [_company("乙")]

        listed = client.get(
            "/api/v1/admin/companies",
            params={"q": _PREFIX, "only_with_jobs": True},
            headers=_headers(admin_token),
        ).json()["items"]
        assert all(item["job_count"] > 0 for item in listed)

    def test_filter_by_industry_and_city(self, client: TestClient, admin_token: str, seeded):
        items = client.get(
            "/api/v1/admin/companies",
            params={"q": _PREFIX, "industry": "金融"},
            headers=_headers(admin_token),
        ).json()["items"]
        assert [i["name"] for i in items] == [_company("乙")]

        items = client.get(
            "/api/v1/admin/companies",
            params={"q": _PREFIX, "city": "北京"},
            headers=_headers(admin_token),
        ).json()["items"]
        assert [i["name"] for i in items] == [_company("甲")]


class TestCompanyDetail:
    def test_detail_lists_jobs(self, client: TestClient, admin_token: str, seeded):
        company_id = seeded[_company("甲")]
        resp = client.get(f"/api/v1/admin/companies/{company_id}", headers=_headers(admin_token))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == _company("甲")
        assert data["job_count"] == 2
        assert {j["title"] for j in data["jobs"]} == {_title("Java 工程师"), _title("Java 架构师")}

    def test_detail_404(self, client: TestClient, admin_token: str):
        resp = client.get("/api/v1/admin/companies/99999999", headers=_headers(admin_token))
        assert resp.status_code == 404


class TestCompanyWrite:
    def test_update_industry_and_city(self, client: TestClient, admin_token: str, seeded):
        company_id = seeded[_company("乙")]
        try:
            resp = client.put(
                f"/api/v1/admin/companies/{company_id}",
                json={"industry": "金融科技", "city": "杭州"},
                headers=_headers(admin_token),
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["industry"] == "金融科技"
            assert data["city"] == "杭州"
        finally:
            client.put(
                f"/api/v1/admin/companies/{company_id}",
                json={"industry": "金融", "city": "上海"},
                headers=_headers(admin_token),
            )

    def test_rename_conflict_409(self, client: TestClient, admin_token: str, seeded):
        resp = client.put(
            f"/api/v1/admin/companies/{seeded[_company('乙')]}",
            json={"name": _company("甲")},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 409

    def test_sync_recomputes_job_count(self, client: TestClient, admin_token: str, seeded):
        company_id = seeded[_company("甲")]

        async def _dirty() -> None:
            async with test_session_factory() as session:
                await session.execute(
                    text("UPDATE companies SET job_count = 999 WHERE id = :i"), {"i": company_id}
                )
                await session.commit()

        asyncio.run(_dirty())

        resp = client.post("/api/v1/admin/companies/sync", headers=_headers(admin_token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["synced"] >= 2

        data = client.get(
            f"/api/v1/admin/companies/{company_id}", headers=_headers(admin_token)
        ).json()
        assert data["job_count"] == 2


class TestCompanyDeleteKeepsJobs:
    def test_delete_unbinds_jobs(self, client: TestClient, admin_token: str):
        """删除公司不得删岗位：外键 ON DELETE SET NULL，只解绑。"""

        async def _seed_one() -> tuple[int, int]:
            async with test_session_factory() as session:
                profile, _ = await upsert_job_profile(
                    session, {"title": _title("待解绑岗位"), "company": _company("待删公司")}
                )
                await session.commit()
                return int(profile.id), int(profile.company_id or 0)

        profile_id, company_id = asyncio.run(_seed_one())

        resp = client.delete(
            f"/api/v1/admin/companies/{company_id}", headers=_headers(admin_token)
        )
        assert resp.status_code == 204

        async def _company_id_of_profile() -> tuple[bool, int | None]:
            async with test_session_factory() as session:
                row = (
                    await session.execute(
                        text("SELECT company_id FROM job_profiles WHERE id = :i"),
                        {"i": profile_id},
                    )
                ).scalar_one_or_none()
                exists = (
                    await session.execute(
                        text("SELECT count(*) FROM companies WHERE id = :i"), {"i": company_id}
                    )
                ).scalar_one()
                return bool(exists), row

        company_exists, profile_company_id = asyncio.run(_company_id_of_profile())
        assert company_exists is False  # 公司没了
        assert profile_company_id is None  # 岗位还在，只是解绑

        resp = client.get(f"/api/v1/admin/jobs/{profile_id}", headers=_headers(admin_token))
        assert resp.status_code == 200
        assert resp.json()["company_id"] is None


class TestJobsFilterByCompany:
    def test_jobs_filter_and_company_name(self, client: TestClient, admin_token: str, seeded):
        company_id = seeded[_company("甲")]
        resp = client.get(
            "/api/v1/admin/jobs",
            params={"company_id": company_id},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 2
        assert all(item["company_id"] == company_id for item in data["items"])
        assert all(item["company_name"] == _company("甲") for item in data["items"])

    def test_jobs_without_company_filter_still_works(self, client: TestClient, admin_token: str):
        resp = client.get("/api/v1/admin/jobs", params={"limit": 1}, headers=_headers(admin_token))
        assert resp.status_code == 200
        assert "items" in resp.json()
