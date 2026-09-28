"""B3-1 接入导入流水线：节点位置、进度表、统计落库、以及"富化真的先于质检"。

这一组用例守的是**接线**，不是算法：算法在各自的测试里。接线错了两边测试都不会红，
但线上表现是"功能写了却从不生效"或"进度条倒退"。

最关键的一条是 `test_quality_judge_sees_enriched_fields`：用户拍板把富化放在
**质检之前**，理由是"链接里有公司/薪资/描述，不该因为表格没写就被判 D"。
这条用例直接把"质检看到的行里有没有链接补的字段"抓出来断言，接线一断就红。
"""

from __future__ import annotations

import asyncio
import importlib
import time

from app.api.v1.admin._import_runner import STAGE_PROGRESS, _apply_stage
from app.core.job_agent.graphs.import_pipeline import (
    merge_rows_for_persist,
    node_link_enrich,
    node_quality_judge,
)
from app.domain.models.import_job import DataImportJob
from sqlalchemy import text
from tests.conftest import test_session_factory

# ⚠️ importlib 取模块：`from app.core.job_agent.tools import quality_judge` 拿到的是
# StructuredTool 对象（包内同名导出），对它 monkeypatch 无效。
qj_module = importlib.import_module("app.core.job_agent.tools.quality_judge")

_EXPECTED_STAGES = (
    "load_data",
    "clean_data",
    "dedup",
    "link_enrich",
    "quality_judge",
    "extract",
    "portrait",
    "persist",
)


class TestStageTable:
    def test_link_enrich_stage_is_registered(self):
        assert set(STAGE_PROGRESS) == set(_EXPECTED_STAGES)

    def test_progress_is_strictly_increasing(self):
        # 前端进度条只认"只增不减"；插阶段时最容易犯的错就是忘了重排百分比
        values = [STAGE_PROGRESS[name] for name in _EXPECTED_STAGES]
        assert values == sorted(values)
        assert len(set(values)) == len(values)
        assert values[0] > 0 and values[-1] == 100

    def test_link_enrich_sits_between_dedup_and_quality_judge(self):
        ordered = list(STAGE_PROGRESS)
        assert ordered.index("dedup") < ordered.index("link_enrich")
        assert ordered.index("link_enrich") < ordered.index("quality_judge")


class TestNodeDisabled:
    def test_setting_defaults_to_off(self):
        """默认必须是**关**（主计划 §4.5：先让代码上线但不出网，验证后再开）。

        断言字段的**默认值**，而不是 `get_settings().link_enrich_enabled` —— 后者会被
        环境变量影响（真机验收时要临时把开关打开），那样这条用例会在"开关开着"的环境里
        假红，属于依赖环境的坏测试（P5 已经在"库非空"上吃过一次同样的亏）。
        """
        from app.config import Settings

        assert Settings.model_fields["link_enrich_enabled"].default is False

    async def test_disabled_returns_stats_and_does_not_touch_rows(self, monkeypatch):
        from app.core.link_enrich.service import EnrichConfig

        monkeypatch.setattr(
            EnrichConfig,
            "from_settings",
            classmethod(lambda cls, settings=None: EnrichConfig(enabled=False)),
        )
        rows = [{"title": "Java", "source_url": "https://jobs.example.com/1"}]
        update = await node_link_enrich({"deduped_rows": rows})
        assert update["link_enrich_stats"]["enabled"] is False
        assert "enriched_rows" not in update


class TestNodeEnabled:
    async def test_enabled_returns_enriched_rows(self, monkeypatch):
        import app.core.link_enrich as pkg
        from app.core.link_enrich.service import EnrichConfig

        async def fake_enrich(rows, **kwargs):
            out = [dict(r, company="补的公司") for r in rows]
            return out, {"enabled": True, "rows_enriched": len(out)}

        monkeypatch.setattr(pkg, "enrich_rows", fake_enrich)
        monkeypatch.setattr(
            EnrichConfig, "from_settings", classmethod(lambda cls, settings=None: EnrichConfig(enabled=True))
        )

        update = await node_link_enrich({"deduped_rows": [{"title": "Java"}]})
        assert update["enriched_rows"][0]["company"] == "补的公司"
        assert update["link_enrich_stats"]["enabled"] is True


class TestQualityJudgeOrdering:
    async def test_quality_judge_sees_enriched_fields(self, monkeypatch):
        """富化必须发生在质检**之前** —— 否则链接补齐的字段对质检无效。"""
        seen: list[str] = []

        class _FakeJudge:
            async def ainvoke(self, payload):
                seen.append(payload["job_data"])
                return {"grade": "B", "score": 80, "summary": "", "breakdown": {}, "strengths": [], "weaknesses": []}

        monkeypatch.setattr(qj_module, "quality_judge", _FakeJudge())

        state = {
            "schema_profile": {"genre": "job_posting"},
            "deduped_rows": [{"title": "Java", "company": None, "salary": None}],
            "enriched_rows": [{"title": "Java", "company": "链接补的公司", "salary": "20-30K"}],
        }
        await node_quality_judge(state)

        assert seen, "质检没有被调用"
        assert "链接补的公司" in seen[0]
        assert "20-30K" in seen[0]

    async def test_falls_back_to_deduped_rows_when_no_enrichment(self, monkeypatch):
        seen: list[str] = []

        class _FakeJudge:
            async def ainvoke(self, payload):
                seen.append(payload["job_data"])
                return {"grade": "A", "score": 90, "summary": "", "breakdown": {}, "strengths": [], "weaknesses": []}

        monkeypatch.setattr(qj_module, "quality_judge", _FakeJudge())
        state = {
            "schema_profile": {"genre": "job_posting"},
            "deduped_rows": [{"title": "只有去重行"}],
        }
        await node_quality_judge(state)
        assert "只有去重行" in seen[0]


