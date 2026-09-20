from collections import defaultdict

import pytest
from app.main import app
from fastapi.testclient import TestClient

REPORT_FIELDS = {
    "id",
    "user_id",
    "profile_snapshot_id",
    "serial_no",
    "description",
    "version",
    "created_at",
}

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestReportsAPI:
    """S5: 报告管理改为基于 report_records（原 CareerReport 表已删除）。"""

    def test_list_reports_shape(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/reports?limit=100",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "total" in data
        assert "items" in data
        for item in data["items"]:
            assert set(item) == REPORT_FIELDS
            assert item["version"] >= 1
            assert item["profile_snapshot_id"] > 0

    def test_list_reports_version_is_per_user_sequence(self, admin_token: str, client: TestClient):
        """version 必须是「该用户内 1..n 的连续序号」—— 防写死 0 / 算错 / N+1 漏算。"""
        resp = client.get(
            "/api/v1/admin/reports?limit=100",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["total"] > 100:
            pytest.skip("记录数超过单页上限，跳过完整性校验")

        by_user: dict[int, list[int]] = defaultdict(list)
        for item in data["items"]:
            by_user[item["user_id"]].append(item["version"])
        for uid, versions in by_user.items():
            assert sorted(versions) == list(range(1, len(versions) + 1)), (
                f"user {uid} 的 version 不是 1..n：{sorted(versions)}"
            )

    def test_filter_reports_by_user(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/reports?user_id=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["user_id"] == 1 for item in data["items"])

    def test_get_report_not_found(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/reports/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_download_report_not_found(self, admin_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/reports/999999/download",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_delete_report_not_found(self, admin_token: str, client: TestClient):
        resp = client.delete(
            "/api/v1/admin/reports/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_download_real_report_returns_docx(self, admin_token: str, client: TestClient):
        """端到端：取一条真实记录下载，必须拿到 docx（惰性生成）。"""
        listing = client.get(
            "/api/v1/admin/reports?limit=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert listing.status_code == 200
        items = listing.json()["items"]
        if not items:
            pytest.skip("库里暂无报告记录，跳过下载用例")

        rid = items[0]["id"]
        resp = client.get(
            f"/api/v1/admin/reports/{rid}/download",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith(DOCX_MEDIA_TYPE)
        assert len(resp.content) > 1000  # 真实的 docx 不会只有几十字节

    def test_detail_contains_report_text(self, admin_token: str, client: TestClient):
        listing = client.get(
            "/api/v1/admin/reports?limit=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        items = listing.json()["items"]
        if not items:
            pytest.skip("库里暂无报告记录，跳过详情用例")

        rid = items[0]["id"]
        resp = client.get(
            f"/api/v1/admin/reports/{rid}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == REPORT_FIELDS | {"report_text", "word_file_path"}
        assert data["report_text"]


class TestReportsAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        resp = client.get(
            "/api/v1/admin/reports",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403
