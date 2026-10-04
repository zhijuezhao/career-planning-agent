"""B4-c 单元测试：聚合编排（mock 掉 DB 与 LLM，只测编排逻辑）。

覆盖：分组→逐组综合→对卡评分→落库、失败计数不静默、`titles` 过滤、dry-run 不落库、
等级/薪资统计正确透传。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.core.skills import BONUS_SKILL_LIMIT, CORE_SKILL_LIMIT
from app.domain.services import job_aggregate_service as svc


def _raw(title: str, salary: str, **extra) -> dict:
    return {
        "title": title,
        "salary": salary,
        "description": extra.pop("description", "岗位职责描述"),
        "requirements": "",
        "company": "某公司",
        "city": "北京",
        "industry": "互联网",
        "payload": {"extract": {"hard_skills": ["Java"]}, "source": {}},
        **extra,
    }


def _card(ok: bool = True, **over):
    card = {
        "role": "x",
        "level": "初级",
        "posting_count": 3,
        "consensus_duties": ["职责"],
        "consensus_requirements": ["要求"],
        "core_skills": ["Java", "MySQL"],
        "bonus_skills": ["Redis"],
        "differentiators": [],
        "excluded_noise": ["丢了公司简介"],
        "level_objections": [],
        "education_range": "本科",
        "experience_range": "1-3年",
        "city_distribution": ["北京"],
        "top_companies": ["某公司"],
        "aggregate_ok": ok,
        "aggregate_error": None if ok else "TimeoutError: boom",
        "aggregate_problems": [],
    }
    card.update(over)
    return card


def _portrait(ok: bool = True):
    return {
        "six_dimensions": {
            "专业技术能力": {"score": 3, "key_skills": ["Java"]},
            "实践经验背景": {"score": 3},
            "通用软素质": {"score": 3},
            "职业匹配度": {"score": 3},
            "成长潜力": {"score": 3},
            "基础资质条件": {"score": 3},
        },
        "outlook": {"outlook": "成熟", "trend": "", "risk_factors": []},
        "summary": "综合摘要",
        "portrait_ok": ok,
        "portrait_error": None if ok else "LLM 挂了",
    }


class _StubTool:
    """替身工具。

    为什么不 `monkeypatch.setattr(job_aggregator, "ainvoke", ...)`：
    LangChain 的 `StructuredTool` 是 **pydantic 模型**，`ainvoke` 不是可写字段
    （会抛 `ValueError: "StructuredTool" object has no field "ainvoke"`）。
    所以替换**模块级名字**（服务是 `from ... import job_aggregator`）。
    """

    def __init__(self, handler):
        self._handler = handler

    async def ainvoke(self, payload):
        return await self._handler(payload)


@pytest.fixture()
def wired(monkeypatch):
    """把 DB 与 LLM 全换成替身，返回可断言的记录器。"""
    calls: dict[str, list] = {"aggregate": [], "portrait": [], "upsert": []}

    async def fake_load(_session):
        return [
            _raw("Java", "5000"),
            _raw("Java", "5200"),
            _raw("Java", "5400"),
            _raw("前端开发", "8000"),
            _raw("前端开发", "8200"),
            _raw("前端开发", "8400"),
        ]

    async def fake_aggregate(payload):
        calls["aggregate"].append(payload)
        return _card()

    async def fake_portrait(payload):
        calls["portrait"].append(payload)
        return _portrait()

    async def fake_upsert(_session, **kwargs):
        calls["upsert"].append(kwargs)

    monkeypatch.setattr(svc, "_load_raw_rows", fake_load)
    monkeypatch.setattr(svc, "job_aggregator", _StubTool(fake_aggregate))
    monkeypatch.setattr(svc, "portrait_builder", _StubTool(fake_portrait))
    monkeypatch.setattr(svc, "_upsert_group", fake_upsert)
    return calls


def _session():
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


class TestAggregateRoles:
    @pytest.mark.asyncio
    async def test_one_call_per_group_and_one_upsert(self, wired):
        stats = await svc.aggregate_roles(_session())

        # 6 行 → 2 个组：java 的 5000/5200/5400 都 <6000 → 初级；
        # 前端开发的 8000/8200/8400 落在 6000–12000 → 中级
        assert stats["groups"] == 2
        assert stats["ok"] == 2
        assert stats["failed"] == 0
        assert stats["postings"] == 6
        assert len(wired["aggregate"]) == 2
        # **每组只评一次六维**（这正是顺序 B 相对"逐条评分再平均"的核心收益）
        assert len(wired["portrait"]) == 2
        assert len(wired["upsert"]) == 2
        assert stats["by_level"] == {"初级": 1, "中级": 1}

    @pytest.mark.asyncio
    async def test_level_and_salary_stats_reach_upsert(self, wired):
        await svc.aggregate_roles(_session())

        by_title = {call["title"]: call for call in wired["upsert"]}
        java = by_title["Java"]
        assert java["level"] == "初级"
        # 用户要求「两者都存」：包络 + 中位数都要落
        assert java["salary_stats"]["envelope"] == "5000-5400"
        # 组内全是单值 → 中位数退化成同一个数，渲染成单值而不是 "5200-5200"
        assert java["salary_stats"]["median"] == "5200"
        assert java["salary_stats"]["n"] == 3
        # 综合卡必须落库（含"丢了什么"），否则无法复核
        assert java["card"]["excluded_noise"] == ["丢了公司简介"]
        assert java["card_payload"]["salary_range"]["envelope"] == "5000-5400"

    @pytest.mark.asyncio
    async def test_aggregate_failure_is_counted_not_silent(self, wired, monkeypatch):
        async def failing(payload):
            wired["aggregate"].append(payload)
            return _card(ok=False)

        monkeypatch.setattr(svc, "job_aggregator", _StubTool(failing))
        stats = await svc.aggregate_roles(_session())

        assert stats["ok"] == 0
        assert stats["failed"] == 2
        assert stats["errors"], "失败必须留下原因"
        assert not wired["upsert"], "综合卡失败时不该落库半成品"

    @pytest.mark.asyncio
    async def test_portrait_failure_is_counted(self, wired, monkeypatch):
        async def bad_portrait(payload):
            wired["portrait"].append(payload)
            return _portrait(ok=False)

        monkeypatch.setattr(svc, "portrait_builder", _StubTool(bad_portrait))
        stats = await svc.aggregate_roles(_session())

        assert stats["ok"] == 2
        assert stats.get("portrait_failed") == 2

    @pytest.mark.asyncio
    async def test_titles_filter(self, wired):
        stats = await svc.aggregate_roles(_session(), titles={"java"})
        assert stats["groups"] == 1
        assert wired["upsert"][0]["title"] == "Java"

    @pytest.mark.asyncio
    async def test_dry_run_does_not_write(self, wired, monkeypatch):
        commits = {"n": 0}

        async def counting_commit():
            commits["n"] += 1

        session = AsyncMock()
        session.commit = counting_commit
        stats = await svc.aggregate_roles(session, dry_run=True)

        assert stats["ok"] == 2
        assert stats["dry_run"] is True
        assert not wired["upsert"]
        assert commits["n"] == 0, "dry-run 不该提交"

    @pytest.mark.asyncio
    async def test_commits_once_after_all_groups(self, wired, monkeypatch):
        commits = {"n": 0}

        async def counting_commit():
            commits["n"] += 1

        session = AsyncMock()
        session.commit = counting_commit
        await svc.aggregate_roles(session)
        assert commits["n"] == 1

    @pytest.mark.asyncio
    async def test_progress_stats_are_complete(self, wired):
        stats = await svc.aggregate_roles(_session())
        for key in ("groups", "ok", "failed", "postings", "by_level", "errors", "elapsed_s", "prompt_version"):
            assert key in stats, key
        assert stats["prompt_version"] == svc.AGGREGATE_PROMPT_VERSION


class TestUpsertGroupSkillNormalisation:
    """B5（2026-10-03）：技能在**落库前**必须归一化 + 限量。

    提示词里已经要求"最基础的技术名词、核心≤20 / 加分≤10"，但提示词是**约定**
    不是**保证** —— 这里是第二道防线（生成时预防 + 落库前归一双保险）。
    """

    @pytest.mark.asyncio
    async def test_normalises_dedupes_and_caps(self, monkeypatch):
        captured: dict = {}

        async def fake_upsert(_session, data):
            captured.update(data)
            return None, True

        monkeypatch.setattr(svc, "upsert_job_profile", fake_upsert)

        await svc._upsert_group(
            AsyncMock(),
            title="Java",
            level="初级",
            salary_stats={"envelope": "8000-12000", "median": "9000"},
            card={
                "core_skills": ["Java开发", "MySQL数据库", "springboot", "Java"]
                + [f"Core{i}" for i in range(30)],
                "bonus_skills": ["Redis缓存", "Go"] + [f"Bonus{i}" for i in range(15)],
                "education_range": "本科",
                "experience_range": "1-3年",
                "excluded_noise": [],
                "level_objections": [],
            },
            card_payload={"core_skills": ["Java"]},
            portrait={
                "six_dimensions": {},
                "outlook": {},
                "summary": "摘要",
                "portrait_ok": True,
            },
            posting_count=3,
        )

        tags = captured["hard_skills"]["tags"]
        # 归约 + 去重（`Java开发` 与 `Java` 归一后是同一个）
        assert tags[:3] == ["Java", "MySQL", "Spring Boot"]
        assert tags.count("Java") == 1
        assert len(tags) == CORE_SKILL_LIMIT  # 核心 ≤20

        bonus = captured["hard_skills"]["bonus_tags"]
        assert bonus[:2] == ["Redis", "Go"]
        assert len(bonus) == BONUS_SKILL_LIMIT  # 加分 ≤10

        # 核心与加分不能重复
        assert not ({t.lower() for t in tags} & {b.lower() for b in bonus})

    @pytest.mark.asyncio
    async def test_salary_and_card_are_passed_through(self, monkeypatch):
        captured: dict = {}

        async def fake_upsert(_session, data):
            captured.update(data)
            return None, True

        monkeypatch.setattr(svc, "upsert_job_profile", fake_upsert)
        await svc._upsert_group(
            AsyncMock(),
            title="Java",
            level="中级",
            salary_stats={"envelope": "8000-12000", "median": "9000"},
            card={"core_skills": [], "bonus_skills": [], "excluded_noise": ["X"], "level_objections": []},
            card_payload={"core_skills": []},
            portrait={"six_dimensions": {}, "outlook": {}, "summary": "s", "portrait_ok": True},
            posting_count=5,
        )

        assert captured["salary"] == "8000-12000"  # 主值取包络
        assert captured["salary_stats"]["median"] == "9000"  # 中位数另存（"两者都存"）
        assert captured["aggregate_card"]["excluded_noise"] == ["X"]  # 可审计
        assert captured["aggregate_card"]["prompt_version"] == svc.AGGREGATE_PROMPT_VERSION


class TestRawRowToDict:
    def test_includes_payload(self):
        class _Row:
            title = "Java"
            company = "A"
            city = "北京"
            salary = "8000"
            industry = "互联网"
            description = "描述"
            requirements = ""
            payload = {"extract": {"hard_skills": ["Java"]}}

        data = svc.raw_row_to_dict(_Row())
        assert data["title"] == "Java"
        assert data["payload"]["extract"]["hard_skills"] == ["Java"]