class TestStatsLanding:
    def _job(self) -> DataImportJob:
        return DataImportJob(
            file_name="x.xlsx", file_size=1, status="processing", total_rows=1, processed_rows=0,
            success_count=0, error_count=0,
        )

    def test_link_enrich_stats_written_to_job(self):
        job = self._job()
        _apply_stage(job, "link_enrich", {"link_enrich_stats": {"enabled": True, "rows_enriched": 3}})
        assert job.stats["link_enrich"]["rows_enriched"] == 3

    def test_disabled_run_still_records_a_reason(self):
        # 开关关着也要写一条 enabled=false —— 让"这次为什么没富化"在导入详情里自解释
        job = self._job()
        _apply_stage(job, "link_enrich", {"link_enrich_stats": {"enabled": False}})
        assert job.stats["link_enrich"] == {"enabled": False}

    def test_existing_stats_are_preserved(self):
        job = self._job()
        job.stats = {"schema": {"genre": "job_posting"}}
        _apply_stage(job, "link_enrich", {"link_enrich_stats": {"enabled": True}})
        assert job.stats["schema"] == {"genre": "job_posting"}
        assert job.stats["link_enrich"] == {"enabled": True}


class TestRowCarriesEnrichmentToPersist:
    def test_merge_for_persist_keeps_enrich_stats_and_source_url(self):
        row = {
            "title": "Java",
            "company": "链接补的公司",
            "source_url": "https://jobs.example.com/1",
            "enrich_stats": {"version": 1, "filled": ["company"]},
        }
        merged = merge_rows_for_persist({"passed_rows": [row], "extracted_rows": [], "portrait_rows": []})
        # 落库路径靠 merge_rows_for_persist 装配行，链接产物必须活着走到 persist
        assert merged[0]["source_url"] == "https://jobs.example.com/1"
        assert merged[0]["enrich_stats"]["filled"] == ["company"]

    def test_llm_stages_cannot_wipe_enrich_stats(self):
        # 画像/提取产物里没有这两个键，且 overlay 只覆盖非空值 → 不可能被抹掉
        row = {"title": "Java", "enrich_stats": {"version": 1}, "source_url": "https://a.com/1"}
        merged = merge_rows_for_persist(
            {
                "passed_rows": [row],
                "extracted_rows": [{"company": "LLM 提取的公司"}],
                "portrait_rows": [{"six_dimensions": {}}],
            }
        )
        assert merged[0]["enrich_stats"] == {"version": 1}
        assert merged[0]["source_url"] == "https://a.com/1"


_PREFIX = f"linkenrich_{int(time.time())}"


class TestPersistWritesEnrichColumns:
    """`job_profiles.source_url` / `enrich_stats` 此前**只在 DDL 里、ORM 没映射** ——
    列在库里但谁也写不进去。这组用例证明映射补上后写读都通。

    实现方式刻意用「sync 测试 + 一个 `asyncio.run` + NullPool」而不是 `db_session`
    夹具：`pytest.ini` 里 `asyncio_default_fixture_loop_scope = session`，即**异步夹具
    跑在 session 循环、测试体跑在 function 循环**；一旦夹具内部碰过连接，连接就绑死在
    session 循环上，测试体再用必然 `got Future attached to a different loop`
    （2026-09-27 实测）。同一个 `asyncio.run` 里做完所有事就没有跨循环。
    """

    @staticmethod
    async def _cleanup() -> None:
        async with test_session_factory() as session:
            await session.execute(
                text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
            )
            await session.execute(
                text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"{_PREFIX}%"}
            )
            await session.commit()

    def setup_method(self):
        asyncio.run(self._cleanup())

    def teardown_method(self):
        asyncio.run(self._cleanup())

    def test_new_profile_persists_source_url_and_enrich_stats(self):
        from app.domain.services.job_persist_service import upsert_job_profile

        async def _run() -> None:
            async with test_session_factory() as session:
                profile, created = await upsert_job_profile(
                    session,
                    {
                        "title": f"{_PREFIX} Java 工程师",
                        "source_url": "https://jobs.example.com/1",
                        "enrich_stats": {"version": 1, "filled": ["company"]},
                    },
                )
                await session.commit()
                assert created is True
                assert profile.source_url == "https://jobs.example.com/1"
                assert profile.enrich_stats["filled"] == ["company"]

        asyncio.run(_run())

    def test_later_import_without_links_does_not_wipe_them(self):
        from app.domain.services.job_persist_service import upsert_job_profile

        title = f"{_PREFIX} 前端工程师"

        async def _run() -> None:
            async with test_session_factory() as session:
                await upsert_job_profile(
                    session,
                    {"title": title, "source_url": "https://jobs.example.com/2", "enrich_stats": {"version": 1}},
                )
                await session.commit()

                updated, created = await upsert_job_profile(session, {"title": title, "city": "深圳"})
                await session.commit()
                assert created is False
                # 后一次导入没有链接，但已有的来源与统计不能被抹掉（`_pick` 空值不覆盖）
                assert updated.source_url == "https://jobs.example.com/2"
                assert updated.enrich_stats == {"version": 1}

        asyncio.run(_run())
