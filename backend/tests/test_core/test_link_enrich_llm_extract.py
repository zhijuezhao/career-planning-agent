"""L3（LLM 精简提取）的机制测试。

最重要的两条不是"能不能抽出字段"，而是**能不能拒绝模型**：

- `test_hallucinated_value_is_replaced_by_the_real_one`：模型说某字段的值是 X，
  但用它的 XPath 在本页取到的是 Y —— 必须采用 **Y**。值一律以"XPath 实际取到的
  文本"为准，绝不信模型抄的值。这是"不编造数据"的**机制**而非提示词请求。
- `test_xpath_outside_the_menu_is_rejected`：模型只能从候选菜单里挑。菜单之外自己
  编的表达式直接丢弃 —— 否则"省 token 的核心资产"（可复用定位式）会变成一堆
  跑不通、或者在本页碰巧能跑的表达式。

网络与模型都用假的（`get_llm_gateway` 被替换），落库用 NullPool 的真实库。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from app.core.link_enrich import llm_extract
from app.core.link_enrich.budget import LlmBudget
from app.core.link_enrich.llm_extract import learn_link_fields
from app.core.link_enrich.xpath import Candidate
from app.domain.models.link_xpath_template import LinkXpathTemplate
from lxml import html as lxml_html
from sqlalchemy import delete, select, text
from tests.conftest import test_session_factory

PAGE = """
<html><body>
  <div class="job-salary">20-30K</div>
  <span class="company-name">示例科技有限公司</span>
  <div><span class="label">工作地点</span><span class="value">深圳</span></div>
