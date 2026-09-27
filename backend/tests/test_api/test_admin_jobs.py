import asyncio
import time

import pytest
from app.domain.models.vector import JobMatchEmbedding
from app.domain.services.job_persist_service import upsert_job_profile
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from tests.conftest import test_session_factory

_ts = str(int(time.time()))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestJobsAPI:
    def test_list_jobs(self, admin_token: str, client: TestClient):
        """Test listing job profiles."""
        resp = client.get(
            "/api/v1/admin/jobs",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_create_job(self, admin_token: str, client: TestClient):
        """Test creating a job profile."""
        resp = client.post(
            "/api/v1/admin/jobs",
            json={
                "title": f"测试岗位_{_ts}",
                "industry": "互联网",
                "level": "中级",
                "salary_range": "15000-25000",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == f"测试岗位_{_ts}"
        self.created_job_id = data["id"]

    def test_get_job(self, admin_token: str, client: TestClient):
        """Test getting a single job profile."""
        # First create a job
        resp = client.post(
            "/api/v1/admin/jobs",
            json={
                "title": f"测试岗位详情_{_ts}",
                "industry": "互联网",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        job_id = resp.json()["id"]

        # Get the job
        resp = client.get(
            f"/api/v1/admin/jobs/{job_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job_id

    def test_update_job(self, admin_token: str, client: TestClient):
        """Test updating a job profile."""
        # First create a job
        resp = client.post(
            "/api/v1/admin/jobs",
            json={
                "title": f"测试岗位更新_{_ts}",
                "industry": "互联网",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        job_id = resp.json()["id"]

        # Update the job
        resp = client.put(
            f"/api/v1/admin/jobs/{job_id}",
            json={"title": f"更新后岗位_{_ts}", "level": "高级"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == f"更新后岗位_{_ts}"
        assert data["level"] == "高级"

    def test_delete_job(self, admin_token: str, client: TestClient):
        """Test deleting a job profile."""
        # First create a job
        resp = client.post(
            "/api/v1/admin/jobs",
            json={
                "title": f"测试岗位删除_{_ts}",
                "industry": "互联网",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        job_id = resp.json()["id"]

        # Delete the job
        resp = client.delete(
            f"/api/v1/admin/jobs/{job_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

        # Verify it's deleted
        resp = client.get(
            f"/api/v1/admin/jobs/{job_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_delete_job_with_embedding(self, admin_token: str, client: TestClient):
        """回归：岗位**有 embedding 行**时删除也必须 204（曾经 500）。

        `job_match_embeddings.job_profile_id` 是 **NO ACTION** 外键（另两张子表是
        CASCADE，只有它漏了），而 `create_job` 会调 `embed_job()` 写一行。
        而 `embed_job` 把**所有异常都吞成一条 warning**，所以测试进程里 embedding
        调用成不成是**碰运气的** —— 老用例 `test_delete_job` 恰好没赶上向量行时才
        204 绿，是**不确定性的假绿**；embedding 正常时（线上/真栈）「新建岗位 →
        点删除」必 `ForeignKeyViolationError` → 500。这条用例**显式塞行**，不再看运气。
        """
        headers = {"Authorization": f"Bearer {admin_token}"}
        created = client.post(
            "/api/v1/admin/jobs",
            json={"title": f"测试岗位_删除带向量_{_ts}"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["id"]

        async def _seed_embedding() -> None:
            async with test_session_factory() as session:
                session.add(
                    JobMatchEmbedding(
                        job_profile_id=job_id,
                        content="回归占位文本",
                        embedding=[0.0] * 1024,
                    )
                )
                await session.commit()

        asyncio.run(_seed_embedding())

        resp = client.delete(f"/api/v1/admin/jobs/{job_id}", headers=headers)
        assert resp.status_code == 204, resp.text

        async def _embedding_count() -> int:
            async with test_session_factory() as session:
                return (
                    await session.execute(
                        select(func.count())
                        .select_from(JobMatchEmbedding)
                        .where(JobMatchEmbedding.job_profile_id == job_id)
                    )
                ).scalar_one()

        # 子行必须一并删掉，不能留孤儿向量（否则重建同 id 会撞回同一条）
        assert asyncio.run(_embedding_count()) == 0

    def test_filter_jobs(self, admin_token: str, client: TestClient):
        """Test filtering job profiles."""
        # 创建不同行业的岗位
        client.post(
            "/api/v1/admin/jobs",
            json={"title": f"互联网岗位_{_ts}", "industry": "互联网"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # P2 回归：这里以前用**字面量** `金融岗位`（没有时间戳）→ 每次跑测试都插一条，
        # 历史上一共堆了 63 条（数据卫生清理时才发现）。加了 `(岗位名, 公司)` 唯一索引后
        # 第二次插入直接 UniqueViolation → 500。测试数据必须自带唯一后缀。
        client.post(
            "/api/v1/admin/jobs",
            json={"title": f"金融岗位_{_ts}", "industry": "金融"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Filter by industry
        resp = client.get(
            "/api/v1/admin/jobs?industry=互联网",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["industry"] == "互联网" for item in data["items"])

    def test_create_duplicate_title_returns_409(self, admin_token: str, client: TestClient):
        """P2：`(岗位名, 公司)` 唯一 —— 管理端重复新建应得 **409**，不能是 500。

        归一化后同名也算重复（忽略大小写 + 折叠空白）。
        """
        title = f"测试岗位_冲突_{_ts}"
        headers = {"Authorization": f"Bearer {admin_token}"}

        first = client.post("/api/v1/admin/jobs", json={"title": title}, headers=headers)
        assert first.status_code == 201, first.text

        second = client.post(
            "/api/v1/admin/jobs", json={"title": f"  {title.upper()}  "}, headers=headers
        )
        assert second.status_code == 409, second.text
        assert "已存在" in second.json()["detail"]

    def test_update_title_to_duplicate_returns_409(self, admin_token: str, client: TestClient):
        """P2：改名撞上另一条同键岗位 → 409（编辑弹窗要看得懂）。"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        kept = client.post(
            "/api/v1/admin/jobs", json={"title": f"测试岗位_占用_{_ts}"}, headers=headers
        ).json()
        other = client.post(
            "/api/v1/admin/jobs", json={"title": f"测试岗位_待改_{_ts}"}, headers=headers
        ).json()

        resp = client.put(
            f"/api/v1/admin/jobs/{other['id']}",
            json={"title": kept["title"]},
            headers=headers,
        )
        assert resp.status_code == 409, resp.text

        # 改成自己的原名不受影响
        ok = client.put(
            f"/api/v1/admin/jobs/{other['id']}",
            json={"title": other["title"], "level": "高级"},
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["level"] == "高级"


# ── 任务 4（2026-09-27）：岗位的地域筛选（**招聘所在地**口径，缺失回落公司）────────

_GEO_PREFIX = f"t4geo_{_ts}"


def _geo(name: str) -> str:
    return f"{_GEO_PREFIX}_{name}"


async def _geo_cleanup() -> None:
    async with test_session_factory() as session:
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_GEO_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM job_raw_data WHERE title LIKE :p"), {"p": f"{_GEO_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"{_GEO_PREFIX}%"}
        )
        await session.commit()


@pytest.fixture(scope="module", autouse=True)
def clean_t4geo_rows():
    asyncio.run(_geo_cleanup())
    yield
    asyncio.run(_geo_cleanup())


async def _seed_geo_jobs() -> dict[str, int]:
    """三个岗位，覆盖地域筛选的三种数据形态（用别处不用的地名，断言才敢写死）。

    - `链接地域岗`：**关联行自带**招聘所在地（青海/西宁）→ 走 link 口径；
    - `回落地域岗`：关联行**没有**地域、公司写了（西藏/拉萨）→ 走"回落公司"口径
      （下面手动把 link 的地域清成 NULL 来模拟这种老数据）；
    - `多公司地域岗`：**一条岗位、两家公司分别在两个省招**（宁夏/银川 + 新疆/乌鲁木齐）
      → 两个省都该能筛出**同一条**岗位（多对多：地域算各的）。
    """
    async with test_session_factory() as session:
        job_link, _ = await upsert_job_profile(
            session,
            {
                "title": _geo("链接地域岗"),
                "company": _geo("链接公司甲"),
                "region": "青海",
                "city": "西宁",
                "salary": "10-15K",
            },
        )
        job_fallback, _ = await upsert_job_profile(
            session,
            {
                "title": _geo("回落地域岗"),
                "company": _geo("回落公司乙"),
                "region": "西藏",
                "city": "拉萨",
            },
        )
        job_multi, _ = await upsert_job_profile(
            session,
            {
                "title": _geo("多公司地域岗"),
                "company": _geo("多公司甲"),
                "region": "宁夏",
                "city": "银川",
            },
        )
        await upsert_job_profile(
            session,
            {
                "title": _geo("多公司地域岗"),
                "company": _geo("多公司乙"),
                "region": "新疆",
                "city": "乌鲁木齐",
            },
        )
        await session.commit()

    # 制造"link 没写地域、公司写了"的老数据形态（入库路径两边都会写，所以要手工清一次）
    async with test_session_factory() as session:
        await session.execute(
            text(
                "UPDATE job_company_links SET region = NULL, city = NULL "
                "WHERE job_profile_id = :i"
            ),
            {"i": job_fallback.id},
        )
        await session.commit()

    return {
        "link_job": int(job_link.id),
        "fallback_job": int(job_fallback.id),
        "multi_job": int(job_multi.id),
    }


@pytest.fixture(scope="module")
def geo_jobs() -> dict[str, int]:
    return asyncio.run(_seed_geo_jobs())


class TestJobGeoFilterAPI:
    """任务 4：岗位列表按**招聘所在地**筛，口径与详情「在招公司」逐字一致。"""

    def test_region_filter_matches_link_level(self, client: TestClient, admin_token: str, geo_jobs):
        resp = client.get(
            "/api/v1/admin/jobs",
            params={"region": "青海", "limit": 100},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == geo_jobs["link_job"]

    def test_region_and_city_filters_compose(self, client: TestClient, admin_token: str, geo_jobs):
        headers = {"Authorization": f"Bearer {admin_token}"}
        hit = client.get(
            "/api/v1/admin/jobs", params={"region": "青海", "city": "西宁"}, headers=headers
        ).json()
        assert [i["id"] for i in hit["items"]] == [geo_jobs["link_job"]]

        miss = client.get(
            "/api/v1/admin/jobs", params={"region": "青海", "city": "拉萨"}, headers=headers
        ).json()
        assert miss["total"] == 0

    def test_region_filter_falls_back_to_company(self, client: TestClient, admin_token: str, geo_jobs):
        """关联行没写地域时回落到**公司所在地** —— 否则这批老数据永远筛不到。"""
        resp = client.get(
            "/api/v1/admin/jobs",
            params={"region": "西藏", "limit": 100},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == geo_jobs["fallback_job"]

    def test_multi_company_job_matches_both_regions(self, client: TestClient, admin_token: str, geo_jobs):
        """一条岗位被两家不同省的公司招 → **两个省都筛得到同一条**（多对多的要点）。"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        for region, city in (("宁夏", "银川"), ("新疆", "乌鲁木齐")):
            data = client.get(
                "/api/v1/admin/jobs", params={"region": region, "city": city}, headers=headers
            ).json()
            assert data["total"] == 1, f"{region} 没筛到"
            assert data["items"][0]["id"] == geo_jobs["multi_job"]

    def test_geo_options_include_link_and_fallback_regions(
        self, client: TestClient, admin_token: str, geo_jobs
    ):
        """级联数据源必须和筛选口径**同源** —— 否则会出现"筛得到却看不到"。"""
        resp = client.get(
            "/api/v1/admin/jobs/geo-options",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, f"路由被 /{{job_id}} 抢走了：{resp.status_code} {resp.text}"
        data = resp.json()
        assert set(data) == {"regions", "cities_by_region", "all_cities"}

        # ① 官方行政区划参考数据也在（任务 4 续：空库也要有标准省市可选）
        assert len(data["regions"]) >= 34
        assert {"广东", "内蒙古", "台湾", "香港", "澳门"} <= set(data["regions"])
        assert "深圳" in data["cities_by_region"]["广东"]
        assert data["cities_by_region"]["北京"] == ["北京"]  # 直辖市第二级=自己

        # ② link 口径
        assert "青海" in data["regions"]
        assert "西宁" in data["cities_by_region"]["青海"]
        # 回落口径（公司所在地也得进级联，才与上面的筛选一致）
        assert "西藏" in data["regions"]
        assert "拉萨" in data["cities_by_region"]["西藏"]
        # 多对多：两个省都在
        assert {"宁夏", "新疆"} <= set(data["regions"])
