"""P4 / C2 零成本只读工具（`job_search` / `job_detail` / `user_snapshot`）测试。

覆盖三件事：
1. **纯函数**：`compact_scores` 对真实画像 JSONB 的**多形状**容错（§18 那次 500 的教训）；
2. **工具本身**（连真实 dev DB）：筛选语义、在招公司、找不到时的返回、空库时的措辞；
3. **运行时身份注入**（`_inject_runtime_args`）：模型**不能**用 `user_id` 冒充别人 ——
   这条是 P4 顺手补的隐私硬化，必须有测试钉住，否则哪天有人改回"模型没给才注入"就静默失守。

⚠️ 工具自建 session 用的是应用**池化** engine（`async_session_factory`）。测试里每个用例
各自 `asyncio.run`（= 各起一个事件循环），池里的 asyncpg 连接会绑在已关闭的 loop 上
→ Windows 下必现 `Event loop is closed`（`tests/conftest.py` 开头记的就是这个坑）。
所以下面统一把工具模块里的工厂换成 conftest 的 **NullPool** `test_session_factory`。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from app.core.agent.nodes import _inject_runtime_args, execute_tools
from app.core.agent.tools import AGENT_TOOLS, get_agent_tools
from app.core.agent.tools.jobs import compact_scores, job_detail, job_search
from app.core.agent.tools.snapshot import user_snapshot
from app.domain.services.job_persist_service import upsert_job_profile
from langchain_core.messages import AIMessage
from sqlalchemy import text
from tests.conftest import test_session_factory

_PREFIX = f"p4tool_{int(time.time())}"


def _title(name: str) -> str:
    return f"{_PREFIX}_{name}"


def _company(name: str) -> str:
    return f"{_PREFIX}_{name}"


@pytest.fixture(autouse=True)
def nullpool_session_factory(monkeypatch):
    """把工具模块里的池化工厂换成 NullPool 测试工厂（见文件头说明）。"""
    import app.core.agent.tools.jobs as jobs_module
    import app.core.agent.tools.snapshot as snapshot_module

    monkeypatch.setattr(jobs_module, "async_session_factory", test_session_factory)
    monkeypatch.setattr(snapshot_module, "async_session_factory", test_session_factory)


async def _cleanup() -> None:
    async with test_session_factory() as session:
        await session.execute(
            text("DELETE FROM job_profiles WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM job_raw_data WHERE title LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM companies WHERE name LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.execute(
            text("DELETE FROM users WHERE username LIKE :p"), {"p": f"{_PREFIX}%"}
        )
        await session.commit()


@pytest.fixture(scope="module", autouse=True)
def clean_p4tool_rows():
    asyncio.run(_cleanup())
    yield
    asyncio.run(_cleanup())


async def _seed_jobs() -> dict[str, int]:
    """三个岗位，覆盖筛选的三种形态（地域用别处不用的地名，断言才敢写死）。

    - `Java工程师`：**广东/深圳**（关联行自带地域）+ 五维画像；
    - `前端开发`：**北京**（关联行没写地域 → 走"回落公司"口径）；
    - `数据分析师`：无地域。
    """
    async with test_session_factory() as session:
        java, _ = await upsert_job_profile(
            session,
            {
                "title": _title("Java工程师"),
                "company": _company("甲"),
                "industry": "互联网",
                "level": "高级",
                "salary": "25-40K",
                "region": "广东",
                "city": "深圳",
                "source_url": "https://example.com/p4/1",
                "five_dimensions": {
                    "technical": {"score": 5, "key_skills": ["Java"]},
                    "experience": {"score": 4},
                    "soft_skills": {"score": 3},
                    "education": {"score": 3},
                    "responsibility": {"score": 4},
                },
                "summary": "后端主力岗",
            },
        )
        front, _ = await upsert_job_profile(
            session,
            {
                "title": _title("前端开发"),
                "company": _company("乙"),
                "industry": "互联网",
                "level": "中级",
                "region": "北京",
                "city": "北京",
            },
        )
        data_job, _ = await upsert_job_profile(
            session,
            {"title": _title("数据分析师"), "company": _company("丙"), "industry": "金融"},
        )
        # 造"关联行没写地域、公司写了"的老数据形态：前端那条的 link 地域清空
        await session.execute(
            text(
                "UPDATE job_company_links SET region = NULL, city = NULL "
                "WHERE job_profile_id = :i"
            ),
            {"i": front.id},
        )
        await session.commit()
        return {
            "java": int(java.id),
            "frontend": int(front.id),
            "data": int(data_job.id),
        }


@pytest.fixture(scope="module")
def seeded_jobs() -> dict[str, int]:
    return asyncio.run(_seed_jobs())


async def _seed_user(*, with_profile: bool, with_snapshot: bool) -> int:
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
        if with_profile:
            await session.execute(
                text(
                    "INSERT INTO student_profiles (user_id, resume_form, created_at, updated_at) "
                    "VALUES (:i, CAST(:f AS jsonb), now(), now())"
                ),
                {
                    "i": user_id,
                    "f": '{"major": "计算机", "degree": "本科", "skills": ["Java", "SQL"]}',
                },
            )
        if with_snapshot:
            # embedding 是 NOT NULL Vector(1024) → 必须给一个 1024 维向量；
            # serial_no 也没有 server_default（是 ORM 侧 default=uuid4），裸 SQL 插入要显式给。
            await session.execute(
                text(
                    "INSERT INTO profile_snapshots (user_id, profile_id, form_raw_json, "
                    "five_layers_json, six_dim_scores_json, embedding, serial_no, description) "
                    "VALUES (:i, :i, '{}'::jsonb, CAST(:five AS jsonb), CAST(:six AS jsonb), "
                    ":emb, gen_random_uuid(), 'P4 工具测试快照')"
                ),
                {
                    "i": user_id,
                    "five": '{"layer1": {"value": "x"}}',
                    "six": '{"technical": 4, "experience": 3, "soft_skills": 4, '
                    '"education": 3, "responsibility": 4, "potential": 3}',
                    "emb": "[" + ",".join(["0"] * 1024) + "]",
                },
            )
        await session.commit()
        return user_id


class TestCompactScores:
    """画像 JSONB 的**多形状**容错（§18：只收 dict 曾让整个岗位列表 500）。"""

    def test_dict_of_dicts(self):
        assert compact_scores({"technical": {"score": 5, "key_skills": ["Java"]}}) == {
            "technical": 5.0
        }

    def test_dict_of_scalars(self):
        assert compact_scores({"technical": 4, "experience": 3.5}) == {
            "technical": 4.0,
            "experience": 3.5,
        }

    def test_dict_of_numeric_strings(self):
        assert compact_scores({"technical": "4"}) == {"technical": 4.0}

    def test_unparsable_entries_are_skipped_not_raised(self):
        # 认不出的键跳过；能认的照常返回 —— 绝不抛错
        assert compact_scores({"a": {"score": 4}, "b": "高", "c": None, "d": []}) == {"a": 4.0}

    @pytest.mark.parametrize("raw", [None, "成熟", ["a"], 5, {}])
    def test_non_dict_shapes_return_none(self, raw):
        assert compact_scores(raw) is None


class TestRuntimeArgInjection:
    """🔒 模型**不能**冒充身份：运行时注入的 user_id/profile_id 一律覆盖模型给的值。"""

    def test_user_id_is_always_overridden(self):
        tool = next(t for t in AGENT_TOOLS if t.name == "user_snapshot")
        args = _inject_runtime_args(tool, {"user_id": 999999}, user_id=7)
        assert args["user_id"] == 7, "模型填的 user_id 必须被服务端顶掉"

    def test_profile_id_also_overridden(self):
        tool = next(t for t in AGENT_TOOLS if t.name == "generate_career_report")
        args = _inject_runtime_args(
            tool, {"user_id": 1, "profile_id": 1, "target_job": "Java"}, user_id=42
        )
        assert args["user_id"] == 42 and args["profile_id"] == 42
        assert args["target_job"] == "Java", "非身份参数不应被动"

    def test_tools_without_identity_fields_untouched(self):
        tool = next(t for t in AGENT_TOOLS if t.name == "job_search")
        args = _inject_runtime_args(tool, {"keyword": "Java"}, user_id=7)
        assert args == {"keyword": "Java"}

    def test_identity_not_injected_when_absent(self):
        """运行时没给 user_id（如后台脚本）→ 不凭空造一个。"""
        tool = next(t for t in AGENT_TOOLS if t.name == "user_snapshot")
        assert _inject_runtime_args(tool, {}, user_id=None) == {}


class TestJobSearchTool:
    def test_registered_and_zero_cost_tools_present(self):
        names = [t.name for t in get_agent_tools()]
        assert {"job_search", "job_detail", "user_snapshot"} <= set(names)

    def test_keyword_is_case_and_space_insensitive(self, seeded_jobs):
        result = asyncio.run(job_search.ainvoke({"keyword": "  java  "}))
        assert result["total"] == 1
        assert result["jobs"][0]["id"] == seeded_jobs["java"]

    def test_region_filter_and_link_level_company(self, seeded_jobs):
        result = asyncio.run(job_search.ainvoke({"region": "广东", "city": "深圳"}))
        assert [j["id"] for j in result["jobs"]] == [seeded_jobs["java"]]
        company = result["jobs"][0]["companies"][0]
        assert company["company_name"] == _company("甲")
        assert (company["region"], company["city"]) == ("广东", "深圳")
        assert company["salary"] == "25-40K"

    def test_region_filter_falls_back_to_company(self, seeded_jobs):
        """前端那条的关联行没写地域 → 按公司所在地（北京）也要筛得到。

        ⚠️ 断言用**包含**而不是相等：dev 库是**共享**的，别的测试（`test_admin_jobs`
        等）也会留下北京/金融这类常见地域/行业的数据 —— 早期写成相等就踩过。
        """
        result = asyncio.run(job_search.ainvoke({"region": "北京"}))
        assert seeded_jobs["frontend"] in [j["id"] for j in result["jobs"]]

    def test_industry_filter(self, seeded_jobs):
        result = asyncio.run(job_search.ainvoke({"industry": "金融"}))
        ids = [j["id"] for j in result["jobs"]]
        assert seeded_jobs["data"] in ids
        # 过滤确实生效：返回的每一条行业都对
        assert all(j["industry"] == "金融" for j in result["jobs"])

    def test_no_match_returns_note_not_error(self):
        result = asyncio.run(job_search.ainvoke({"keyword": f"{_PREFIX}不存在的岗位"}))
        assert result["total"] == 0 and result["jobs"] == []
        assert "note" in result

    def test_limit_is_clamped(self, seeded_jobs):
        """超大 limit 被收敛到上限（`clamp_limit` 防的是**越界**）。"""
        assert asyncio.run(job_search.ainvoke({"limit": 100000}))["returned"] <= 50

    def test_type_invalid_limit_is_rejected_by_schema(self):
        """⚠️ 类型非法的入参在**进函数之前**就被 pydantic 挡掉（`limit: int`）。

        这是刻意的：工具 schema 要清楚（`int` 而不是 `str | int`），模型看到 `int` 就会给数字；
        真给了 `"abc"` 会收到一条校验错误，它会自己纠正。所以 `clamp_limit` 只需管范围，
        不必管类型 —— 这条把该行为钉住，免得有人误以为"脏输入会被兜住"。
        """
        with pytest.raises(Exception) as excinfo:
            asyncio.run(job_search.ainvoke({"limit": "abc"}))
        assert "validation error" in str(excinfo.value).lower()


class TestJobDetailTool:
    def test_by_id_returns_facts_companies_and_portrait(self, seeded_jobs):
        result = asyncio.run(job_detail.ainvoke({"job_id": seeded_jobs["java"]}))
        assert result["found"] is True
        job = result["job"]
        assert job["title"] == _title("Java工程师")
        assert job["industry"] == "互联网" and job["level"] == "高级"
        # 画像五维被压成 {维度: 分数}（不是原 JSONB）
        assert job["portrait_dimensions"]["technical"] == 5.0
        assert job["company_count"] == 1
        link = job["companies"][0]
        assert link["region"] == "广东" and link["source_url"] == "https://example.com/p4/1"

    def test_by_title_is_normalised(self, seeded_jobs):
        result = asyncio.run(job_detail.ainvoke({"title": f"  {_title('java工程师').upper()}  "}))
        assert result["found"] is True
        assert result["job"]["id"] == seeded_jobs["java"]

    def test_not_found(self):
        assert asyncio.run(job_detail.ainvoke({"job_id": 999999999}))["found"] is False

    def test_missing_args(self):
        result = asyncio.run(job_detail.ainvoke({}))
        assert result["found"] is False and "error" in result


class TestUserSnapshotTool:
    def test_with_profile_and_snapshot(self):
        user_id = asyncio.run(_seed_user(with_profile=True, with_snapshot=True))
        result = asyncio.run(user_snapshot.ainvoke({"user_id": user_id}))
        assert result["has_profile"] is True and result["has_snapshot"] is True
        assert result["snapshot_count"] == 1
        # 表单只给"形状"：标量直出，列表给数量（避免把整棵树塞进上下文）
        assert result["resume_form"]["major"] == "计算机"
        assert result["resume_form"]["skills"]["count"] == 2
        # 六维分数与匹配链路同源（快照冻结 JSON）
        assert result["latest_snapshot"]["six_dim_scores"]["technical"] == 4
        assert result["latest_snapshot"]["description"] == "P4 工具测试快照"

    def test_profile_but_no_snapshot(self):
        user_id = asyncio.run(_seed_user(with_profile=True, with_snapshot=False))
        result = asyncio.run(user_snapshot.ainvoke({"user_id": user_id}))
        assert result["has_profile"] is True and result["has_snapshot"] is False
        assert "note" in result

    def test_unknown_user_returns_no_data_with_note(self):
        result = asyncio.run(user_snapshot.ainvoke({"user_id": 999999999}))
        assert result["has_profile"] is False and result["has_snapshot"] is False
        assert "note" in result


class TestZeroCostProperty:
    """C2 的硬要求是"**0 LLM 调用**"。这里不测行为、测**不变的构造性质**：
    模块源码里不许出现 LLM 网关 —— 一旦有人图省事在只读工具里调模型，这条立刻红。"""

    @pytest.mark.parametrize(
        "module_name",
        ["app.core.agent.tools.jobs", "app.core.agent.tools.snapshot"],
    )
    def test_readonly_tool_modules_never_import_the_gateway(self, module_name):
        import importlib
        from pathlib import Path

        source = Path(importlib.import_module(module_name).__file__).read_text(encoding="utf-8")
        assert "get_llm_gateway" not in source
        assert "app.core.llm" not in source, "只读工具不该依赖 LLM 层（C2：0 token）"


class TestAgentLoopIntegration:
    """经**真实的 agent 节点**跑一遍（节点 → 工具 → DB），而不是只调工具本身。"""

    def test_execute_tools_runs_real_job_search(self, seeded_jobs):
        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "job_search",
                            "args": {"keyword": _title("Java工程师")},
                            "id": "call_p4_1",
                        }
                    ],
                )
            ]
        }
        result = asyncio.run(
            execute_tools(
                state,
                config={"configurable": {"tools_by_name": {"job_search": job_search}}},
            )
        )
        content = result["messages"][0].content
        assert str(seeded_jobs["java"]) in content, f"工具结果里应带回岗位 id：{content[:200]}"
        assert result["next"] == "continue"

    def test_model_cannot_read_another_users_profile(self):
        """🔒 端到端隐私红线：模型在 tool_call 里填别人的 id 也读不到别人。

        这是 P4 收紧 `_inject_runtime_args` 的**唯一目的** —— 学生问"查一下用户 X 的画像"时，
        节点必须用**当前登录用户**覆盖掉模型填的 id。
        """
        victim_id = asyncio.run(_seed_user(with_profile=True, with_snapshot=True))
        attacker_id = asyncio.run(_seed_user(with_profile=False, with_snapshot=False))

        state = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "user_snapshot",
                            # 模型（或被注入诱导）试图读**别人**的画像
                            "args": {"user_id": victim_id},
                            "id": "call_p4_2",
                        }
                    ],
                )
            ]
        }
        result = asyncio.run(
            execute_tools(
                state,
                config={
                    "configurable": {
                        "tools_by_name": {"user_snapshot": user_snapshot},
                        # 运行时身份 = 攻击者本人
                        "user_id": attacker_id,
                    }
                },
            )
        )
        content = result["messages"][0].content
        # 拿到的是**攻击者自己**的（无画像）结果，而不是受害者的
        assert "has_profile" in content and "False" in content
        assert "计算机" not in content, "绝不能读到别人的简历内容"
