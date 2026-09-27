"""岗位信息 vs 岗位画像的**分离**（用户 2026-09-27 明确要求）。

用户原话：
    我的岗位信息和岗位画像一定要区分开，岗位信息是岗位的信息，后期我对这些岗位信息
    我有二次开发需求。画像是用来做人岗匹配，这些画像是精提出来的，是每个岗位综合的画像。

本文件把这条要求变成可执行的断言：
1. 字段分组互斥（`field_groups`）；
2. **画像写入器碰不到岗位信息列**（纯内存即可证明）；
3. 端到端：portrait 里就算带了 `career_paths`/`transition_roles`，落库的岗位信息也
   必须来自**源文本的确定性解析**，而不是模型产物。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.job_agent.field_groups import (
    JOB_INFO_FIELDS,
    PORTRAIT_FIELDS,
    facts_payload,
    portrait_payload,
)
from app.core.job_agent.tools.portrait_builder import portrait_builder
from app.domain.models.job import JobProfile
from app.domain.services.job_persist_service import apply_job_portrait, upsert_job_profile
from sqlalchemy import text
from tests.conftest import test_session_factory

_PREFIX = f"p4bsep_{int(time.time())}"

SOURCE_DESCRIPTION = "岗位晋升：全栈工程师 / 技术经理\n换岗方向：测试开发工程师 / Python"
SOURCE_REQUIREMENTS = "核心技能：Java、Redis\n所需证书：软考（软件设计师）、Oracle Java认证（OCP/OCM）"

#: 故意与源文本**不同**的模型产物 —— 如果它出现在岗位信息列里，就是分离被破坏
#: （2026-09-27 P5 起画像维度块是**六维中文**，与`core/dimensions/rubrics.py` 同名）
PORTRAIT_PAYLOAD = {
    "six_dimensions": {
        "专业技术能力": {"score": 5, "key_skills": ["微服务"]},
        "实践经验背景": {"score": 4},
        "通用软素质": {"score": 3},
        "职业匹配度": {"score": 3},
        "成长潜力": {"score": 4},
        "基础资质条件": {"score": 3},
    },
    # 这两项**不属于画像**（属岗位信息，由 career_fields 确定性解析）——
    # 故意留在这里，用来验证"模型就算产了也不会进岗位信息列"
    "career_paths": ["模型编的晋升"],
    "transition_roles": ["模型编的换岗"],
    "outlook": {"outlook": "朝阳", "trend": "需求稳定", "risk_factors": []},
    "summary": "模型给的摘要",
    "portrait_ok": True,
    "portrait_error": None,
}


class TestFieldGroups:
    def test_two_groups_are_disjoint(self):
        assert JOB_INFO_FIELDS & PORTRAIT_FIELDS == set()

    def test_expected_membership(self):
        # 岗位信息：源数据 + 确定性解析得到的列
        assert {
            "title",
            "hard_skills",
            "career_path",
            "transition_paths",
            "certificates",
        } <= JOB_INFO_FIELDS
        # 任务 3（2026-09-27）：`company_id` 已从 job_profiles 删除 → 不再是岗位信息列。
        # 这一条同时是**防回归**：集合里放已删除的列，`getattr(profile, column)`
        # （rerun_portrait.py / 本文件下面那个用例）会直接 AttributeError。
        assert "company_id" not in JOB_INFO_FIELDS
        # 岗位画像：模型精提、服务人岗匹配的三列
        assert PORTRAIT_FIELDS == {"requirement_intensity", "outlook", "summary"}

    def test_portrait_payload_maps_pipeline_keys_and_drops_facts(self):
        payload = portrait_payload(PORTRAIT_PAYLOAD)
        assert set(payload) == {"requirement_intensity", "outlook", "summary"}
        assert payload["requirement_intensity"]["专业技术能力"]["score"] == 5
        # 模型给的 career_paths / transition_roles 不该出现在画像载荷里被写库
        assert "career_path" not in payload

    def test_portrait_payload_skips_empty_values(self):
        assert portrait_payload({"summary": "", "outlook": {}, "six_dimensions": None}) == {}

    def test_facts_payload_excludes_portrait(self):
        payload = facts_payload({**PORTRAIT_PAYLOAD, "title": "Java", "hard_skills": ["A"]})
        assert "title" in payload and "hard_skills" in payload
        assert not (set(payload) & PORTRAIT_FIELDS)


class TestPortraitWriterCannotTouchFacts:
    """纯内存证明：画像写入器只碰画像列。"""

    def test_apply_job_portrait_leaves_facts_untouched(self):
        profile = JobProfile(
            title="Java",
            hard_skills=["Java"],
            career_path=["全栈工程师", "技术经理"],
            transition_paths=["测试开发工程师"],
            certificates=["软考（软件设计师）"],
            requirement_intensity={"专业技术能力": {"score": 3, "key_skills": []}},
            outlook={"outlook": "成熟", "trend": "", "risk_factors": []},
            summary="",
        )
        facts_before = {column: getattr(profile, column) for column in JOB_INFO_FIELDS}

        written = apply_job_portrait(profile, PORTRAIT_PAYLOAD)

        assert set(written) == {"requirement_intensity", "outlook", "summary"}
        for column, before in facts_before.items():
            assert getattr(profile, column) == before, f"画像写入改到了岗位信息列 {column}"
        # 画像列确实被更新了
        assert profile.requirement_intensity["专业技术能力"]["score"] == 5
        assert profile.summary == "模型给的摘要"

    def test_empty_portrait_does_not_clear_existing_portrait(self):
        profile = JobProfile(title="Java", summary="旧摘要", outlook={"outlook": "成熟"})
        apply_job_portrait(profile, {"summary": "", "outlook": None, "six_dimensions": None})
        assert profile.summary == "旧摘要"
        assert profile.outlook == {"outlook": "成熟"}


class TestUpsertKeepsFactsFromSourceText:
    """端到端（真实 DB）：岗位信息来自源文本解析，模型产物不得覆盖。"""

    @pytest.fixture(autouse=True)
    def _cleanup(self):
        async def _delete() -> None:
            async with test_session_factory() as session:
                await session.execute(
                    text("DELETE FROM job_raw_data WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
                )
                await session.execute(
                    text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
                )
                await session.commit()

        asyncio.run(_delete())
        yield
        asyncio.run(_delete())

    @staticmethod
    def _row(title: str) -> dict:
        return {
            "title": title,
            "description": SOURCE_DESCRIPTION,
            "requirements": SOURCE_REQUIREMENTS,
            **PORTRAIT_PAYLOAD,
        }

    def test_facts_come_from_source_text_not_from_portrait(self):
        title = f"{_PREFIX}_Java"

        async def _run() -> JobProfile:
            async with test_session_factory() as session:
                profile, created = await upsert_job_profile(session, self._row(title))
                await session.commit()
                assert created is True
                return profile

        profile = asyncio.run(_run())

        # 岗位信息：源文本的确定性解析结果
        assert profile.career_path == ["全栈工程师", "技术经理"]
        assert profile.transition_paths == ["测试开发工程师", "Python"]
        assert profile.certificates == ["软考（软件设计师）", "Oracle Java认证（OCP/OCM）"]
        # 模型编的那两个**没有**进岗位信息列
        assert "模型编的晋升" not in (profile.career_path or [])
        assert "模型编的换岗" not in (profile.transition_paths or [])
        # 画像列照常写入
        assert profile.requirement_intensity["专业技术能力"]["score"] == 5
        assert profile.summary == "模型给的摘要"

    def test_second_upsert_does_not_overwrite_user_facts(self):
        """用户改过岗位信息后再导入同一岗位：岗位信息不被覆盖（只填空），画像照常更新。"""
        title = f"{_PREFIX}_Python"

        async def _first() -> int:
            async with test_session_factory() as session:
                profile, _ = await upsert_job_profile(session, self._row(title))
                # 模拟"用户二次开发"：手工改岗位信息
                profile.career_path = ["用户自己写的晋升"]
                profile.certificates = ["用户自己加的证书"]
                await session.commit()
                return profile.id

        profile_id = asyncio.run(_first())

        async def _second() -> JobProfile:
            async with test_session_factory() as session:
                changed = {**self._row(title), "summary": "第二次导入的摘要"}
                profile, created = await upsert_job_profile(session, changed)
                await session.commit()
                assert created is False
                return profile

        profile = asyncio.run(_second())
        assert profile.id == profile_id
        # 用户自己的岗位信息原封不动
        assert profile.career_path == ["用户自己写的晋升"]
        assert profile.certificates == ["用户自己加的证书"]
        # 画像被更新
        assert profile.summary == "第二次导入的摘要"

    def test_missing_source_labels_leaves_facts_empty(self):
        """源文本没有这些标签 → 岗位信息留空，**不**拿模型产物顶上。"""
        title = f"{_PREFIX}_NoLabels"

        async def _run() -> JobProfile:
            async with test_session_factory() as session:
                profile, _ = await upsert_job_profile(
                    session,
                    {"title": title, "description": "普通描述", "requirements": "普通要求",
                     **PORTRAIT_PAYLOAD},
                )
                await session.commit()
                return profile

        profile = asyncio.run(_run())
        assert not profile.career_path
        assert not profile.transition_paths
        assert not profile.certificates
        assert profile.summary == "模型给的摘要"


class TestPortraitBuilderObservability:
    """画像失败必须**可见**（原先静默返回默认值，让 73/82 行"假装成功"）。"""

    def test_success_marks_portrait_ok(self):
        fake = SimpleNamespace(content='{"six_dimensions": {"专业技术能力": {"score": 4}}, "summary": "s"}')
        gateway = MagicMock()
        gateway.ainvoke = AsyncMock(return_value=fake)
        with patch(
            "app.core.job_agent.tools.portrait_builder.get_llm_gateway", return_value=gateway
        ):
            result = asyncio.run(portrait_builder.ainvoke({"job_data": "{}"}))
        assert result["portrait_ok"] is True
        assert result["portrait_error"] is None
        assert gateway.ainvoke.await_count == 1

    def test_failure_retries_once_then_reports(self):
        gateway = MagicMock()
        gateway.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        with patch(
            "app.core.job_agent.tools.portrait_builder.get_llm_gateway", return_value=gateway
        ):
            result = asyncio.run(portrait_builder.ainvoke({"job_data": "{}"}))
        assert result["portrait_ok"] is False
        assert "LLM unavailable" in (result["portrait_error"] or "")
        assert gateway.ainvoke.await_count == 2  # 重试了一次
        # 仍然返回可继续的默认结构（流水线不该因为一行画像失败而中断）
        assert result["six_dimensions"]["专业技术能力"]["score"] == 3
