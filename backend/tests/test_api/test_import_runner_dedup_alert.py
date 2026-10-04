"""B2（2026-10-03）：去重护栏必须**落到工单上**（stats + errors），不能只写日志。

事故复盘：旧实现把 100 行并成 1 行（删 99%）、4366 行并成 1 行，工单却报
`completed` / `success_count=1`，管理端**看不到任何异常**。

本文件只测纯函数（`node_dedup` 的返回、`_apply_stage` 的落库折算），**不需要 DB**。
"""

from __future__ import annotations

import pytest
from app.api.v1.admin._import_runner import _apply_stage
from app.core.job_agent.graphs.import_pipeline import node_dedup
from app.domain.models.import_job import DataImportJob


def _job() -> DataImportJob:
    return DataImportJob(file_name="x.xlsx", file_size=1, status="processing")


class TestNodeDedupReturnsStats:
    @pytest.mark.asyncio
    async def test_returns_dedup_stats(self):
        state = {"cleaned_rows": [{"title": "Java", "company": "A", "code": "C1"}]}
        update = await node_dedup(state)

        stats = update["dedup_stats"]
        assert stats["input"] == 1
        assert stats["kept"] == 1
        assert stats["alerts"] == []

    @pytest.mark.asyncio
    async def test_distinct_codes_kept_without_alert(self):
        """两个不同编码、同名的行 → 都保留，且不触发告警。"""
        state = {
            "cleaned_rows": [
                {"title": "APP推广", "company": "美团", "code": "C1", "city": "北京"},
                {"title": "APP推广", "company": "美团", "code": "C2", "city": "上海"},
            ]
        }
        update = await node_dedup(state)
        assert update["dedup_stats"]["kept"] == 2
        assert update["dedup_stats"]["identity_removed"] == 0

    @pytest.mark.asyncio
    async def test_mass_removal_produces_alert(self):
        state = {"cleaned_rows": [{"title": "C/C++", "company": None} for _ in range(10)]}
        update = await node_dedup(state)
        assert update["dedup_stats"]["kept"] == 1
        assert update["dedup_stats"]["alerts"], "删除 9/10 必须带告警"


class TestApplyStageSurfacesAlert:
    def test_alert_written_to_stats_and_errors(self):
        job = _job()
        _apply_stage(
            job,
            "dedup",
            {
                "dedup_stats": {
                    "input": 11,
                    "kept": 2,
                    "alerts": ["(岗位名, 公司) 精确去重 阶段删除 9/11 行（>50%），请确认表内是否确实大量重复"],
                }
            },
        )

        assert job.stats["dedup"]["kept"] == 2
        assert job.errors, "告警必须进入 errors（前端失败原因预览卡可见）"
        assert "去重告警" in job.errors[0]

    def test_normal_removal_writes_stats_without_errors(self):
        job = _job()
        _apply_stage(job, "dedup", {"dedup_stats": {"input": 524, "kept": 487, "alerts": []}})

        assert job.stats["dedup"]["kept"] == 487
        assert not job.errors

    def test_alert_appends_to_existing_errors(self):
        """告警不能把已有的失败原因覆盖掉。"""
        job = _job()
        job.errors = ["某岗位：D 级（30 分）"]
        _apply_stage(job, "dedup", {"dedup_stats": {"input": 10, "kept": 1, "alerts": ["删太多"]}})

        assert job.errors[0] == "某岗位：D 级（30 分）"
        assert "去重告警" in job.errors[1]
