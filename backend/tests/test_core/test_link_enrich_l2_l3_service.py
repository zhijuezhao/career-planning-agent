"""L2 的服务层集成：模板复用（0 LLM）、每域一次、缓存与 LLM 层的一致性。

用 `httpx.MockTransport` 顶掉网络、用假 `learn_link_fields` 顶掉模型，
但**落库走真实库**（模板表与缓存表都是真表）—— 这一层要验的正是"接线"：
模板从库里读出来、命中计数写回去、学到的模板落库、以及缓存标记的规则。
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from app.core.link_enrich import service
from app.core.link_enrich.llm_extract import LearnResult
from app.core.link_enrich.service import EnrichConfig, enrich_rows
from app.core.link_enrich.templates import save_template
from app.core.llm.usage import TokenUsage
from app.domain.models.link_fetch_cache import LinkFetchCache
from app.domain.models.link_xpath_template import LinkXpathTemplate
from sqlalchemy import delete, select, text
from tests.conftest import test_session_factory

SALARY_XPATH = '//div[contains(concat(" ", normalize-space(@class), " "), \'job-salary\')]'
COMPANY_XPATH = '//span[contains(concat(" ", normalize-space(@class), " "), \'company-name\')]'

PAGE = """<html><head><title>Java 工程师</title></head><body>
  <div class="job-salary">20-30K</div>
  <span class="company-name">示例科技</span>
