"""B2-2 管理端「公司信息导航」API 测试（真实 dev DB）。

数据准备直接走服务层（`upsert_job_profile`）——管理端**没有**新建公司的入口是刻意的：
公司由导入/岗位落库时自动识别，管理端只做人工修正（PUT）、重算（sync）与删除。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from app.domain.models.company import Company
from app.domain.models.job_company_link import JobCompanyLink
from app.domain.services.job_persist_service import upsert_job_profile
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select, text
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


async def _seed_same_title() -> dict[str, object]:
    """同一岗位名被两家公司招（B2-5 场景）：返回**那一条岗位** id + 两家公司 id。

    **任务 2（2026-09-27）起是多对多**：岗位是**角色级**的 → 这里落 **1 条岗位**
    + **2 条在招关联**（不再是 P2 时代"每家一条画像"）。

    用独立子前缀（`<prefix>-L`），避免污染其它用例对 `_company("")` 前缀的精确断言。
    """
    title = f"{_PREFIX}-L_同岗两家公司"
    name_a = f"{_PREFIX}-L_同岗甲"
    name_b = f"{_PREFIX}-L_同岗乙"
    async with test_session_factory() as session:
        profile_a, _ = await upsert_job_profile(
            session, {"title": title, "company": name_a, "industry": "互联网"}
        )
        profile_b, _ = await upsert_job_profile(
            session,
            {
                "title": title,
                "company": name_b,
                "region": "广东",
                "city": "深圳",
                "salary": "25-40K",
            },
        )
        await session.commit()

        company_ids = {}
        for name in (name_a, name_b):
            company_ids[name] = (
                await session.execute(select(Company.id).where(Company.name == name))
            ).scalar_one()
        # 多对多：第二次是**同一条**岗位（只是多一家在招）
        # 注：本模块的清理是 module 级的 → 同一次 pytest 里本函数可能被多次调用，
        #     所以只看"是不是同一条"，不断言 created（第二次起必然是 update）。
        assert profile_a.id == profile_b.id
        return {
            "job_id": int(profile_a.id),
            "company_a": company_ids[name_a],
            "company_b": company_ids[name_b],
            "name_a": name_a,
            "name_b": name_b,
        }


class TestJobCompanyLinksAPI:
    """B2-5 的两个查询方向（管理端接口）。任务 2 起底层是多对多：1 条岗位 ↔ N 家公司。"""

    def test_jobs_filter_finds_the_shared_profile(self, client, admin_token):
        """按公司筛选走关联表：**两家公司筛出来的是同一条岗位**（角色级）。"""
        seeded = asyncio.run(_seed_same_title())

        for key in ("company_a", "company_b"):
            resp = client.get(
                "/api/v1/admin/jobs",
                params={"company_id": seeded[key]},
                headers=_headers(admin_token),
            )
            assert resp.status_code == 200, resp.text
            items = resp.json()["items"]
            assert [i["id"] for i in items] == [seeded["job_id"]], key
            # 岗位行不挂公司（角色级）："在招公司"看 company_name / company_count；
            # 任务 3 起 `company_id` 连字段都没有了（列已删）
            assert "company_id" not in items[0], key
            assert items[0]["company_count"] == 2, key

    def test_job_list_exposes_company_count(self, client, admin_token):
        """`company_count` = 这个岗位**有多少家公司在招**（直接数关联表）。"""
        seeded = asyncio.run(_seed_same_title())
        resp = client.get(
            "/api/v1/admin/jobs",
            params={"company_id": seeded["company_a"]},
            headers=_headers(admin_token),
        )
        item = next(i for i in resp.json()["items"] if i["id"] == seeded["job_id"])
        assert item["company_count"] == 2
        assert item["company_name"] == seeded["name_a"]  # 展示名 = 最早建立关联的那家

    def test_job_detail_lists_all_hiring_companies(self, client, admin_token):
        seeded = asyncio.run(_seed_same_title())
        resp = client.get(
            f"/api/v1/admin/jobs/{seeded['job_id']}", headers=_headers(admin_token)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["company_count"] == 2
        names = {c["company_name"] for c in data["companies"]}
        assert names == {seeded["name_a"], seeded["name_b"]}
        # 多对多下没有"主公司"概念：`is_primary` = **最早建立关联**的那一条
        primaries = [c for c in data["companies"] if c["is_primary"]]
        assert len(primaries) == 1
        assert primaries[0]["company_id"] == seeded["company_a"]
        # 岗位详情同样不再有 `company_id` 字段（任务 3 删列）
        assert "company_id" not in data
        # 每条关联自带**这次招聘**的所在地/薪资
        b = next(c for c in data["companies"] if c["company_id"] == seeded["company_b"])
        assert (b["region"], b["city"], b["salary"]) == ("广东", "深圳", "25-40K")

    def test_company_detail_shows_linked_jobs(self, client, admin_token):
        seeded = asyncio.run(_seed_same_title())
        resp = client.get(
            f"/api/v1/admin/companies/{seeded['company_b']}", headers=_headers(admin_token)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["job_count"] == 1
        # 两家公司名下都是**同一条**岗位（角色级）
        assert [j["id"] for j in data["jobs"]] == [seeded["job_id"]]

    def test_sync_backfills_links_and_reports_count(self, client, admin_token):
        resp = client.post("/api/v1/admin/companies/sync", headers=_headers(admin_token))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data["links_created"], int)
        assert data["synced"] >= 1

    def test_company_job_counts_reflect_links_after_sync(self, client, admin_token):
        seeded = asyncio.run(_seed_same_title())
        client.post("/api/v1/admin/companies/sync", headers=_headers(admin_token))
        for key in ("company_a", "company_b"):
            detail = client.get(
                f"/api/v1/admin/companies/{seeded[key]}", headers=_headers(admin_token)
            ).json()
            assert detail["job_count"] == 1


class TestCompanyAuth:
    def test_list_forbidden_for_student(self, client: TestClient, student_token: str):
        resp = client.get("/api/v1/admin/companies", headers=_headers(student_token))
        assert resp.status_code == 403


class TestCompanyList:
    def test_list_orders_by_job_count(self, client: TestClient, admin_token: str, seeded):
        # ⚠️ **不能对全库列表断言**：dev 库里装着真实导入的公司（87 家），它们按
        #    job_count 降序排在本用例两家前面，会把「乙公司」（job_count=1）挤出默认分页
        #    （`limit=20`）→ 旧写法「全库恰好只剩我这两家」必红。所以用 `q` 把候选收敛到
        #    本用例的唯一前缀，只在前缀内断言顺序。
        resp = client.get(
            "/api/v1/admin/companies",
            params={"q": _PREFIX, "limit": 100},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        mine = [i for i in items if i["name"].startswith(_company(""))]
        assert [i["name"] for i in mine] == [_company("甲"), _company("乙")]  # 2 个岗位在前
        assert [i["job_count"] for i in mine] == [2, 1]
        # 降序是**整个返回列表**的性质（不只我这几家）：前缀内 job_count 必须单调不增
        counts = [i["job_count"] for i in items]
        assert counts == sorted(counts, reverse=True), counts

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
        """删除公司不得删岗位：关联行随公司 CASCADE 消失，**岗位本身留着**。

        任务 2 起岗位是角色级的（`job_profiles.company_id` 已由任务 3 删除），所以"解绑"
        就是"关联行没了、岗位还在" —— 这也正是 P2 时代那个"删第二家公司撞唯一索引 → 500"
        隐患消失的原因。
        """
        title = f"{_PREFIX}_待解绑岗位"
        company_name = _company("待删公司")

        async def _seed_one() -> tuple[int, int]:
            async with test_session_factory() as session:
                profile, _ = await upsert_job_profile(
                    session, {"title": title, "company": company_name}
                )
                await session.commit()
                link = (
                    await session.execute(
                        select(JobCompanyLink).where(
                            JobCompanyLink.job_profile_id == profile.id
                        )
                    )
                ).scalar_one()
                return int(profile.id), int(link.company_id)

        profile_id, company_id = asyncio.run(_seed_one())

        resp = client.delete(
            f"/api/v1/admin/companies/{company_id}", headers=_headers(admin_token)
        )
        assert resp.status_code == 204

        async def _state() -> tuple[bool, int]:
            async with test_session_factory() as session:
                exists = (
                    await session.execute(
                        text("SELECT count(*) FROM companies WHERE id = :i"), {"i": company_id}
                    )
                ).scalar_one()
                links = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM job_company_links WHERE job_profile_id = :i"
                        ),
                        {"i": profile_id},
                    )
                ).scalar_one()
                return bool(exists), int(links)

        company_exists, link_count = asyncio.run(_state())
        assert company_exists is False  # 公司没了
        assert link_count == 0  # 关联行随公司 CASCADE 消失

        # 岗位还在，且"在招公司"变空
        detail = client.get(
            f"/api/v1/admin/jobs/{profile_id}", headers=_headers(admin_token)
        )
        assert detail.status_code == 200
        assert detail.json()["company_count"] == 0
        assert detail.json()["companies"] == []


class TestJobDeleteRefreshesCompanyCount:
    def test_delete_job_drops_company_job_count(self, client: TestClient, admin_token: str):
        """回归：删岗位要把 `companies.job_count` 追平。

        `job_company_links` 是 CASCADE 外键，关联行会随岗位一起消失，但
        `companies.job_count` 是**冗余列**，不重算就虚高 —— 公司页正按它排序、
        `only_with_jobs` 也按它过滤，虚高会让"没有在招岗位的公司"继续显示。
        """
        title = f"{_PREFIX}_删后计数岗位"
        company_name = _company("删后计数公司")

        async def _seed_one() -> tuple[int, int, int]:
            async with test_session_factory() as session:
                profile, _ = await upsert_job_profile(
                    session, {"title": title, "company": company_name}
                )
                await session.commit()
                link = (
                    await session.execute(
                        select(JobCompanyLink).where(
                            JobCompanyLink.job_profile_id == profile.id
                        )
                    )
                ).scalar_one()
                company_id = int(link.company_id)
                count = (
                    await session.execute(
                        text("SELECT job_count FROM companies WHERE id = :i"), {"i": company_id}
                    )
                ).scalar_one()
                return int(profile.id), company_id, int(count)

        profile_id, company_id, count_before = asyncio.run(_seed_one())
        assert count_before == 1, f"前置条件不成立：job_count={count_before}"

        resp = client.delete(f"/api/v1/admin/jobs/{profile_id}", headers=_headers(admin_token))
        assert resp.status_code == 204, resp.text

        async def _count() -> int:
            async with test_session_factory() as session:
                return int(
                    (
                        await session.execute(
                            text("SELECT job_count FROM companies WHERE id = :i"),
                            {"i": company_id},
                        )
                    ).scalar_one()
                )

        assert asyncio.run(_count()) == 0


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
        # 岗位是角色级的 → 行上连 `company_id` 字段都没有；展示名来自关联表里最早的那家
        assert all("company_id" not in item for item in data["items"])
        assert all(item["company_name"] == _company("甲") for item in data["items"])
        assert all(item["company_count"] == 1 for item in data["items"])

    def test_jobs_without_company_filter_still_works(self, client: TestClient, admin_token: str):
        resp = client.get("/api/v1/admin/jobs", params={"limit": 1}, headers=_headers(admin_token))
        assert resp.status_code == 200
        assert "items" in resp.json()


# ── 任务 4（2026-09-27）：公司规模/省市 + 省→市级联（公司所在地口径）──────────────

_GEO_SCOPE = ("青海", "西藏")  # 与其它用例的地域不重叠，便于精确断言


async def _seed_geo_companies() -> dict[str, int]:
    """四家带规模/省市的公司（用别处不用的地名，断言才敢写死）。

    - `青海甲`：规模 + 省 + 市齐全；
    - `西藏乙`：规模 + 省 + 市齐全；
    - `无省丙`：**有市无省**，且这个市名**只存在于库里**（不在行政区划参考数据中）——
      它必须仍能通过 `all_cities` 被筛到；参考数据里没有它，所以它不会挂到任何省下面。
      （任务 4 续：下拉选项 = 官方参考数据 ∪ 库里的值，所以"只在库里的写法"要单独测。）
    - `待改丁`：规模/省/市**全空**，专供 PUT 用例 —— 不拿上面几家做修改，
      否则会污染 `test_geo_options_cascade_shape` 对级联数据的断言（测试之间不能互相踩）。
    """
    async with test_session_factory() as session:
        for name, scale, region, city in (
            ("青海甲", "1000-9999人", "青海", "西宁"),
            ("西藏乙", "100-499人", "西藏", "拉萨"),
            ("无省丙", "20-99人", None, "测试无省城"),
            ("待改丁", None, None, None),
        ):
            await upsert_job_profile(
                session,
                {
                    "title": _title(f"geo{name}"),
                    "company": _company(f"geo{name}"),
                    "region": region,
                    "city": city,
                    "scale": scale,
                },
            )
        await session.commit()

        rows = (
            await session.execute(
                text("SELECT id, name FROM companies WHERE name LIKE :p"),
                {"p": f"{_PREFIX}_geo%"},
            )
        ).all()
        return {row[1]: row[0] for row in rows}


@pytest.fixture(scope="module")
def geo_companies() -> dict[str, int]:
    return asyncio.run(_seed_geo_companies())


class TestCompanyScaleRegionAPI:
    """任务 4：`CompanyResponse/CompanyUpdate` 的 `scale`/`region` + 地域筛选。"""

    def test_list_exposes_scale_and_region(self, client: TestClient, admin_token: str, geo_companies):
        resp = client.get(
            "/api/v1/admin/companies",
            params={"region": "青海", "limit": 100},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        ours = [c for c in items if c["name"] == _company("geo青海甲")]
        assert len(ours) == 1, f"按省筛选没命中目标公司：{[c['name'] for c in items]}"
        assert ours[0]["scale"] == "1000-9999人"
        assert ours[0]["region"] == "青海"
        assert ours[0]["city"] == "西宁"

    def test_region_and_city_filters_compose(self, client: TestClient, admin_token: str, geo_companies):
        """省 → 市级联：选中省后加市继续收窄；省市不匹配就是空。"""
        hit = client.get(
            "/api/v1/admin/companies",
            params={"region": "青海", "city": "西宁", "limit": 100},
            headers=_headers(admin_token),
        )
        assert hit.status_code == 200
        names = [c["name"] for c in hit.json()["items"]]
        assert _company("geo青海甲") in names

        miss = client.get(
            "/api/v1/admin/companies",
            params={"region": "青海", "city": "拉萨", "limit": 100},
            headers=_headers(admin_token),
        )
        assert miss.json()["total"] == 0

    def test_update_sets_scale_and_region(self, client: TestClient, admin_token: str, geo_companies):
        """人工修正能写规模/省/市，且**省/市按短名归一**（导入识别的值可能不准）。

        用 `待改丁`（规模/省/市全空，且**只有它**允许被本类修改）—— 不碰别的公司，
        避免污染级联数据源的断言。
        下发的是官方全名「广东省/东莞市」→ 库里应落**短名**「广东/东莞」，
        否则它跟级联下拉给的「广东」对不上，这行就永远筛不到。
        """
        company_id = geo_companies[_company("geo待改丁")]
        resp = client.put(
            f"/api/v1/admin/companies/{company_id}",
            json={"scale": "500-999人", "region": "广东省", "city": "东莞市"},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert (data["scale"], data["region"], data["city"]) == ("500-999人", "广东", "东莞")

        # 落库为真（再查一次详情，不靠 PUT 的响应回显）
        detail = client.get(
            f"/api/v1/admin/companies/{company_id}", headers=_headers(admin_token)
        ).json()
        assert (detail["scale"], detail["region"], detail["city"]) == ("500-999人", "广东", "东莞")

    def test_import_write_path_normalises_full_names_to_short(
        self, client: TestClient, admin_token: str
    ):
        """导入写「广东省/深圳市」→ 库里存**短名**，且用短名**筛得到**。

        这条是"写法必须同源"的端到端证明：只做下拉不做归一化，或只做归一化不做下拉，
        都会在这里红。
        """
        title = _title("geo归一化岗")
        company_name = _company("geo归一化公司")

        async def _seed() -> int:
            async with test_session_factory() as session:
                await upsert_job_profile(
                    session,
                    {
                        "title": title,
                        "company": company_name,
                        "region": "广东省",
                        "city": "深圳市",
                    },
                )
                await session.commit()
                return int(
                    (
                        await session.execute(
                            select(Company.id).where(Company.name == company_name)
                        )
                    ).scalar_one()
                )

        async def _stored(company_id: int) -> tuple[str | None, str | None]:
            async with test_session_factory() as session:
                row = (
                    await session.execute(
                        text("SELECT region, city FROM companies WHERE id = :i"),
                        {"i": company_id},
                    )
                ).one()
                return (row[0], row[1])

        company_id = asyncio.run(_seed())
        assert asyncio.run(_stored(company_id)) == ("广东", "深圳")

        # 用短名筛选命中（这才是归一化的目的）
        hit = client.get(
            "/api/v1/admin/companies",
            params={"region": "广东", "city": "深圳", "limit": 100},
            headers=_headers(admin_token),
        ).json()
        assert company_id in [c["id"] for c in hit["items"]]

    def test_geo_options_cascade_shape(self, client: TestClient, admin_token: str, geo_companies):
        """级联数据源 = **官方参考数据 ∪ 库里的值**（任务 4 续）。

        - 参考数据保证**空库也有标准省市可选**（用户要求参考民政部写法）；
        - 合并库里的值保证导入的非标准写法**不丢**（否则"筛得到却选不到"）。
        """
        resp = client.get("/api/v1/admin/companies/geo-options", headers=_headers(admin_token))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data) == {"regions", "cities_by_region", "all_cities"}

        # ① 官方参考数据在位（与库里有没有数据无关）：34 个省级 + 含港澳台
        assert len(data["regions"]) >= 34
        assert {"广东", "内蒙古", "台湾", "香港", "澳门"} <= set(data["regions"])
        assert "深圳" in data["cities_by_region"]["广东"]
        # 直辖市：第二级 = 它自己（不列"区"）
        assert data["cities_by_region"]["北京"] == ["北京"]

        # ② 库里的值在位（含"只在库里"的写法）
        assert set(_GEO_SCOPE) <= set(data["regions"])
        assert "西宁" in data["cities_by_region"]["青海"]
        assert "测试无省城" in data["all_cities"]
        # 它只可能在 all_cities 里（参考数据没有它，库里那行又没写省）
        assert "测试无省城" not in [
            c for cities in data["cities_by_region"].values() for c in cities
        ]

    def test_geo_options_not_shadowed_by_company_id_route(self, client: TestClient, admin_token: str):
        """`/companies/geo-options` 必须命中自己的路由，而不是被 `/{company_id}` 吃掉（422）。"""
        resp = client.get("/api/v1/admin/companies/geo-options", headers=_headers(admin_token))
        assert resp.status_code == 200, f"路由被 /{{company_id}} 抢走了：{resp.status_code} {resp.text}"

    def test_no_create_company_endpoint(self, client: TestClient, admin_token: str):
        """**刻意没有"新建公司"**：公司是导入的副产品，管理端只修正/删除。

        钉住这个设计决定 —— 哪天有人顺手加了 POST，这条会红，提醒他先想清楚
        "手工建的公司" 与 "导入 upsert 的同名公司" 如何不打架。
        """
        resp = client.post(
            "/api/v1/admin/companies",
            json={"name": _company("手工新建")},
            headers=_headers(admin_token),
        )
        assert resp.status_code == 405, resp.text
