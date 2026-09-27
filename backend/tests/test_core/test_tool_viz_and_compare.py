"""P5：**工具 → viz** 链路 + 两个六维对比工具（`gap_analysis` / `job_compare`）的测试。

三块：
1. **管道**（`nodes._split_tool_viz` / `execute_tools`）：viz 必须被**摘出来**，不能进
   `ToolMessage` —— 它是 ECharts option（几十上百个数字/中文键），给模型看就是纯烧 token；
2. **gap_analysis**：我 vs 一个岗位；**缺任一侧数据就不出图**（不编数据）；
3. **job_compare**：多个岗位的要求强度对比；有画像的不足 2 个就不出图。

另有一条**跨模块**不变量：产 viz 的工具都在 `viz_sink` 之外**不暴露** option 给模型。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from app.core.agent.nodes import _split_tool_viz, execute_tools
from app.core.agent.tools import AGENT_TOOLS, get_agent_tools
from app.core.agent.tools.matching import gap_analysis, job_compare
from app.core.dimensions.rubrics import DIMENSION_ORDER
from app.domain.services.job_persist_service import upsert_job_profile
from langchain_core.messages import AIMessage
from sqlalchemy import text
from tests.conftest import test_session_factory

_PREFIX = f"p5cmp_{int(time.time())}"

#: 岗位画像（六维）—— 与"我的分数"刻意不同，便于断言 gap 的正负号
_JOB_PORTRAIT = {
    "专业技术能力": {"score": 5},
    "实践经验背景": {"score": 4},
    "通用软素质": {"score": 3},
    "职业匹配度": {"score": 3},
    "成长潜力": {"score": 4},
    "基础资质条件": {"score": 2},
}
#: 我的六维
_MY_SCORES = {
    "专业技术能力": 4,
    "实践经验背景": 2,
    "通用软素质": 3,
    "职业匹配度": 3,
    "成长潜力": 4,
    "基础资质条件": 5,
}


def _radar_viz() -> dict:
    return {"kind": "radar", "title": "t", "option": {"series": []}}


@pytest.fixture(autouse=True)
def nullpool_session_factory(monkeypatch):
    """工具自建 session 用的是**池化** engine，测试里各用例各起事件循环 → 会跨 loop 复用连接。
    换成 NullPool 测试工厂（与 P4 的工具测试同一处理，原因见 `conftest.py` 开头）。"""
    import app.core.agent.tools.matching as matching_module

    monkeypatch.setattr(matching_module, "async_session_factory", test_session_factory)


async def _cleanup() -> None:
    async with test_session_factory() as session:
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM users WHERE username LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.commit()


@pytest.fixture(scope="module", autouse=True)
def clean_p5cmp_rows():
    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


async def _seed_job(name: str, portrait: dict | None) -> int:
    async with test_session_factory() as session:
        row: dict = {"title": f"{_PREFIX}_{name}", "company": f"{_PREFIX}_公司"}
        if portrait is not None:
            row["six_dimensions"] = portrait
        profile, _ = await upsert_job_profile(session, row)
        await session.commit()
        return int(profile.id)


async def _seed_user_with_snapshot(scores: dict | None) -> int:
    async with test_session_factory() as session:
        user_id = int(
            (
                await session.execute(
                    text(
                        "INSERT INTO users (username, password_hash, role, status, "
                        "created_at, updated_at) "
                        "VALUES (:u, 'x', 'student', 1, now(), now()) RETURNING id"
                    ),
                    {"u": f"{_PREFIX}_u{int(time.time() * 1000) % 100000}"},
                )
            ).scalar_one()
        )
        if scores is not None:
            await session.execute(
                text(
                    "INSERT INTO student_profiles (user_id, resume_form, created_at, updated_at) "
                    "VALUES (:i, '{}'::jsonb, now(), now())"
                ),
                {"i": user_id},
            )
            await session.execute(
                text(
                    "INSERT INTO profile_snapshots (user_id, profile_id, form_raw_json, "
                    "five_layers_json, six_dim_scores_json, embedding, serial_no, description) "
                    "VALUES (:i, :i, '{}'::jsonb, '{}'::jsonb, CAST(:six AS jsonb), :emb, "
                    "gen_random_uuid(), 'P5 对比测试快照')"
                ),
                {
                    "i": user_id,
                    "six": "{" + ", ".join(f'"{k}": {v}' for k, v in scores.items()) + "}",
                    "emb": "[" + ",".join(["0"] * 1024) + "]",
                },
            )
        await session.commit()
        return user_id


class TestSplitToolViz:
    """viz 与"给模型的结果"必须分开。"""

    def test_viz_is_stripped_from_the_model_payload(self):
        payload, viz = _split_tool_viz({"total": 3, "viz": [_radar_viz()]})
        assert payload == {"total": 3}
        assert "viz" not in payload
        assert viz == [_radar_viz()]

    def test_single_dict_viz_is_normalised_to_list(self):
        _, viz = _split_tool_viz({"viz": _radar_viz()})
        assert viz == [_radar_viz()]

    def test_non_dict_and_missing_viz(self):
        assert _split_tool_viz("纯文本") == ("纯文本", [])
        assert _split_tool_viz({"total": 1}) == ({"total": 1}, [])

    def test_non_dict_viz_items_are_dropped(self):
        _, viz = _split_tool_viz({"viz": ["nope", _radar_viz(), 42]})
        assert viz == [_radar_viz()]


class TestExecuteToolsCollectsViz:
    def _tool(self, viz: list | None):
        from langchain_core.tools import tool

        @tool
        async def _demo(query: str = "") -> dict:
            """Demo tool returning optional viz."""
            out: dict = {"total": 1}
            if viz is not None:
                out["viz"] = viz
            return out

        return _demo

    def _state(self, name: str) -> dict:
        return {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": "c1"}])
            ]
        }

    def test_viz_goes_to_sink_and_not_to_the_model(self):
        tool = self._tool([_radar_viz()])
        sink: list = []
        result = asyncio.run(
            execute_tools(
                self._state("_demo"),
                config={"configurable": {"tools_by_name": {"_demo": tool}, "viz_sink": sink}},
            )
        )
        assert sink == [_radar_viz()], "图必须进 sink"
        content = result["messages"][0].content
        assert "viz" not in content and "radar" not in content, "图不能进 ToolMessage（烧 token）"
        assert "total" in content, "业务数据仍要回给模型"

    def test_no_sink_does_not_break(self):
        tool = self._tool([_radar_viz()])
        result = asyncio.run(
            execute_tools(
                self._state("_demo"),
                config={"configurable": {"tools_by_name": {"_demo": tool}}},
            )
        )
        assert "total" in result["messages"][0].content

    def test_tool_without_viz_leaves_sink_empty(self):
        tool = self._tool(None)
        sink: list = []
        asyncio.run(
            execute_tools(
                self._state("_demo"),
                config={"configurable": {"tools_by_name": {"_demo": tool}, "viz_sink": sink}},
            )
        )
        assert sink == []


class TestToolRegistration:
    def test_compare_tools_are_exposed(self):
        names = [t.name for t in get_agent_tools()]
        assert {"gap_analysis", "job_compare"} <= set(names)

    def test_only_compare_tools_declare_viz_producing_shape(self):
        """`gap_analysis` / `job_compare` 需要注入 `user_id`（前者要读"我的"画像）。"""
        gap = next(t for t in AGENT_TOOLS if t.name == "gap_analysis")
        assert "user_id" in gap.args_schema.model_fields
        comp = next(t for t in AGENT_TOOLS if t.name == "job_compare")
        assert "user_id" not in comp.args_schema.model_fields


class TestGapAnalysis:
    def test_comparable_produces_radar_and_signed_gaps(self):
        job_id = asyncio.run(_seed_job("有画像岗", _JOB_PORTRAIT))
        user_id = asyncio.run(_seed_user_with_snapshot(_MY_SCORES))

        result = asyncio.run(gap_analysis.ainvoke({"job_id": job_id, "user_id": user_id}))

        assert result["found"] is True and result["comparable"] is True
        # gap = 岗位要求 − 我的水平
        gaps = result["gaps"]
        assert gaps["专业技术能力"] == 1.0  # 5 − 4
        assert gaps["实践经验背景"] == 2.0  # 4 − 2
        assert gaps["基础资质条件"] == -3.0  # 2 − 5（我超出要求）
        assert result["matched_dimensions"] == list(DIMENSION_ORDER)

        viz = result["viz"][0]
        assert viz["kind"] == "radar"
        data = viz["option"]["series"][0]["data"]
        assert [d["name"] for d in data] == ["我的能力", "岗位要求"]
        # 序列分值按**轴顺序**（DIMENSION_ORDER）排 —— 错序会让雷达变形
        assert data[0]["value"][0] == _MY_SCORES["专业技术能力"]
        assert data[1]["value"][0] == _JOB_PORTRAIT["专业技术能力"]["score"]

    def test_no_snapshot_is_not_comparable_and_emits_no_viz(self):
        job_id = asyncio.run(_seed_job("有画像岗2", _JOB_PORTRAIT))
        user_id = asyncio.run(_seed_user_with_snapshot(None))

        result = asyncio.run(gap_analysis.ainvoke({"job_id": job_id, "user_id": user_id}))
        assert result["found"] is True and result["comparable"] is False
        assert "viz" not in result
        assert "画像" in result["reason"]

    def test_job_without_portrait_is_not_comparable(self):
        job_id = asyncio.run(_seed_job("无画像岗", None))
        user_id = asyncio.run(_seed_user_with_snapshot(_MY_SCORES))

        result = asyncio.run(gap_analysis.ainvoke({"job_id": job_id, "user_id": user_id}))
        assert result["comparable"] is False and "viz" not in result
        assert result["job_scores"] == {}

    def test_job_not_found(self):
        result = asyncio.run(gap_analysis.ainvoke({"job_id": 999999999, "user_id": 1}))
        assert result["found"] is False and result["comparable"] is False

    def test_missing_dimension_stays_none_not_zero(self):
        """岗位画像只给了一维 → 其余维的 gap 必须是 `None`，不能是 0（0 = 谎称"刚好达标"）。"""
        partial = {"专业技术能力": {"score": 5}}
        job_id = asyncio.run(_seed_job("半画像岗", partial))
        user_id = asyncio.run(_seed_user_with_snapshot(_MY_SCORES))

        result = asyncio.run(gap_analysis.ainvoke({"job_id": job_id, "user_id": user_id}))
        assert result["gaps"]["专业技术能力"] == 1.0
        assert result["gaps"]["成长潜力"] is None
        assert result["matched_dimensions"] == ["专业技术能力"]


class TestJobCompare:
    def test_two_jobs_produce_two_series(self):
        first = asyncio.run(_seed_job("对比岗甲", _JOB_PORTRAIT))
        second = asyncio.run(
            _seed_job("对比岗乙", {**{d: {"score": 2} for d in DIMENSION_ORDER}})
        )

        result = asyncio.run(job_compare.ainvoke({"job_ids": [first, second]}))
        assert result["found"] is True
        viz = result["viz"][0]
        data = viz["option"]["series"][0]["data"]
        assert len(data) == 2
        assert len(result["comparable_jobs"]) == 2

    def test_fewer_than_two_comparable_emits_no_viz(self):
        only = asyncio.run(_seed_job("对比岗单", _JOB_PORTRAIT))
        blank = asyncio.run(_seed_job("对比岗无画像", None))

        result = asyncio.run(job_compare.ainvoke({"job_ids": [only, blank]}))
        assert "viz" not in result
        assert "不足 2 个" in result["reason"]

    def test_missing_args(self):
        result = asyncio.run(job_compare.ainvoke({}))
        assert result["found"] is False
