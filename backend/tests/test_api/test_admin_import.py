import asyncio
import io
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.v1.admin import _import_runner, import_module
from app.config import get_settings
from app.core.job_agent.graphs import import_pipeline
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


async def _read_job_full(job_id: int) -> dict | None:
    """S7-3 起需要看全部计数（success/error），单独开一个读取器，不动既有断言。"""
    async with _probe_session_factory() as session:
        row = await session.get(DataImportJob, job_id)
        if row is None:
            return None
        return {
            "status": row.status,
            "total": row.total_rows,
            "processed": row.processed_rows,
            "success": row.success_count,
            "error": row.error_count,
            "errors": list(row.errors or []),
            "stats": dict(row.stats or {}),  # B2-2：persist 阶段统计
        }


def _job(job_id: int) -> dict | None:
    return asyncio.run(_read_job_full(job_id))


async def _count_table(table: str) -> int:
    async with _probe_session_factory() as session:
        return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


def _count_rows(table: str) -> int:
    return asyncio.run(_count_table(table))


def _max_id(table: str) -> int:
    """表当前最大自增 id（用于「只清理本次新增」的精确边界）。"""

    async def _run() -> int:
        async with _probe_session_factory() as session:
            return int(
                (await session.execute(text(f"SELECT coalesce(max(id), 0) FROM {table}"))).scalar_one()
            )

    return asyncio.run(_run())


async def _noop_persist(state: dict) -> dict:
    """persist 阶段的空替身：给「只关心进度/计数」的用例用，避免它们写库。"""
    return {"persist_stats": {}, "status": "completed"}


class _PersistControl:
    """默认把 persist 阶段换成空替身；需要验证真落库的用例调用 `enable()`。

    为什么默认关：本模块多数用例只验证进度/计数映射，真落库会往 dev 库写数据、
    还会让持久化引擎在多个 `asyncio.run` 事件循环间复用连接（S1 的坑）。
    """

    def __init__(self, monkeypatch, real):
        self._monkeypatch = monkeypatch
        self._real = real

    def enable(self) -> None:
        self._monkeypatch.setattr(import_pipeline, "node_persist", self._real)


@pytest.fixture(autouse=True)
def persist_control(monkeypatch) -> _PersistControl:
    real = import_pipeline.node_persist
    monkeypatch.setattr(import_pipeline, "node_persist", _noop_persist)
    return _PersistControl(monkeypatch, real)


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


def _mock_tool(return_value: dict | Exception) -> MagicMock:
    """流水线工具替身：``.ainvoke()`` 返回给定值（沿用 test_core 的 mock 手法）。"""
    tool = MagicMock()
    if isinstance(return_value, Exception):
        tool.ainvoke = AsyncMock(side_effect=return_value)
    else:
        tool.ainvoke = AsyncMock(return_value=return_value)
    return tool


# 三个 LLM 工具的返回值骨架（字段与 import_pipeline 各节点读取的键一致）
_A_GRADE = {
    "grade": "A", "score": 90, "breakdown": {},
    "strengths": [], "weaknesses": [], "summary": "",
}
_EXTRACTED = {
    "title": "数据分析师", "company": "A公司", "city": "北京",
    "salary": "", "description": "", "requirements": "",
    "education_requirement": None, "experience_requirement": None,
    "hard_skills": [], "soft_skills": [],
}
_PORTRAIT = {
    "five_dimensions": {}, "career_paths": [],
    "transition_roles": [], "outlook": {}, "summary": "",
}


@contextmanager
def mock_llm_tools(judge_result: dict | None = None):
    """只替换 3 个 LLM 工具（质检/提取/画像），其余节点跑真实实现。

    `load_data`（真实读文件）、`clean_data`、`dedup` 都是纯规则实现，
    因此这样 mock 之后是「真流水线 + 零 LLM 调用」：测试不触网、不计费。
    """
    with (
        patch(
            "app.core.job_agent.tools.quality_judge.quality_judge",
            _mock_tool(judge_result or _A_GRADE),
        ),
        patch("app.core.job_agent.tools.job_extractor.job_extractor", _mock_tool(_EXTRACTED)),
        patch("app.core.job_agent.tools.portrait_builder.portrait_builder", _mock_tool(_PORTRAIT)),
    ):
        yield