</body></html>"""

HTML = {"content-type": "text/html; charset=utf-8"}
RESOLVER_MAP: dict[str, list[str]] = {}


def _client(routes: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url not in routes:
            return httpx.Response(404, headers=HTML, content=b"nope")
        status, headers, body = routes[url]
        return httpx.Response(status, headers=headers, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _resolver(host: str) -> list[str]:
    if host not in RESOLVER_MAP:
        raise OSError(host)
    return RESOLVER_MAP[host]


def _config(**over) -> EnrichConfig:
    base = dict(enabled=True, max_rows=10, max_urls=10, timeout_s=5.0, concurrency=2)
    base.update(over)
    return EnrichConfig(**base)


@pytest.fixture
def fresh_domain() -> str:
    return f"y{uuid.uuid4().hex[:10]}.example.com"


@pytest.fixture(autouse=True)
def _clean_state():
    async def _clean() -> None:
        async with test_session_factory() as session:
            await session.execute(delete(LinkXpathTemplate).where(LinkXpathTemplate.domain.like("y%")))
            await session.execute(delete(LinkFetchCache).where(LinkFetchCache.url.like("%.example.com/%")))
            await session.commit()

    asyncio.run(_clean())
    yield
    asyncio.run(_clean())


def _url(domain: str, path: str = "/job/1") -> str:
    return f"https://{domain}{path}"


class TestTemplateReuse:
    def test_existing_template_fills_field_without_any_llm(self, fresh_domain):
        RESOLVER_MAP[fresh_domain] = ["93.184.216.34"]
        url = _url(fresh_domain)
        rows = [{"title": "Java", "company": None, "salary": None, "source_url": url}]

        async def _run():
            async with test_session_factory() as session:
                await save_template(session, fresh_domain, "salary", SALARY_XPATH)
                await session.commit()

                out, stats = await enrich_rows(
                    rows,
                    session=session,
                    config=_config(),
                    client=_client({url: (200, HTML, PAGE.encode())}),
                    resolver=_resolver,
                )
                await session.commit()
                assert out[0]["salary"] == "20-30K"
                assert stats["template_hits"] == 1
                assert stats["llm_calls"] == 0, "模板复用必须零 LLM"
                assert out[0]["enrich_stats"]["provenance"]["salary"].startswith("link:")
                return stats

        asyncio.run(_run())

    def test_template_hit_counter_is_written_back(self, fresh_domain):
        RESOLVER_MAP[fresh_domain] = ["93.184.216.34"]
        url = _url(fresh_domain)

        async def _run():
            async with test_session_factory() as session:
                await save_template(session, fresh_domain, "salary", SALARY_XPATH)
                await session.commit()
                before = (await session.execute(
                    select(LinkXpathTemplate.hit_count).where(LinkXpathTemplate.domain == fresh_domain)
                )).scalar_one()

                await enrich_rows(
                    [{"title": "J", "salary": None, "source_url": url}],
                    session=session, config=_config(),
                    client=_client({url: (200, HTML, PAGE.encode())}), resolver=_resolver,
                )
                await session.commit()
                after = (await session.execute(
                    select(LinkXpathTemplate.hit_count).where(LinkXpathTemplate.domain == fresh_domain)
                )).scalar_one()
                assert after == before + 1

        asyncio.run(_run())

    def test_unusable_template_records_miss_and_falls_through(self, fresh_domain):
        """模板指向本页不存在的 class → 取不到值 → 记一次 miss，且不影响其它 L1 字段。"""
        RESOLVER_MAP[fresh_domain] = ["93.184.216.34"]
        url = _url(fresh_domain)
        dead_xpath = '//div[contains(concat(" ", normalize-space(@class), " "), \'no-such-class\')]'

        async def _run():
            async with test_session_factory() as session:
                await save_template(session, fresh_domain, "salary", dead_xpath)
                await session.commit()
                out, stats = await enrich_rows(
                    [{"title": "J", "salary": None, "company": None, "source_url": url}],
                    session=session, config=_config(),
                    client=_client({url: (200, HTML, PAGE.encode())}), resolver=_resolver,
                )
                await session.commit()
                assert stats["template_hits"] == 0
                # 一条值得记住的边界：L1 **不从 DOM 里猜结构化字段**（连 og:site_name
                # 都不映射到 company）。抓 company/salary 这类"需要定位式"的字段本来
                # 就是 L2/L3 的职责 —— 所以这里两者都空是**正确行为**，不是缺陷。
                assert out[0].get("salary") is None
                assert out[0].get("company") is None
                miss = (await session.execute(
                    select(LinkXpathTemplate.miss_count).where(
                        LinkXpathTemplate.domain == fresh_domain,
                        LinkXpathTemplate.field == "salary",
                    )
                )).scalar_one()
                assert miss == 1, "模板取不到值必须记 miss（用于观测失效）"

        asyncio.run(_run())


class TestL3SwitchAndDomainGranularity:
    def test_llm_off_means_no_call_and_no_learn(self, fresh_domain, monkeypatch):
        RESOLVER_MAP[fresh_domain] = ["93.184.216.34"]
        url = _url(fresh_domain)
        calls: list[str] = []

        async def fake_learn(**kwargs):
            calls.append(kwargs["domain"])
            return LearnResult()

        monkeypatch.setattr(service, "learn_link_fields", fake_learn)

        async def _run():
            async with test_session_factory() as session:
                await enrich_rows(
                    [{"title": "J", "company": None, "source_url": url}],
                    session=session, config=_config(llm_enabled=False),
                    client=_client({url: (200, HTML, PAGE.encode())}), resolver=_resolver,
                )
                await session.commit()

        asyncio.run(_run())
        assert calls == [], "LLM 层关着就不该调用模型"

    def test_one_call_per_domain_not_per_url(self, fresh_domain, monkeypatch):
        """同一域的两个页面只学一次 —— 这是"省 token"的核心机制。"""
        RESOLVER_MAP[fresh_domain] = ["93.184.216.34"]
        url1, url2 = _url(fresh_domain, "/job/1"), _url(fresh_domain, "/job/2")
        calls: list[str] = []

        async def fake_learn(**kwargs):
            calls.append(kwargs["domain"])
            return LearnResult(fields={"salary": "20-30K"}, learned={"salary": SALARY_XPATH})

        monkeypatch.setattr(service, "learn_link_fields", fake_learn)

        async def _run():
            async with test_session_factory() as session:
                out, stats = await enrich_rows(
                    [
                        {"title": "A", "salary": None, "note": url1},
                        {"title": "B", "salary": None, "note": url2},
                    ],
                    session=session, config=_config(llm_enabled=True),
                    client=_client({
                        url1: (200, HTML, PAGE.encode()),
                        url2: (200, HTML, PAGE.encode()),
                    }),
                    resolver=_resolver,
                )
                await session.commit()
                assert calls == [fresh_domain], "同域只应学一次"
                assert stats["templates_learned"] == 1
                assert stats["llm_calls"] == 0  # 假 learn 没记账，真实实现会记
                assert out[0]["salary"] == "20-30K"

        asyncio.run(_run())

    def test_two_domains_get_two_calls(self, monkeypatch):
        d1, d2 = f"y{uuid.uuid4().hex[:8]}.example.com", f"y{uuid.uuid4().hex[:8]}.example.com"
        RESOLVER_MAP[d1] = RESOLVER_MAP[d2] = ["93.184.216.34"]
        u1, u2 = _url(d1), _url(d2)
        calls: list[str] = []

        async def fake_learn(**kwargs):
            calls.append(kwargs["domain"])
            return LearnResult()

        monkeypatch.setattr(service, "learn_link_fields", fake_learn)

        async def _run():
            async with test_session_factory() as session:
                await enrich_rows(
                    [{"title": "A", "note": u1}, {"title": "B", "note": u2}],
                    session=session, config=_config(llm_enabled=True),
                    client=_client({u1: (200, HTML, PAGE.encode()), u2: (200, HTML, PAGE.encode())}),
                    resolver=_resolver,
                )
                await session.commit()

        asyncio.run(_run())
        assert sorted(calls) == sorted([d1, d2])

    def test_budget_skip_reason_reaches_stats(self, fresh_domain, monkeypatch):
        """预算被挡时，原因要能出现在统计里（否则"为什么没学"无从排查）。

        真实的预算判断在 `learn_link_fields` 内部（由 `test_link_enrich_llm_extract.py`
        覆盖）；这里只验"原因字符串被正确汇总进 stats"这条接线。
        """
        RESOLVER_MAP[fresh_domain] = ["93.184.216.34"]
        url = _url(fresh_domain)

        async def fake_learn(**kwargs):
            return LearnResult(skipped="budget")

        monkeypatch.setattr(service, "learn_link_fields", fake_learn)

        async def _run():
            async with test_session_factory() as session:
                _out, stats = await enrich_rows(
                    [{"title": "J", "company": None, "source_url": url}],
                    session=session, config=_config(llm_enabled=True, max_llm_calls=1, max_tokens=1),
                    client=_client({url: (200, HTML, PAGE.encode())}), resolver=_resolver,
                )
                await session.commit()
                assert stats["llm_skipped"].get("budget") == 1

        asyncio.run(_run())

    def test_exhausted_llm_budget_sets_llm_flag_only(self, monkeypatch):
        """B3-3：LLM 预算用尽要**单独**点亮 `budget_llm_exceeded`。

        这里的假 `learn` 复刻真实实现的预算用法（调前 `can_call()`、调后 `spend()`），
        所以被挡时 `LlmBudget.blocked` 会置真 —— 这正是 `budget_llm_exceeded` 的来源。
        同时断言 `budget_url_exceeded` 仍为假：URL 预算没被碰过，两个标志必须分得开。
        """
        d1, d2 = f"y{uuid.uuid4().hex[:8]}.example.com", f"y{uuid.uuid4().hex[:8]}.example.com"
        RESOLVER_MAP[d1] = RESOLVER_MAP[d2] = ["93.184.216.34"]
        u1, u2 = _url(d1), _url(d2)

        async def fake_learn(**kwargs):
            budget = kwargs["budget"]
            if not budget.can_call():
                return LearnResult(skipped="budget")
            budget.spend(TokenUsage(10, 5, 15))
            return LearnResult()

        monkeypatch.setattr(service, "learn_link_fields", fake_learn)

        async def _run():
            async with test_session_factory() as session:
                _out, stats = await enrich_rows(
                    [
                        {"title": "A", "salary": None, "note": u1},
                        {"title": "B", "salary": None, "note": u2},
                    ],
                    session=session,
                    config=_config(llm_enabled=True, max_llm_calls=1),
                    client=_client({u1: (200, HTML, PAGE.encode()), u2: (200, HTML, PAGE.encode())}),
                    resolver=_resolver,
                )
                await session.commit()
                assert stats["llm_calls"] == 1
                assert stats["llm_skipped"].get("budget") == 1
                assert stats["budget_llm_exceeded"] is True
                assert stats["budget_url_exceeded"] is False
                assert stats["budget_exceeded"] is True      # 向后兼容
                assert stats["tokens_used"] == 15

        asyncio.run(_run())


class TestCacheConsistencyWithLlmLayer:
    def test_zero_cost_cache_is_not_reused_once_llm_layer_turns_on(self, fresh_domain, monkeypatch):
        """零成本层写的缓存（`llm=false`）在 LLM 层打开后必须重新抓，否则用户会以为没生效。"""
        RESOLVER_MAP[fresh_domain] = ["93.184.216.34"]
        url = _url(fresh_domain)
        monkeypatch.setattr(
            service, "learn_link_fields",
            lambda **kwargs: _noop_learn(),
        )

        async def _run():
            async with test_session_factory() as session:
                # 第一次：LLM 层关 → 缓存标记 llm=false
                _out1, stats1 = await enrich_rows(
                    [{"title": "J", "company": None, "source_url": url}],
                    session=session, config=_config(llm_enabled=False),
                    client=_client({url: (200, HTML, PAGE.encode())}), resolver=_resolver,
                )
                await session.commit()
                assert stats1["cache_hits"] == 0 and stats1["urls_fetched"] == 1

                # 第二次（同配置）：命中缓存
                _out2, stats2 = await enrich_rows(
                    [{"title": "J", "company": None, "source_url": url}],
                    session=session, config=_config(llm_enabled=False),
                    client=_client({}), resolver=_resolver,
                )
                assert stats2["cache_hits"] == 1 and stats2["urls_fetched"] == 0

                # 第三次：打开 LLM 层 → 旧缓存不被复用，重新抓一次
                _out3, stats3 = await enrich_rows(
                    [{"title": "J", "company": None, "source_url": url}],
                    session=session, config=_config(llm_enabled=True),
                    client=_client({url: (200, HTML, PAGE.encode())}), resolver=_resolver,
                )
                await session.commit()
                assert stats3["cache_hits"] == 0
                assert stats3["urls_fetched"] == 1

                # 第四次：这份缓存是 LLM 层写的 → 可以复用
                _out4, stats4 = await enrich_rows(
                    [{"title": "J", "company": None, "source_url": url}],
                    session=session, config=_config(llm_enabled=True),
                    client=_client({}), resolver=_resolver,
                )
                assert stats4["cache_hits"] == 1 and stats4["urls_fetched"] == 0

        asyncio.run(_run())


async def _noop_learn(**kwargs):
    return LearnResult()


def test_cleanup_left_nothing():
    async def _run():
        async with test_session_factory() as session:
            templates = (await session.execute(
                text("SELECT count(*) FROM link_xpath_templates WHERE domain LIKE 'y%'")
            )).scalar_one()
            assert templates == 0

    asyncio.run(_run())
