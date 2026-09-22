import asyncio
import io
from pathlib import Path

import pytest
from app.api.v1.admin import import_module
from app.config import get_settings
from app.domain.models.import_job import DataImportJob
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# S7-1：后台任务用独立 session 读库，测试侧统一用 NullPool 引擎直连，
# 避免 event-loop 之间复用池化连接（S1 同类问题）。
_probe_engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
_probe_session_factory = async_sessionmaker(_probe_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_real_background_scheduling(monkeypatch):
    """本模块一律不真正调度后台任务。

    `TestClient(app)` 未作为上下文管理器时每个请求一个临时事件循环，请求结束即关闭：
    端点里的 `create_task` 注定不会执行，还会变成「未取回异常」在后续用例里爆炸
    （实测：污染 portal，报 'NoneType' object has no attribute 'send'）。
    需要验证后台主体的用例改为直接 `asyncio.run(import_module._process_import(...))`。
    """
    monkeypatch.setattr(import_module, "_schedule_process", lambda _job_id: None)


async def _read_job(job_id: int) -> tuple[str, int, list] | None:
    async with _probe_session_factory() as session:
        row = await session.get(DataImportJob, job_id)
        if row is None:
            return None
        return row.status, row.total_rows, list(row.errors or [])


def _job_snapshot(job_id: int) -> tuple[str, int, list] | None:
    return asyncio.run(_read_job(job_id))


async def _count_table(table: str) -> int:
    async with _probe_session_factory() as session:
        return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


def _count_rows(table: str) -> int:
    return asyncio.run(_count_table(table))


def _upload(client: TestClient, token: str, filename: str, content: bytes):
    return client.post(
        "/api/v1/admin/import/upload",
        files={"file": (filename, io.BytesIO(content), "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )


def _process(client: TestClient, token: str, job_id: int):
    return client.post(
        f"/api/v1/admin/import/{job_id}/process",
        headers={"Authorization": f"Bearer {token}"},
    )


THREE_ROW_CSV = (
    "岗位名称,公司名称,工作城市\n"
    "数据分析师,A公司,北京\n"
    "后端工程师,B公司,上海\n"
    "产品经理,C公司,深圳\n"
).encode("utf-8")


class TestImportAPI:
    def test_list_import_jobs(self, admin_token: str, client: TestClient):
        """Test listing import jobs."""
        resp = client.get(
            "/api/v1/admin/import",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_upload_file(self, admin_token: str, client: TestClient):
        """Test uploading a file."""
        file_content = b"title,company,city\nTest Job,Test Company,Beijing\n"
        resp = client.post(
            "/api/v1/admin/import/upload",
            files={"file": ("test.csv", io.BytesIO(file_content), "text/csv")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["file_name"] == "test.csv"
        assert data["status"] == "pending"

    def test_upload_invalid_extension(self, admin_token: str, client: TestClient):
        """Test uploading a file with invalid extension."""
        resp = client.post(
            "/api/v1/admin/import/upload",
            files={"file": ("test.txt", io.BytesIO(b"content"), "text/plain")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    def test_get_import_job_not_found(self, admin_token: str, client: TestClient):
        """Test getting a non-existent import job."""
        resp = client.get(
            "/api/v1/admin/import/999999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_get_progress_not_found(self, admin_token: str, client: TestClient):
        """Test getting progress of non-existent job."""
        resp = client.get(
            "/api/v1/admin/import/999999/progress",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_process_and_check_progress(self, admin_token: str, client: TestClient):
        """Test processing an import job and checking progress."""
        file_content = b"title,company\nJob,Company\n"
        upload_resp = client.post(
            "/api/v1/admin/import/upload",
            files={"file": ("process_test.csv", io.BytesIO(file_content), "text/csv")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        job_id = upload_resp.json()["id"]

        process_resp = client.post(
            f"/api/v1/admin/import/{job_id}/process",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert process_resp.status_code == 200
        assert process_resp.json()["status"] == "processing"

        progress_resp = client.get(
            f"/api/v1/admin/import/{job_id}/progress",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert progress_resp.status_code == 200
        data = progress_resp.json()
        assert data["job_id"] == job_id
        assert "progress_pct" in data


class TestImportAPIAuth:
    def test_non_admin_forbidden(self, student_token: str, client: TestClient):
        """Test that non-admin users cannot access import endpoints."""
        resp = client.get(
            "/api/v1/admin/import",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 403


class TestImportS71FileLocation:
    """S7-1（D-S7-1=A）：文件名即索引 —— `<job_id>_<safe_name>`，处理阶段靠它定位。"""

    def test_uploaded_file_is_named_with_job_id(self, admin_token: str, client: TestClient):
        resp = _upload(client, admin_token, "s71_named.csv", THREE_ROW_CSV)
        assert resp.status_code == 201, resp.text
        job_id = resp.json()["id"]

        expected = import_module.UPLOAD_DIR / f"{job_id}_s71_named.csv"
        assert expected.exists(), f"未按 <job_id>_<safe_name> 落盘：{expected}"
        assert expected.read_bytes() == THREE_ROW_CSV

    def test_upload_filename_path_traversal_is_sanitized(self, admin_token: str, client: TestClient):
        resp = _upload(client, admin_token, "../../evil.csv", THREE_ROW_CSV)
        assert resp.status_code == 201, resp.text
        job_id = resp.json()["id"]

        # 落盘只保留 basename，且必须留在 UPLOAD_DIR 内
        assert (import_module.UPLOAD_DIR / f"{job_id}_evil.csv").exists()
        created = sorted(import_module.UPLOAD_DIR.glob("*evil*.csv"))
        assert created, "未找到落盘文件"
        for path in created:
            assert path.resolve().parent == import_module.UPLOAD_DIR.resolve()

    def test_find_upload_file_by_job_id(self, admin_token: str, client: TestClient):
        job_id = _upload(client, admin_token, "s71_find.csv", THREE_ROW_CSV).json()["id"]
        found = import_module._find_upload_file(job_id)
        assert found is not None
        assert found.name.startswith(f"{job_id}_")
        assert import_module._find_upload_file(job_id + 999999) is None


class TestImportS71StateMachine:
    """S7-1：状态机 —— 先 commit 再调度；真实行数；失败可见；不造假数据。

    注意：`TestClient(app)` 未作为上下文管理器时**每个请求一个临时事件循环**，
    请求结束循环即销毁 → 端点上 `create_task` 调度的任务在测试里不会真正跑。
    因此本类分两层断言：调度接缝（`_schedule_process`）验证「先落库」，
    runner 主体（`_process_import`）在测试自己的循环里直接执行验证状态机。
    """

    def test_process_commits_processing_before_scheduling(
        self, admin_token: str, client: TestClient, monkeypatch
    ):
        """反竞态：调度发生的那一刻，DB 里必须已经是 processing（原实现只 flush）。

        端点执行顺序是 commit → refresh → `_schedule_process` → return，
        调度是返回前最后一步；这里把它换成只记录 job_id 的探针（不在事件循环里
        调 asyncio.run，否则会污染 portal），请求返回后直接读库验证已落库。
        """
        captured: dict[str, object] = {}

        def fake_schedule(job_id: int) -> None:
            captured["job_id"] = job_id

        monkeypatch.setattr(import_module, "_schedule_process", fake_schedule)

        job_id = _upload(client, admin_token, "s71_commit.csv", THREE_ROW_CSV).json()["id"]
        resp = _process(client, admin_token, job_id)

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "processing"
        # 调度已发生（探针被调用），且此后无任何写入者 → 此刻库内即调度时的状态
        assert captured["job_id"] == job_id
        status, _total, _errors = _job_snapshot(job_id)
        assert status == "processing"

    def _start_job_without_scheduling(
        self, client: TestClient, token: str, job_id: int, monkeypatch
    ) -> None:
        """走完端点把状态置为 processing（调度由模块级 autouse 探针兜住），
        并把 import_module 用的 session 工厂换成 NullPool 探针。

        注意必须 patch `import_module.async_session_factory`：该模块在导入时就绑定了
        这个名字，改 `app.infrastructure.database` 上的同名属性不会生效，
        runner 仍会用应用池化引擎，跨 loop 触发 pool_pre_ping 失败。
        """
        assert _process(client, token, job_id).status_code == 200
        monkeypatch.setattr(import_module, "async_session_factory", _probe_session_factory)

    def test_runner_completes_with_real_row_count(
        self, admin_token: str, client: TestClient, monkeypatch
    ):
        """正常路径：completed 且 total_rows == 文件真实行数（3），进度 100%。"""
        job_id = _upload(client, admin_token, "s71_ok.csv", THREE_ROW_CSV).json()["id"]
        self._start_job_without_scheduling(client, admin_token, job_id, monkeypatch)

        asyncio.run(import_module._process_import(job_id))

        status, total_rows, errors = _job_snapshot(job_id)
        assert status == "completed", errors
        assert total_rows == 3
        assert errors == []

        progress = client.get(
            f"/api/v1/admin/import/{job_id}/progress",
            headers={"Authorization": f"Bearer {admin_token}"},
        ).json()
        assert progress["status"] == "completed"
        assert progress["total_rows"] == 3
        assert progress["progress_pct"] == 100.0

    def test_runner_fails_when_upload_file_missing(
        self, admin_token: str, client: TestClient, monkeypatch
    ):
        """反例：文件被删 → failed 且 errors 有内容（不再静默成功）。"""
        job_id = _upload(client, admin_token, "s71_missing.csv", THREE_ROW_CSV).json()["id"]
        self._start_job_without_scheduling(client, admin_token, job_id, monkeypatch)

        path = import_module._find_upload_file(job_id)
        assert path is not None
        Path(path).unlink()

        asyncio.run(import_module._process_import(job_id))

        status, _total, errors = _job_snapshot(job_id)
        assert status == "failed"
        assert errors and "未找到上传文件" in errors[0]

    def test_runner_writes_no_fake_rows(self, admin_token: str, client: TestClient, monkeypatch):
        """回归：原实现会造 100 条假岗位 —— 现在必须一条不写。"""
        job_id = _upload(client, admin_token, "s71_nofake.csv", THREE_ROW_CSV).json()["id"]
        self._start_job_without_scheduling(client, admin_token, job_id, monkeypatch)

        raw_before = _count_rows("job_raw_data")
        profiles_before = _count_rows("job_profiles")

        asyncio.run(import_module._process_import(job_id))

        status, _total, errors = _job_snapshot(job_id)
        assert status == "completed", errors
        assert _count_rows("job_raw_data") == raw_before
        assert _count_rows("job_profiles") == profiles_before