class _FakeGraph:
    """假编译图：按 (node, update) 序列产出 updates chunk，可在阶段间注入观察者。

    ``astream`` 的 yield 语义与 LangGraph 一致：控制权交回调用方，调用方跑完
    本阶段（落库）后再回来取下一个 chunk —— 所以观察者看到的一定是
    「该阶段已 commit」之后的状态，这正是反「只在最后写一次」的断言基础。
    """

    def __init__(self, stages: list[tuple[str, object]], on_stage=None):
        self._stages = stages
        self._on_stage = on_stage
        self.payload: dict | None = None

    async def astream(self, payload: dict, stream_mode: str = "updates"):
        self.payload = payload
        for node, update in self._stages:
            if isinstance(update, Exception):
                raise update
            yield {node: update}
            if self._on_stage is not None:
                await self._on_stage(node)


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
        并把 runner 用的 session 工厂换成 NullPool 探针。

        注意必须 patch `_import_runner.async_session_factory`：S7-3 起后台主体在
        runner 模块里，它在导入时就绑定了这个名字；改 `app.infrastructure.database`
        上的同名属性不会生效，runner 仍会用应用池化引擎，跨 loop 触发 pool_pre_ping 失败。
        """
        assert _process(client, token, job_id).status_code == 200
        monkeypatch.setattr(_import_runner, "async_session_factory", _probe_session_factory)

    def test_runner_completes_with_real_row_count(
        self, admin_token: str, client: TestClient, monkeypatch
    ):
        """正常路径：completed 且 total_rows == 文件真实行数（3），进度 100%。

        S7-3 起后台跑的是真流水线，这里把 3 个 LLM 工具 mock 掉（零调用、不触网），
        `load_data` 仍真实读取上传的 CSV —— 所以 total_rows 是文件真实行数。
        """
        job_id = _upload(client, admin_token, "s71_ok.csv", THREE_ROW_CSV).json()["id"]
        self._start_job_without_scheduling(client, admin_token, job_id, monkeypatch)

        with mock_llm_tools():
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

    def test_runner_writes_only_the_imported_rows(
        self, admin_token: str, client: TestClient, monkeypatch, persist_control
    ):
        """原为「一条不写」的回归（防造 100 条假数据）。

        B2-2 起落库已接上（流水线末尾 `persist` 阶段），因此本用例按它自己的注释
        改为「**只写该写的那几行**」：3 家公司 + 3 条岗位 + 3 条原始行，
        `data_import_jobs.stats.persist` 如实记录，岗位挂到正确的公司上。

        为了断言「新建」而不是「更新」，CSV 里的岗位名/公司名带本次唯一后缀；
        跑完按后缀精确清理（不用 id 边界，避免误删并发写入的数据）。
        """
        suffix = str(int(time.time() * 1000))
        csv = (
            "岗位名称,公司名称,工作城市\n"
            f"数据分析师{suffix},A公司{suffix},北京\n"
            f"后端工程师{suffix},B公司{suffix},上海\n"
            f"产品经理{suffix},C公司{suffix},深圳\n"
        ).encode("utf-8")

        job_id = _upload(client, admin_token, "s71_nofake.csv", csv).json()["id"]
        self._start_job_without_scheduling(client, admin_token, job_id, monkeypatch)
        monkeypatch.setattr(import_pipeline, "async_session_factory", _probe_session_factory)
        persist_control.enable()  # 本用例专门验证真落库

        try:
            with mock_llm_tools():
                asyncio.run(import_module._process_import(job_id))

            status, _total, errors = _job_snapshot(job_id)
            assert status == "completed", errors

            detail = _job(job_id) or {}
            persist = (detail.get("stats") or {}).get("persist") or {}
            assert persist.get("raw_written") == 3
            assert persist.get("profiles_new") == 3
            assert persist.get("profiles_updated") == 0
            assert persist.get("failed") == 0

            # 接口也要把 stats 暴露出去（前端导入详情要展示落库/扣费统计）
            api_job = client.get(
                f"/api/v1/admin/import/{job_id}", headers={"Authorization": f"Bearer {admin_token}"}
            ).json()
            assert api_job["stats"]["persist"]["profiles_new"] == 3

            async def _persisted() -> list[tuple[str, str | None, int | None]]:
                async with _probe_session_factory() as session:
                    rows = (
                        await session.execute(
                            text(
                                "SELECT j.title, c.name, c.job_count "
                                "FROM job_profiles j LEFT JOIN companies c ON c.id = j.company_id "
                                "WHERE j.title LIKE :p ORDER BY j.title"
                            ),
                            {"p": f"%{suffix}"},
                        )
                    ).all()
                    return [(r[0], r[1], r[2]) for r in rows]

            assert asyncio.run(_persisted()) == [
                (f"产品经理{suffix}", f"C公司{suffix}", 1),
                (f"后端工程师{suffix}", f"B公司{suffix}", 1),
                (f"数据分析师{suffix}", f"A公司{suffix}", 1),
            ]

            # 原始行也写了 3 条（source=import）
            async def _raw_count() -> int:
                async with _probe_session_factory() as session:
                    return int(
                        (
                            await session.execute(
                                text(
                                    "SELECT count(*) FROM job_raw_data "
                                    "WHERE title LIKE :p AND source = 'import'"
                                ),
                                {"p": f"%{suffix}"},
                            )
                        ).scalar_one()
                    )

            assert asyncio.run(_raw_count()) == 3

            # B2-5：每个 (岗位, 公司) 组合都写了关联行 —— 3 行 → 3 条关联
            async def _link_count() -> int:
                async with _probe_session_factory() as session:
                    return int(
                        (
                            await session.execute(
                                text(
                                    "SELECT count(*) FROM job_company_links l "
                                    "JOIN job_profiles p ON p.id = l.job_profile_id "
                                    "WHERE p.title LIKE :p"
                                ),
                                {"p": f"%{suffix}"},
                            )
                        ).scalar_one()
                    )

            assert asyncio.run(_link_count()) == 3
        finally:
            async def _cleanup_suffix() -> None:
                async with _probe_session_factory() as session:
                    await session.execute(
                        text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"%{suffix}"}
                    )
                    await session.execute(
                        text("DELETE FROM job_raw_data WHERE title LIKE :p"), {"p": f"%{suffix}"}
                    )
                    await session.execute(
                        text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"%{suffix}"}
                    )
                    await session.commit()

            asyncio.run(_cleanup_suffix())


# ---------------------------------------------------------------------------
# S7-3：接真实流水线 + 阶段级进度
# ---------------------------------------------------------------------------

_ROW_OK = {"title": "数据分析师", "company": "A公司", "city": "北京", "description": "详细描述"}
_ROW_BAD = {"title": "低质岗位", "company": "B公司", "city": "上海", "description": ""}
_D_GRADE = {
    "grade": "D", "score": 30, "breakdown": {},
    "strengths": [], "weaknesses": [], "summary": "描述为空",
}

STAGES_TWO_ROWS: list[tuple[str, object]] = [
    ("load_data", {"raw_rows": [_ROW_OK, _ROW_BAD], "total_input": 2, "status": "loaded"}),
    ("clean_data", {"cleaned_rows": [_ROW_OK, _ROW_BAD], "status": "cleaned"}),
    ("dedup", {"deduped_rows": [_ROW_OK, _ROW_BAD], "status": "deduped"}),
    (
        "quality_judge",
        {
            "quality_results": [_A_GRADE, _D_GRADE],
            "passed_rows": [_ROW_OK],
            "rejected_rows": [_ROW_BAD],
            "total_passed": 1,
            "total_rejected": 1,
            "status": "judged",
        },
    ),
    ("extract", {"extracted_rows": [_EXTRACTED], "status": "extracted"}),
    ("portrait", {"portrait_rows": [_PORTRAIT], "total_exported": 1, "status": "completed"}),
]


class TestImportS73StageProgress:
    """S7-3：假图驱动 —— 阶段进度/计数逐阶段落库（零 LLM、零网络）。"""

    def _run_with_graph(self, client, token, monkeypatch, make_graph):
        """上传 → process → 把 runner 的图与 session 工厂换成测试替身 → 跑 runner。"""
        job_id = _upload(client, token, "s73_stage.csv", THREE_ROW_CSV).json()["id"]
        assert _process(client, token, job_id).status_code == 200
        monkeypatch.setattr(_import_runner, "async_session_factory", _probe_session_factory)
        graph = make_graph(job_id)
        monkeypatch.setattr(_import_runner, "compile_import_pipeline", lambda: graph)
        asyncio.run(import_module._process_import(job_id))
        return job_id, graph

    def test_graph_gets_file_path_and_row_cap(self, admin_token, client, monkeypatch):
        """D-S7-3：行数上限必须真的传到流水线（否则等于没有上限）。"""
        job_id, graph = self._run_with_graph(
            client, admin_token, monkeypatch, lambda _jid: _FakeGraph(STAGES_TWO_ROWS)
        )

        assert graph.payload is not None
        assert graph.payload["nrows"] == _import_runner.IMPORT_MAX_ROWS
        assert graph.payload["sheet_name"] == 0
        expected = import_module._find_upload_file(job_id)
        assert expected is not None
        assert graph.payload["file_path"] == str(expected)

    def test_every_stage_is_committed_before_next(self, admin_token, client, monkeypatch):
        """反「最后才写一次」：每个阶段结束时，进度都能被另一条连接读到。"""
        observed: list[dict] = []

        def make_graph(job_id: int) -> _FakeGraph:
            async def observe(node: str) -> None:
                async with _probe_session_factory() as session:
                    row = await session.get(DataImportJob, job_id)
                observed.append({
                    "node": node,
                    "status": row.status,
                    "total": row.total_rows,
                    "processed": row.processed_rows,
                    "success": row.success_count,
                    "error": row.error_count,
                })

            return _FakeGraph(STAGES_TWO_ROWS, on_stage=observe)

        job_id, _graph = self._run_with_graph(client, admin_token, monkeypatch, make_graph)

        assert [o["node"] for o in observed] == [
            "load_data", "clean_data", "dedup", "quality_judge", "extract", "portrait",
        ]
        by_node = {o["node"]: o for o in observed}

        # load 阶段：total_rows 已落库，状态仍 processing（不谎报 completed）
        assert by_node["load_data"]["total"] == 2
        assert by_node["load_data"]["status"] == "processing"
        # 计数映射：total_passed → success_count，total_rejected → error_count
        assert by_node["quality_judge"]["success"] == 1
        assert by_node["quality_judge"]["error"] == 1
        # 阶段进度单调不减，portrait 到 100%
        processed = [o["processed"] for o in observed]
        assert processed == sorted(processed)
        assert by_node["portrait"]["processed"] == 2
        # 终态在循环之后才写：最后阶段观察到的仍是 processing
        assert by_node["portrait"]["status"] == "processing"

        final = _job(job_id)
        assert final["status"] == "completed"
        assert final["total"] == 2 and final["processed"] == 2
        assert final["success"] == 1 and final["error"] == 1
        assert final["errors"] == ["低质岗位：D 级（30 分） 描述为空"]

    def test_pipeline_exception_marks_job_failed(self, admin_token, client, monkeypatch):
        """D-S7-6=A：任一阶段失败 → 整单 failed，原因是可见的。"""
        stages = [
            ("load_data", {"raw_rows": [_ROW_OK], "total_input": 1, "status": "loaded"}),
            ("clean_data", RuntimeError("流水线炸了")),
        ]
        job_id, _graph = self._run_with_graph(
            client, admin_token, monkeypatch, lambda _jid: _FakeGraph(stages)
        )

        final = _job(job_id)
        assert final["status"] == "failed"
        assert final["errors"] == ["流水线炸了"]
        assert final["total"] == 1
        assert final["error"] == 1  # total_rows - processed_rows = 1 - 0

    def test_node_reported_failure_aborts_job(self, admin_token, client, monkeypatch):
        """节点自报失败（error_message / status=failed）→ 立刻整单 failed。

        回归：`load_data` 读不动文件时原先只返回空 rows，流水线继续跑完并报
        completed（实测 64 字节垃圾 .xlsx 被判成功），调用方看不到原因。
        """
        stages = [
            (
                "load_data",
                {
                    "raw_rows": [],
                    "total_input": 0,
                    "status": "failed",
                    "error_message": "File is not a zip file",
                },
            )
        ]
        job_id, _graph = self._run_with_graph(
            client, admin_token, monkeypatch, lambda _jid: _FakeGraph(stages)
        )

        final = _job(job_id)
        assert final["status"] == "failed"
        assert final["errors"] == ["File is not a zip file"]


class TestImportS73RealPipeline:
    """最强证据：真流水线（真读文件/真清洗/真去重）跑通，只替换 3 个 LLM 工具。"""

    def _run_real(self, client, token, monkeypatch, judge_result=None):
        job_id = _upload(client, token, "s73_real.csv", THREE_ROW_CSV).json()["id"]
        assert _process(client, token, job_id).status_code == 200
        monkeypatch.setattr(_import_runner, "async_session_factory", _probe_session_factory)
        # persist 阶段的空替身由模块级 autouse fixture `persist_control` 统一挂在，
        # 本类只验证「进度/计数映射」，不往 dev 库写数据。
        with mock_llm_tools(judge_result):
            asyncio.run(import_module._process_import(job_id))
        return job_id

    def test_real_pipeline_completes_with_all_passed(self, admin_token, client, monkeypatch):
        job_id = self._run_real(client, admin_token, monkeypatch)

        final = _job(job_id)
        assert final["status"] == "completed", final["errors"]
        assert final["total"] == 3        # 真读了上传的 CSV
        assert final["processed"] == 3
        assert final["success"] == 3      # 3 行都是 A 级
        assert final["error"] == 0
        assert final["errors"] == []

    def test_real_pipeline_rejects_all_d_grade(self, admin_token, client, monkeypatch):
        """质检恒返 D：全部被拒 → 计数映射正确且原因可读。"""
        job_id = self._run_real(client, admin_token, monkeypatch, judge_result=_D_GRADE)

        final = _job(job_id)
        assert final["status"] == "completed", final["errors"]
        assert final["total"] == 3
        assert final["success"] == 0
        assert final["error"] == 3
        assert len(final["errors"]) == 3
        assert all("D 级" in text for text in final["errors"])

    def test_real_pipeline_fails_on_unreadable_file(self, admin_token, client, monkeypatch):
        """活体发现的缺陷回归：损坏的 .xlsx 必须 failed 且原因可见（不能报 completed）。

        走真流水线（load_data 真调 pandas/openpyxl），读取在第一个节点就失败，
        因此不会触发任何 LLM 调用。
        """
        job_id = _upload(client, admin_token, "s73_broken.xlsx", bytes(range(64))).json()["id"]
        assert _process(client, admin_token, job_id).status_code == 200
        monkeypatch.setattr(_import_runner, "async_session_factory", _probe_session_factory)

        with mock_llm_tools():
            asyncio.run(import_module._process_import(job_id))

        final = _job(job_id)
        assert final["status"] == "failed"
        assert final["errors"], "失败原因不能为空"
        assert final["total"] == 0
