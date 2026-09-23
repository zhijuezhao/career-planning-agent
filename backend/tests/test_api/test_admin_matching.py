import asyncio
import time

import pytest
from app.config import get_settings
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

_settings = get_settings()
_test_engine = create_async_engine(_settings.database_url, poolclass=NullPool)
_probe_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)

_ts = str(int(time.time()))

SNAPSHOT_FIELDS = {
    "id",
    "user_id",
    "username",  # P1-4：LEFT JOIN users
    "profile_id",
    "serial_no",
    "description",
    "matched",
    "matched_at",
    "created_at",
    "six_dim_scores",
    "report_count",  # P1-4：关联报告数（删除前提示用）
}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


async def _get_user_id(username: str) -> int:
    from app.domain.models.user import User

    async with AsyncSession(_test_engine) as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one().id


def _create_user(client: TestClient, username: str) -> int:
    client.post("/api/v1/auth/register", json={
        "username": username,
        "password": "test123456",
    })
    return asyncio.run(_get_user_id(username))


class TestSnapshotsAPI:
    """S6/D9: /matching/results 与 /feedbacks 已被 /matching/snapshots 取代。"""

    def test_list_snapshots(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/matching/snapshots?limit=100",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "total" in data
        assert "items" in data
        for item in data["items"]:
            assert set(item) == SNAPSHOT_FIELDS
            assert isinstance(item["six_dim_scores"], dict)

    def test_filter_by_user(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/matching/snapshots?user_id=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert all(i["user_id"] == 1 for i in resp.json()["items"])

    def test_filter_matched_consistent(self, admin_token: str, client: TestClient):
        """matched 过滤必须与 matched_at 一致（true -> 非空，false -> 空）。"""
        for flag, expect_matched in (("true", True), ("false", False)):
            resp = client.get(
                f"/api/v1/admin/matching/snapshots?matched={flag}&limit=100",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            for item in resp.json()["items"]:
                assert item["matched"] is expect_matched
                assert (item["matched_at"] is not None) is expect_matched

    def test_get_snapshot_not_found(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/matching/snapshots/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_get_snapshot_detail(self, admin_token: str, client: TestClient):
        listing = client.get(
            "/api/v1/admin/matching/snapshots?limit=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        items = listing.json()["items"]
        if not items:
            pytest.skip("库里暂无画像快照，跳过详情用例")

        resp = client.get(
            f"/api/v1/admin/matching/snapshots/{items[0]['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data) == SNAPSHOT_FIELDS | {"five_layers", "form_raw", "embedding_dim"}
        assert isinstance(data["five_layers"], dict)
        assert isinstance(data["form_raw"], dict)

    def test_legacy_endpoints_removed(self, admin_token: str, client: TestClient):
        """原 /results 与 /feedbacks 已删除 -> 404（不是 501）。"""
        for path in (
            "/api/v1/admin/matching/results",
            "/api/v1/admin/matching/results/1",
            "/api/v1/admin/matching/feedbacks",
            "/api/v1/admin/matching/feedbacks/1",
        ):
            resp = client.get(path, headers={"Authorization": f"Bearer {admin_token}"})
            assert resp.status_code == 404, f"{path} -> {resp.status_code}"


class TestDimensionWeightsAPI:
    def test_list_dimension_weights(self, admin_token: str, client: TestClient):
        """Test listing dimension weights."""
        resp = client.get(
            "/api/v1/admin/matching/weights",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_create_dimension_weight(self, admin_token: str, client: TestClient):
        """Test creating a dimension weight."""
        resp = client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": f"测试类别_{_ts}",
                "top_dimension": "技术能力",
                "weight": 0.3,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["job_category"] == f"测试类别_{_ts}"
        assert data["top_dimension"] == "技术能力"
        assert data["weight"] == 0.3

    def test_create_duplicate_weight_conflict(self, admin_token: str, client: TestClient):
        """Test creating a duplicate dimension weight returns 409."""
        category = f"重复类别_{_ts}"
        client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": category,
                "top_dimension": "沟通能力",
                "weight": 0.2,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": category,
                "top_dimension": "沟通能力",
                "weight": 0.4,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    def test_update_dimension_weight(self, admin_token: str, client: TestClient):
        """Test updating a dimension weight."""
        create_resp = client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": f"更新类别_{_ts}",
                "top_dimension": "领导力",
                "weight": 0.15,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        weight_id = create_resp.json()["id"]

        resp = client.put(
            f"/api/v1/admin/matching/weights/{weight_id}",
            json={"weight": 0.25},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["weight"] == 0.25

    def test_delete_dimension_weight(self, admin_token: str, client: TestClient):
        """Test deleting a dimension weight."""
        create_resp = client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": f"删除类别_{_ts}",
                "top_dimension": "团队协作",
                "weight": 0.1,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        weight_id = create_resp.json()["id"]

        resp = client.delete(
            f"/api/v1/admin/matching/weights/{weight_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

        resp = client.get(
            f"/api/v1/admin/matching/weights/{weight_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_filter_weights_by_category(self, admin_token: str, client: TestClient):
        """Test filtering dimension weights by category."""
        category = f"筛选类别_{_ts}"
        client.post(
            "/api/v1/admin/matching/weights",
            json={
                "job_category": category,
                "top_dimension": "创新能力",
                "weight": 0.2,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        resp = client.get(
            f"/api/v1/admin/matching/weights?job_category={category}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["job_category"] == category for item in data["items"])


class TestMatchingAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """非管理员访问快照列表 -> 403。"""
        resp = client.get(
            "/api/v1/admin/matching/snapshots",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403

    def test_non_admin_forbidden_weights(self, student_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/matching/weights",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403


class TestSnapshotAdminOps:
    """P1-4：下载 / 修改 / 删除。

    做法：**克隆**一条既有快照（复用其 user_id/profile_id，向量置零）作为测试对象，
    全程不碰真实快照数据；每个用例结束前删掉自己那条。
    """

    _CLONE_DESCRIPTION = "p1-4-clone"

    @staticmethod
    async def _clone() -> int | None:
        async with _probe_session_factory() as session:
            src = (await session.execute(select(ProfileSnapshot).limit(1))).scalars().first()
            if src is None:
                return None
            clone = ProfileSnapshot(
                user_id=src.user_id,
                profile_id=src.profile_id,
                form_raw_json={"__test__": True},
                five_layers_json={"基础信息": {"姓名": "P1-4 测试"}},
                six_dim_scores_json={"技能": 4.0},
                embedding=[0.0] * 1024,
                description=TestSnapshotAdminOps._CLONE_DESCRIPTION,
            )
            session.add(clone)
            await session.commit()
            await session.refresh(clone)
            return clone.id

    def _clone_id(self) -> int:
        snapshot_id = asyncio.run(self._clone())
        if snapshot_id is None:
            pytest.skip("库里没有任何快照，无法克隆测试对象")
        return snapshot_id

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _drop(self, client: TestClient, token: str, snapshot_id: int) -> None:
        client.delete(
            f"/api/v1/admin/matching/snapshots/{snapshot_id}",
            headers=self._headers(token),
        )

    def test_download_returns_markdown(self, admin_token: str, client: TestClient):
        snapshot_id = self._clone_id()
        try:
            resp = client.get(
                f"/api/v1/admin/matching/snapshots/{snapshot_id}/download",
                headers=self._headers(admin_token),
            )
            assert resp.status_code == 200, resp.text
            assert resp.headers["content-type"].startswith("text/markdown")
            disposition = resp.headers["content-disposition"]
            assert "attachment" in disposition
            assert "filename*=UTF-8''" in disposition  # RFC 5987 中文名
            assert resp.text.startswith("# 画像快照 ")
            assert "## 五层画像" in resp.text
            assert "P1-4 测试" in resp.text
        finally:
            self._drop(client, admin_token, snapshot_id)

    def test_update_description_and_five_layers(self, admin_token: str, client: TestClient):
        snapshot_id = self._clone_id()
        url = f"/api/v1/admin/matching/snapshots/{snapshot_id}"
        try:
            resp = client.put(
                url,
                json={
                    "description": "改过的备注",
                    "five_layers": {"基础信息": {"姓名": "李四"}},
                },
                headers=self._headers(admin_token),
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["description"] == "改过的备注"
            assert data["five_layers"]["基础信息"]["姓名"] == "李四"

            # 持久化确认（重新 GET）
            detail = client.get(url, headers=self._headers(admin_token)).json()
            assert detail["description"] == "改过的备注"
            assert detail["five_layers"]["基础信息"]["姓名"] == "李四"
        finally:
            self._drop(client, admin_token, snapshot_id)

    def test_update_rejects_unknown_fields(self, admin_token: str, client: TestClient):
        """extra=forbid：传 embedding 之类不在白名单的字段 -> 422（而不是静默忽略）。"""
        snapshot_id = self._clone_id()
        try:
            resp = client.put(
                f"/api/v1/admin/matching/snapshots/{snapshot_id}",
                json={"embedding": [0.1] * 4},
                headers=self._headers(admin_token),
            )
            assert resp.status_code == 422, resp.text
        finally:
            self._drop(client, admin_token, snapshot_id)

    def test_update_not_found(self, admin_token: str, client: TestClient):
        resp = client.put(
            "/api/v1/admin/matching/snapshots/999999",
            json={"description": "x"},
            headers=self._headers(admin_token),
        )
        assert resp.status_code == 404

    def test_delete_then_gone(self, admin_token: str, client: TestClient):
        snapshot_id = self._clone_id()
        url = f"/api/v1/admin/matching/snapshots/{snapshot_id}"

        resp = client.delete(url, headers=self._headers(admin_token))
        assert resp.status_code == 204

        assert client.get(url, headers=self._headers(admin_token)).status_code == 404

    def test_delete_not_found(self, admin_token: str, client: TestClient):
        resp = client.delete(
            "/api/v1/admin/matching/snapshots/999999",
            headers=self._headers(admin_token),
        )
        assert resp.status_code == 404

    def test_clone_has_username_and_report_count(self, admin_token: str, client: TestClient):
        """列表项必须带 username 与 report_count（P1-4 新字段）。"""
        resp = client.get(
            "/api/v1/admin/matching/snapshots?limit=5",
            headers=self._headers(admin_token),
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["username"] is None or isinstance(item["username"], str)
            assert isinstance(item["report_count"], int)
            assert item["report_count"] >= 0
