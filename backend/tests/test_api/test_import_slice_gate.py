"""B3（2026-10-03）单元测试：切片暂停闸门 `awaiting_confirmation`。

用户要求原话::

    每一个传输完成后就暂停，等待人工确认后，再进行下一个切片的处理，
    这样可以保持数据的完整性不被丢失，还能兼顾性能与安全。

本文件测**纯逻辑**（不需要 DB）：
    * `_resolve_slice` 选片；
    * `_finish_slice` 累加计数、推进 next、决定停在 `awaiting_confirmation` 还是 `completed`；
    * `_apply_stage` 在切片模式下的进度/计数必须**跨片单调**（不能回退）；
    * 状态常量本身（`awaiting_confirmation` 21 字符 → 列宽必须 ≥ 21，这是 DDL 的理由）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from app.api.v1.admin._import_runner import (
    STAGE_PROGRESS,
    _apply_stage,
    _finish_slice,
    _resolve_slice,
    _run_aggregation,
    _touched_titles,
)
from app.api.v1.admin.import_module import _slice_progress
from app.domain.models.import_job import (
    IMPORT_PROCESSABLE_STATUSES,
    IMPORT_STATUS_AWAITING_CONFIRMATION,
    IMPORT_STATUS_COMPLETED,
    IMPORT_STATUS_PENDING,
    DataImportJob,
)

SLICE_SIZE = 50
TOTAL_ROWS = 524
SLICE_COUNT = 11


def _slices_state(**over) -> dict:
    state = {
        "batch_id": "job1",
        "total_rows": TOTAL_ROWS,
        "slice_size": SLICE_SIZE,
        "slice_count": SLICE_COUNT,
        "slices": [
            {
                "k": i,
                "row_start": (i - 1) * SLICE_SIZE,
                "row_end": min(i * SLICE_SIZE, TOTAL_ROWS),
                "rows": min(SLICE_SIZE, TOTAL_ROWS - (i - 1) * SLICE_SIZE),
                "file": f"job1_slice_{i:02d}of{SLICE_COUNT:02d}.xlsx",
            }
            for i in range(1, SLICE_COUNT + 1)
        ],
        "state": IMPORT_STATUS_PENDING,
        "next": 1,
        "done": [],
        "cumulative": {"rows": 0, "passed": 0, "rejected": 0},
    }
    state.update(over)
    return state


def _job() -> DataImportJob:
    return DataImportJob(file_name="x.xlsx", file_size=1, status=IMPORT_STATUS_PENDING)


class _FakeGraph:
    """替身流水线：按 `payload["file_path"]` 的文件名返回预置的节点输出。

    只用真实的 `graph.astream(payload, stream_mode="updates")` 契约，
    这样 `_run_pipeline` 的消费逻辑（state 累积、逐节点 `_apply_stage`、计数）都是真跑的。
    """

    def __init__(self, chunks_by_file: dict[str, list[dict]]) -> None:
        self._chunks_by_file = chunks_by_file

    async def astream(self, payload: dict, stream_mode: str = "updates"):
        for chunk in self._chunks_by_file[Path(payload["file_path"]).name]:
            yield chunk


def _chunks_for(title: str, rows: int = 4) -> list[dict]:
    """一片的最小节点输出：读入 → 质检 → 落库。"""
    return [
        {"load_data": {"total_input": rows, "status": "loaded"}},
        {
            "quality_judge": {
                "total_passed": rows,
                "total_rejected": 0,
                "passed_rows": [{"title": title}],
            }
        },
        {"persist": {"persist_stats": {"raw_written": rows}}},
    ]


def _three_slice_state() -> dict:
    return _slices_state(
        total_rows=12,
        slice_size=4,
        slice_count=3,
        slices=[
            {"k": 1, "file": "s1.xlsx", "rows": 4, "row_start": 0, "row_end": 4},
            {"k": 2, "file": "s2.xlsx", "rows": 4, "row_start": 4, "row_end": 8},
            {"k": 3, "file": "s3.xlsx", "rows": 4, "row_start": 8, "row_end": 12},
        ],
    )


class TestResolveSlice:
    def test_no_slices_state_means_whole_table_mode(self):
        assert _resolve_slice({}, None) is None
        assert _resolve_slice({"slice_count": 0}, None) is None

    def test_returns_next_slice(self):
        state = _slices_state(next=3)
        resolved = _resolve_slice(state, "/tmp/slices")
        assert resolved is not None and resolved is not False
        k, item, path = resolved
        assert k == 3
        assert item["k"] == 3
        assert str(path).endswith(item["file"])

    def test_returns_false_when_all_slices_done(self):
        state = _slices_state(next=SLICE_COUNT + 1, done=list(range(1, SLICE_COUNT + 1)))
        assert _resolve_slice(state, "/tmp/slices") is False


class TestFinishSlice:
    def test_first_slice_parks_at_awaiting_confirmation(self):
        state = _slices_state()
        job = _job()
        _finish_slice(job, (1, state["slices"][0], state), slice_input=50, passed=47, rejected=3)

        assert job.status == IMPORT_STATUS_AWAITING_CONFIRMATION
        assert job.processed_rows == 50  # 累计已处理行数（不是 524）
        assert job.total_rows == TOTAL_ROWS
        assert job.success_count == 47
        slices = job.stats["slices"]
        assert slices["done"] == [1]
        assert slices["next"] == 2
        assert slices["state"] == IMPORT_STATUS_AWAITING_CONFIRMATION
        assert slices["cumulative"] == {"rows": 50, "passed": 47, "rejected": 3}

    def test_last_slice_completes(self):
        state = _slices_state(
            next=SLICE_COUNT,
            done=list(range(1, SLICE_COUNT)),
            cumulative={"rows": 500, "passed": 470, "rejected": 30},
        )
        job = _job()
        _finish_slice(job, (SLICE_COUNT, state["slices"][-1], state), slice_input=24, passed=20, rejected=4)

        assert job.status == IMPORT_STATUS_COMPLETED
        assert job.processed_rows == TOTAL_ROWS  # 100%
        assert job.success_count == 490
        assert job.error_count == 34
        assert job.stats["slices"]["next"] == SLICE_COUNT + 1

    def test_cumulative_accumulates_across_slices(self):
        state = _slices_state(
            next=2, done=[1], cumulative={"rows": 50, "passed": 47, "rejected": 3}
        )
        job = _job()
        _finish_slice(job, (2, state["slices"][1], state), slice_input=50, passed=50, rejected=0)

        assert job.success_count == 97
        assert job.error_count == 3
        assert job.processed_rows == 100


class TestApplyStageSliceProgress:
    def test_progress_is_cumulative_base_plus_slice_stage(self):
        state = _slices_state(
            next=2, done=[1], cumulative={"rows": 50, "passed": 47, "rejected": 3}
        )
        job = _job()
        _apply_stage(job, "load_data", {"total_input": 50}, slice_meta=(2, state["slices"][1], state))

        expected = 50 + int(round(50 * STAGE_PROGRESS["load_data"] / 100))
        assert job.processed_rows == expected
        assert job.total_rows == TOTAL_ROWS

    def test_counters_include_completed_slices(self):
        """关键回归：切片模式下计数不能掉回本片的值（进度条会来回跳）。"""
        state = _slices_state(
            next=3, done=[1, 2], cumulative={"rows": 100, "passed": 90, "rejected": 10}
        )
        job = _job()
        _apply_stage(
            job,
            "extract",
            {"total_input": 50, "total_passed": 45, "total_rejected": 5},
            slice_meta=(3, state["slices"][2], state),
        )
        assert job.success_count == 135  # 90 + 45
        assert job.error_count == 15  # 10 + 5

    def test_whole_table_mode_unchanged(self):
        job = _job()
        _apply_stage(job, "load_data", {"total_input": 524})
        assert job.total_rows == 524
        assert job.processed_rows == int(round(524 * STAGE_PROGRESS["load_data"] / 100))


class TestStatusConstants:
    def test_awaiting_confirmation_is_processable(self):
        """暂停后必须能再次点"继续下一片"（复用同一个 /process 接口）。"""
        assert IMPORT_STATUS_AWAITING_CONFIRMATION in IMPORT_PROCESSABLE_STATUSES

    def test_status_length_requires_widening(self):
        """`awaiting_confirmation` 有 21 字符 —— 建表时代是 VARCHAR(20)，必须加宽。

        这条断言就是 `apply_ddl.ALTER_SPECS` 与 alembic `d1f2a3b4c5e6` 存在的理由：
        不加宽的话第一片跑完写状态就 `value too long`，而且恰好发生在最关键的暂停那一步。
        """
        assert len(IMPORT_STATUS_AWAITING_CONFIRMATION) == 21
        assert len(IMPORT_STATUS_AWAITING_CONFIRMATION) > 20


class TestTouchedTitlesAndAggregation:
    """B4-c：聚合只重算"本次导入碰到的岗位"，且失败不拖垮已完成的导入。"""

    def test_touched_titles_are_normalised(self):
        assert _touched_titles([{"title": "  Java "}, {"title": "APP推广"}, {"title": None}]) == {
            "java",
            "app推广",
        }

    def test_touched_titles_accumulate_across_slices(self):
        state = _slices_state()
        job = _job()
        _finish_slice(job, (1, state["slices"][0], state), 50, 47, 3, touched_titles={"java"})
        assert job.stats["slices"]["touched_titles"] == ["java"]

        state2 = dict(job.stats["slices"])
        _finish_slice(job, (2, state2["slices"][1], state2), 50, 50, 0, touched_titles={"前端开发"})
        assert set(job.stats["slices"]["touched_titles"]) == {"java", "前端开发"}

    def test_run_aggregation_writes_stats(self, monkeypatch):
        captured: dict = {}

        async def fake_aggregate(_session, *, titles=None, dry_run=False):
            captured["titles"] = titles
            return {"groups": 3, "ok": 3, "failed": 0, "postings": 12}

        monkeypatch.setattr(
            "app.domain.services.job_aggregate_service.aggregate_roles", fake_aggregate
        )
        job = _job()
        session = AsyncMock()
        session.commit = AsyncMock()

        asyncio.run(_run_aggregation(session, job, {"java"}))

        assert captured["titles"] == {"java"}
        assert job.stats["aggregate"]["ok"] == 3
        assert not job.errors  # 全成功不该产生 error

    def test_run_aggregation_failure_does_not_mark_import_failed(self, monkeypatch):
        """聚合失败只追加一条可读错误 —— 原始数据确实已完整入库。"""

        async def boom(_session, *, titles=None, dry_run=False):
            raise RuntimeError("LLM 全挂了")

        monkeypatch.setattr("app.domain.services.job_aggregate_service.aggregate_roles", boom)
        job = _job()
        job.status = IMPORT_STATUS_COMPLETED
        session = AsyncMock()
        session.commit = AsyncMock()

        asyncio.run(_run_aggregation(session, job, {"java"}))

        assert job.status == IMPORT_STATUS_COMPLETED, "导入状态不该被聚合失败改掉"
        assert job.stats["aggregate"]["failed"] == -1
        assert job.errors and "聚合阶段失败" in job.errors[0]

    def test_empty_titles_skip_aggregation(self, monkeypatch):
        """本次没有任何行入库时**不许**把空集合改写成 `None`（那会重算全库 ≈174 次 LLM）。"""
        called = False

        async def fake_aggregate(_session, *, titles=None, dry_run=False):
            nonlocal called
            called = True
            return {"groups": 87, "ok": 87, "failed": 0}

        monkeypatch.setattr(
            "app.domain.services.job_aggregate_service.aggregate_roles", fake_aggregate
        )
        job = _job()
        session = AsyncMock()
        session.commit = AsyncMock()

        asyncio.run(_run_aggregation(session, job, set()))

        assert called is False
        assert job.stats["aggregate"]["skipped"] is True
        assert "没有新落库的岗位" in job.stats["aggregate"]["reason"]

    def test_aggregation_can_be_disabled(self, monkeypatch):
        """`IMPORT_AGGREGATE_ENABLED=false` 时跳过，并留下原因（可事后用脚本补跑）。"""
        from app.api.v1.admin import _import_runner

        class _S:
            import_aggregate_enabled = False

        monkeypatch.setattr(_import_runner, "get_settings", lambda: _S())
        job = _job()
        session = AsyncMock()
        session.commit = AsyncMock()

        asyncio.run(_run_aggregation(session, job, {"java"}))

        assert job.stats["aggregate"]["skipped"] is True
        assert "IMPORT_AGGREGATE_ENABLED" in job.stats["aggregate"]["reason"]


class TestSliceAggregationWiring:
    """回归（2026-10-04 验收实测）：阶段 8 的"本次碰到的岗位"必须是**所有片**的并集。

    为什么单开一类：`_finish_slice(touched_titles=...)` 曾经**没有任何生产调用方传参**
    —— 只有本文件的单测传。于是纯函数测试全绿，线上却只聚合**最后一片**的岗位：
    实测 3 片导入里第 1 片的岗位永远拿不到 `salary_stats` / `aggregate_card`，
    只有"逐行 upsert"的画像（B4 的全部价值都在综合卡里）。

    这类错误只在**调用方**，所以断言必须打在 `_run_pipeline` 上，而不是 `_finish_slice` 上。
    """

    def test_titles_from_every_slice_reach_aggregation(self, monkeypatch):
        from app.api.v1.admin import _import_runner

        monkeypatch.setattr(
            _import_runner,
            "compile_import_pipeline",
            lambda: _FakeGraph(
                {
                    "s1.xlsx": _chunks_for("Java 开发"),
                    "s2.xlsx": _chunks_for("APP推广"),
                    "s3.xlsx": _chunks_for("Redis 工程师"),
                }
            ),
        )
        captured: dict = {}

        async def fake_aggregate(session, job, titles):
            captured["titles"] = set(titles)

        monkeypatch.setattr(_import_runner, "_run_aggregation", fake_aggregate)

        job = _job()
        session = AsyncMock()
        session.commit = AsyncMock()
        expected = {"java 开发", "app推广", "redis 工程师"}

        for k in (1, 2, 3):
            current = dict(job.stats["slices"]) if job.stats else _three_slice_state()
            item = current["slices"][k - 1]
            asyncio.run(
                _import_runner._run_pipeline(
                    session, job, Path("slices") / item["file"], slice_meta=(k, item, current)
                )
            )

        assert job.status == IMPORT_STATUS_COMPLETED
        assert job.stats["slices"]["touched_titles"] == sorted(expected)
        assert captured["titles"] == expected, "只聚合最后一片 = 前几片的岗位没有综合卡"

    def test_aggregation_not_called_until_last_slice(self, monkeypatch):
        from app.api.v1.admin import _import_runner

        monkeypatch.setattr(
            _import_runner,
            "compile_import_pipeline",
            lambda: _FakeGraph({"s1.xlsx": _chunks_for("Java 开发")}),
        )
        calls: list[set[str]] = []

        async def fake_aggregate(session, job, titles):
            calls.append(set(titles))

        monkeypatch.setattr(_import_runner, "_run_aggregation", fake_aggregate)

        job = _job()
        session = AsyncMock()
        session.commit = AsyncMock()
        state = _three_slice_state()

        asyncio.run(
            _import_runner._run_pipeline(
                session, job, Path("slices") / "s1.xlsx", slice_meta=(1, state["slices"][0], state)
            )
        )

        assert calls == [], "一个岗位组会跨片，没跑完就聚合会拿到不完整的一组"
        assert job.status == IMPORT_STATUS_AWAITING_CONFIRMATION


class TestSliceProgressPayload:
    def test_extracts_numbers_for_frontend(self):
        stats = {
            "slices": {
                "slice_count": 11,
                "done": [1, 2, 3],
                "next": 4,
                "state": IMPORT_STATUS_AWAITING_CONFIRMATION,
            }
        }
        payload = _slice_progress(stats)
        assert payload == {
            "slice_total": 11,
            "slice_done": 3,
            "slice_next": 4,
            "slice_state": IMPORT_STATUS_AWAITING_CONFIRMATION,
            "slice_warning": None,
        }

    def test_empty_for_jobs_without_slices(self):
        assert _slice_progress({}) == {}
        assert _slice_progress(None) == {}

    def test_surfaces_empty_table_warning(self):
        payload = _slice_progress({"slices": {"slice_count": 0, "warning": "该工作表没有任何数据行"}})
        assert payload["slice_warning"] == "该工作表没有任何数据行"