</body></html>
"""

SALARY_XPATH = '//div[contains(concat(" ", normalize-space(@class), " "), \'job-salary\')]'
COMPANY_XPATH = '//span[contains(concat(" ", normalize-space(@class), " "), \'company-name\')]'


def _tree():
    return lxml_html.document_fromstring(PAGE)


def _menu() -> list[Candidate]:
    """直接构造菜单：候选生成本身由 `test_link_enrich_xpath.py` 覆盖。"""
    return [
        Candidate(field="salary", xpath=SALARY_XPATH, preview="20-30K", score=5, matches=1),
        Candidate(field="company", xpath=COMPANY_XPATH, preview="示例科技有限公司", score=5, matches=1),
    ]


class _FakeGateway:
    def __init__(self, content: str, *, usage: dict | None = None, raises: Exception | None = None):
        self.content = content
        self.usage = usage if usage is not None else {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        self.raises = raises
        self.calls: list[dict] = []

    async def ainvoke(self, messages, function_key=None, **kwargs):
        self.calls.append({"messages": messages, "function_key": function_key, "kwargs": kwargs})
        if self.raises:
            raise self.raises
        return SimpleNamespace(content=self.content, usage_metadata=self.usage, response_metadata={})


@pytest.fixture
def domain() -> str:
    return f"x{uuid.uuid4().hex[:10]}.example.com"


@pytest.fixture(autouse=True)
def _cleanup_templates():
    async def _clean(prefix: str) -> None:
        async with test_session_factory() as session:
            await session.execute(delete(LinkXpathTemplate).where(LinkXpathTemplate.domain.like(prefix)))
            await session.commit()

    asyncio.run(_clean("x%"))
    yield
    asyncio.run(_clean("x%"))


def _install(monkeypatch, gateway: _FakeGateway) -> None:
    monkeypatch.setattr(llm_extract, "get_llm_gateway", lambda: gateway)


class TestHappyPath:
    def test_learns_fields_and_saves_templates(self, monkeypatch, domain):
        payload = {"fields": {
            "salary": {"value": "20-30K", "xpath": SALARY_XPATH},
            "company": {"value": "示例科技有限公司", "xpath": COMPANY_XPATH},
        }}
        gateway = _FakeGateway(json.dumps(payload, ensure_ascii=False))
        _install(monkeypatch, gateway)

        async def _run():
            async with test_session_factory() as session:
                result = await learn_link_fields(
                    domain=domain, tree=_tree(), text="薪资 20-30K", session=session,
                    budget=LlmBudget(), candidates=_menu(),
                )
                await session.commit()
                assert result.fields == {"salary": "20-30K", "company": "示例科技有限公司"}
                assert set(result.learned) == {"salary", "company"}
                assert result.usage.total_tokens == 120

                rows = (await session.execute(
                    select(LinkXpathTemplate).where(LinkXpathTemplate.domain == domain)
                )).scalars().all()
                assert {r.field for r in rows} == {"salary", "company"}
                assert all(r.hit_count >= 1 for r in rows)
                return len(gateway.calls)

        calls = asyncio.run(_run())
        assert calls == 1, "一次调用应当覆盖该域的所有字段（省 token 的关键）"

    def test_markdown_fenced_json_is_tolerated(self, monkeypatch, domain):
        body = json.dumps({"fields": {"salary": {"value": "20-30K", "xpath": SALARY_XPATH}}})
        gateway = _FakeGateway(f"```json\n{body}\n```")
        _install(monkeypatch, gateway)

        async def _run():
            result = await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=LlmBudget(), candidates=_menu(),
            )
            assert result.fields == {"salary": "20-30K"}

        asyncio.run(_run())


class TestRefusesToTrustTheModel:
    def test_hallucinated_value_is_replaced_by_the_real_one(self, monkeypatch, domain):
        # 模型"抄"错了值：采用 XPath 在本页真实取到的文本
        payload = {"fields": {"salary": {"value": "月薪十万起", "xpath": SALARY_XPATH}}}
        _install(monkeypatch, _FakeGateway(json.dumps(payload, ensure_ascii=False)))

        async def _run():
            result = await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=LlmBudget(), candidates=_menu(),
            )
            assert result.fields["salary"] == "20-30K"
            assert "月薪十万起" not in str(result.fields)

        asyncio.run(_run())

    def test_xpath_outside_the_menu_is_rejected(self, monkeypatch, domain):
        payload = {"fields": {"salary": {"value": "20-30K", "xpath": "//*[@id='whatever']"}}}
        _install(monkeypatch, _FakeGateway(json.dumps(payload)))

        async def _run():
            async with test_session_factory() as session:
                result = await learn_link_fields(
                    domain=domain, tree=_tree(), text="x", session=session,
                    budget=LlmBudget(), candidates=_menu(),
                )
                await session.commit()
                assert result.fields == {}
                assert any("非候选表达式" in r for r in result.rejected)
                rows = (await session.execute(
                    select(LinkXpathTemplate).where(LinkXpathTemplate.domain == domain)
                )).scalars().all()
                # 约束 3：没采用的表达式绝不落库
                assert rows == []

        asyncio.run(_run())

    def test_field_not_requested_is_ignored(self, monkeypatch, domain):
        payload = {"fields": {"salary": {"value": "20-30K", "xpath": SALARY_XPATH},
                              "secret_note": {"value": "x", "xpath": SALARY_XPATH}}}
        _install(monkeypatch, _FakeGateway(json.dumps(payload, ensure_ascii=False)))

        async def _run():
            result = await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=LlmBudget(), candidates=_menu(),
            )
            assert "secret_note" not in result.fields

        asyncio.run(_run())

    def test_xpath_that_yields_nothing_is_rejected(self, monkeypatch, domain):
        # 表达式在菜单里，但（比如页面变了）在本页取不到值 → 丢弃、不落库
        payload = {"fields": {"company": {"value": "某公司", "xpath": COMPANY_XPATH}}}
        _install(monkeypatch, _FakeGateway(json.dumps(payload, ensure_ascii=False)))

        async def _run():
            empty_tree = lxml_html.document_fromstring("<html><body><p>无</p></body></html>")
            result = await learn_link_fields(
                domain=domain, tree=empty_tree, text="x", session=None,
                budget=LlmBudget(), candidates=_menu(),
            )
            assert result.fields == {}
            assert any("取不到值" in r for r in result.rejected)

        asyncio.run(_run())


class TestSkips:
    def test_no_candidates_means_no_call(self, monkeypatch, domain):
        gateway = _FakeGateway("{}")
        _install(monkeypatch, gateway)

        async def _run():
            result = await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=LlmBudget(), candidates=[],
            )
            assert result.skipped == "no_candidates"
            assert result.fields == {}

        asyncio.run(_run())
        assert gateway.calls == [], "没有可复用的定位式可学，就不该花 token"

    def test_budget_exhausted_means_no_call(self, monkeypatch, domain):
        gateway = _FakeGateway("{}")
        _install(monkeypatch, gateway)

        async def _run():
            result = await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=LlmBudget(max_calls=1, calls=1), candidates=_menu(),
            )
            assert result.skipped == "budget"

        asyncio.run(_run())
        assert gateway.calls == []

    def test_gateway_failure_keeps_rule_results(self, monkeypatch, domain):
        _install(monkeypatch, _FakeGateway("", raises=RuntimeError("模型服务不可用")))

        async def _run():
            result = await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=LlmBudget(), candidates=_menu(),
            )
            assert result.skipped == "error"
            assert "模型服务不可用" in (result.error or "")
            assert result.fields == {}

        asyncio.run(_run())

    def test_unparsable_output_is_reported(self, monkeypatch, domain):
        _install(monkeypatch, _FakeGateway("我觉得薪资大概是 20-30K 吧"))  # 不是 JSON

        async def _run():
            result = await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=LlmBudget(), candidates=_menu(),
            )
            assert result.error == "模型输出不是合法 JSON"
            assert result.fields == {}

        asyncio.run(_run())


class TestBudgetAccounting:
    def test_usage_is_recorded_on_the_budget(self, monkeypatch, domain):
        payload = {"fields": {"salary": {"value": "20-30K", "xpath": SALARY_XPATH}}}
        _install(monkeypatch, _FakeGateway(json.dumps(payload), usage={"total_tokens": 321}))
        budget = LlmBudget(max_calls=5, max_tokens=1000)

        async def _run():
            await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=budget, candidates=_menu(),
            )

        asyncio.run(_run())
        assert budget.calls == 1
        assert budget.usage.total_tokens == 321
        assert not budget.exhausted

    def test_missing_usage_still_counts_the_call(self, monkeypatch, domain):
        payload = {"fields": {"salary": {"value": "20-30K", "xpath": SALARY_XPATH}}}
        _install(monkeypatch, _FakeGateway(json.dumps(payload), usage={}))
        budget = LlmBudget(max_calls=5)

        async def _run():
            await learn_link_fields(
                domain=domain, tree=_tree(), text="x", session=None,
                budget=budget, candidates=_menu(),
            )

        asyncio.run(_run())
        # 用量缺失时次数照记：否则供应商不回报用量就绕过了调用数闸门
        assert budget.calls == 1
        assert budget.usage.total_tokens == 0


class TestPromptShape:
    def test_prompt_carries_menu_and_text_but_not_html(self, monkeypatch, domain):
        payload = {"fields": {"salary": {"value": "20-30K", "xpath": SALARY_XPATH}}}
        gateway = _FakeGateway(json.dumps(payload))
        _install(monkeypatch, gateway)

        async def _run():
            await learn_link_fields(
                domain=domain, tree=_tree(), text="薪资 20-30K", session=None,
                budget=LlmBudget(), candidates=_menu(),
            )

        asyncio.run(_run())
        messages = gateway.calls[0]["messages"]
        user_content = messages[1]["content"]
        assert "<html>" not in user_content, "整页 HTML 绝不能进提示词（数据污染 + 白烧 token）"
        # 菜单以 `json.dumps` 嵌入 user 文本，所以 XPath 里的引号是**单层**转义的
        assert json.dumps(SALARY_XPATH)[1:-1] in user_content
        assert "job-salary" in user_content
        assert gateway.calls[0]["function_key"] == "job_link_extract"


def test_function_key_is_the_reserved_one():
    # 键名必须是 registry 里早已为 B3-2 预留的那一个，不要另起新键
    assert llm_extract.FUNCTION_KEY == "job_link_extract"


def test_cleanup_left_nothing_behind():
    async def _run():
        async with test_session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM link_xpath_templates WHERE domain LIKE 'x%'")
                )
            ).scalar_one()
            assert count == 0

    asyncio.run(_run())
