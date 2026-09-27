import asyncio
import time

import pytest
from app.domain.models.vector import JobMatchEmbedding
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import func, select
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
