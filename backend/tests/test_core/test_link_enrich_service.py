"""B3-1 抓取与编排：SSRF 逐跳复检、有界读取、预算闸门、确定性合并、缓存。

网络全部用 `httpx.MockTransport` 顶掉 —— 单测不该依赖外网（否则别人机器上跑就是
一片红）。真实的出网抓取放在验收阶段单独做一次，作为"这条链路真的能通"的证据。

这里最要紧的一条是 `test_redirect_to_private_address_is_blocked`：
守卫只认第一个 URL，如果抓取层用 `follow_redirects=True`，一个公网地址 302 到
`169.254.169.254` 就能拿到云元数据 —— 那守卫等于摆设。
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
from app.core.link_enrich.fetch import CACHE_VERSION, fetch_page, load_cache
from app.core.link_enrich.service import EnrichConfig, enrich_rows, fetch_one
from tests.conftest import test_session_factory


async def _drop_cache(session, url: str) -> None:
    """清掉本用例写入的缓存行（`url_hash` 是确定性的，随机域名保证互不干扰）。"""
    from app.core.link_enrich.urls import url_hash
    from app.domain.models.link_fetch_cache import LinkFetchCache
    from sqlalchemy import delete

    await session.execute(delete(LinkFetchCache).where(LinkFetchCache.url_hash == url_hash(url)))
    await session.commit()


#: 假 DNS：所有 example.com 都解析到公网 IP（不碰真实 DNS）
PUBLIC_RESOLVER_MAP = {
    "jobs.example.com": ["93.184.216.34"],
    "a.example.com": ["93.184.216.34"],
    "b.example.com": ["93.184.216.34"],
}


async def _resolver(host: str) -> list[str]:
    if host not in PUBLIC_RESOLVER_MAP:
        raise OSError(f"unknown host {host}")
    return PUBLIC_RESOLVER_MAP[host]


JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@type":"JobPosting","title":"Java 开发","hiringOrganization":{"name":"示例科技"},
 "jobLocation":{"address":{"addressLocality":"深圳市","addressRegion":"广东省"}},
 "baseSalary":{"currency":"CNY","value":{"minValue":20000,"maxValue":30000,"unitText":"MONTH"}},
 "description":"<p>负责核心系统</p>"}
</script></head><body><p>x</p></body></html>"""

OG_PAGE = """<html><head><meta property="og:title" content="产品经理" />
<meta property="og:description" content="负责需求分析" /></head>
<body><p>x</p></body></html>"""

#: B3-3 用：**只有 og:title、正文为空**的页面。`title` 刻意不可填（它是去重键，
#: 见 `merge.py:25`），而 text 层取不出任何正文（`<body>` 空）→ 页面抓取成功
#: （`ok = bool(fields or text)` 为真）但**一个字段都补不到**。
#: 这正是 `rows_enriched` 与 `rows_fields_filled` 必须分开的原因。
#: ⚠️ 别往 body 里塞任何文字：哪怕一个 `<p>x</p>` 都会让 text 层产出
#: `description`（可填），用例就失去意义了（2026-09-29 实测踩到）。
TITLE_ONLY_PAGE = """<html><head><meta property="og:title" content="产品经理" /></head>
<body></body></html>"""


def _client(routes: dict, *, raise_on: str | None = None) -> httpx.AsyncClient:
    """把 URL → (status, headers, body) 的映射做成假 HTTP 客户端。"""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if raise_on and url == raise_on:
            raise httpx.ConnectTimeout("simulated timeout")
        if url not in routes:
            return httpx.Response(404, headers={"content-type": "text/html"}, content=b"nope")
        status, headers, body = routes[url]
        return httpx.Response(status, headers=headers, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


HTML = {"content-type": "text/html; charset=utf-8"}


class TestFetchPage:
    async def test_fetches_html(self):
        client = _client({"https://jobs.example.com/1": (200, HTML, b"<html><body>hi</body></html>")})
        outcome = await fetch_page("https://jobs.example.com/1", client=client, resolver=_resolver)
        assert outcome.ok and outcome.status_code == 200
        assert b"hi" in outcome.body

    async def test_http_error_is_reported_not_raised(self):
        client = _client({})
        outcome = await fetch_page("https://jobs.example.com/gone", client=client, resolver=_resolver)
        assert not outcome.ok and "404" in outcome.error

    async def test_non_html_content_type_is_rejected(self):
        client = _client({"https://jobs.example.com/x.png": (200, {"content-type": "image/png"}, b"\x89PNG")})
        outcome = await fetch_page("https://jobs.example.com/x.png", client=client, resolver=_resolver)
        assert not outcome.ok and "非网页内容" in outcome.error

    async def test_redirect_is_followed(self):
        client = _client(
            {
                "https://a.example.com/old": (302, {"location": "https://b.example.com/new"}, b""),
                "https://b.example.com/new": (200, HTML, b"<html><body>final</body></html>"),
            }
        )
        outcome = await fetch_page("https://a.example.com/old", client=client, resolver=_resolver)
        assert outcome.ok
        assert outcome.final_url == "https://b.example.com/new"
        assert b"final" in outcome.body

    async def test_relative_redirect_location_resolved(self):
        client = _client(
            {
                "https://a.example.com/dir/old": (301, {"location": "/new"}, b""),
                "https://a.example.com/new": (200, HTML, b"<html><body>ok</body></html>"),
            }
        )
        outcome = await fetch_page("https://a.example.com/dir/old", client=client, resolver=_resolver)
        assert outcome.ok and outcome.final_url == "https://a.example.com/new"

    async def test_redirect_to_private_address_is_blocked(self):
        # 关键用例：第一个 URL 是公网，302 指向云元数据 → 必须在第二跳被拦下。
        # 用 follow_redirects=True 的实现会在这里静默拿到内网响应。
        client = _client(
            {"https://a.example.com/go": (302, {"location": "http://169.254.169.254/latest/"}, b"")}
        )
        outcome = await fetch_page("https://a.example.com/go", client=client, resolver=_resolver)
        assert not outcome.ok
        assert outcome.blocked_reason
        assert "链路本地" in outcome.blocked_reason

    async def test_redirect_to_container_service_is_blocked(self):
        client = _client(
            {"https://a.example.com/go": (302, {"location": "http://redis:6379/"}, b"")}
        )
        outcome = await fetch_page("https://a.example.com/go", client=client, resolver=_resolver)
        assert not outcome.ok and outcome.blocked_reason

    async def test_too_many_redirects(self):
        client = _client(
            {"https://a.example.com/loop": (302, {"location": "https://a.example.com/loop"}, b"")}
        )
        outcome = await fetch_page(
            "https://a.example.com/loop", client=client, resolver=_resolver, max_redirects=2
        )
        assert not outcome.ok and "重定向" in outcome.error

    async def test_blocks_private_target_before_requesting(self):
        client = _client({})
        outcome = await fetch_page(
            "http://169.254.169.254/latest/meta-data/", client=client, resolver=_resolver
        )
        assert not outcome.ok and outcome.blocked_reason

    async def test_oversized_body_is_truncated_and_flagged(self):
        big = b"<html><body>" + b"A" * 5000 + b"</body></html>"
        client = _client({"https://jobs.example.com/big": (200, HTML, big)})
        outcome = await fetch_page(
            "https://jobs.example.com/big", client=client, resolver=_resolver, max_bytes=1000
        )
        assert outcome.ok and outcome.truncated
        assert len(outcome.body) <= 1001

    async def test_timeout_is_reported_not_raised(self):
        client = _client({}, raise_on="https://jobs.example.com/slow")
        outcome = await fetch_page("https://jobs.example.com/slow", client=client, resolver=_resolver)
        assert not outcome.ok and "超时" in outcome.error


CFG = EnrichConfig(enabled=True, max_rows=10, max_urls=10, timeout_s=5.0, concurrency=2)


class TestEnrichRows:
    async def test_disabled_is_a_noop(self):
        rows = [{"title": "A", "source_url": "https://jobs.example.com/1"}]
        out, stats = await enrich_rows(rows, config=EnrichConfig(enabled=False))
        assert stats["enabled"] is False
        assert out[0] == rows[0]          # 数据一字未动
        assert "enrich_stats" not in out[0]

    async def test_fills_empty_fields_and_records_stats(self):
        rows = [{"title": "Java 开发", "company": None, "source_url": "https://jobs.example.com/1"}]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        out, stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)

        assert out[0]["company"] == "示例科技"
        assert out[0]["city"] == "深圳"          # 地域已归一化为短名
        assert out[0]["region"] == "广东"
        assert out[0]["salary"] == "20000-30000 CNY /月"
        assert stats["rows_enriched"] == 1
        assert stats["jsonld_hits"] == 1
        assert stats["urls_fetched"] == 1
        assert stats["fields_filled"]["company"] == 1

    async def test_does_not_mutate_input_rows(self):
        rows = [{"title": "Java", "company": None, "source_url": "https://jobs.example.com/1"}]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert rows[0]["company"] is None   # 原始行保持不动，便于对照

    async def test_form_value_wins_and_conflict_is_reported(self):
        rows = [{"title": "Java", "salary": "15-18K", "source_url": "https://jobs.example.com/1"}]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        out, stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert out[0]["salary"] == "15-18K"      # 表格值优先
        assert stats["conflicts_count"] == 1
        assert stats["conflicts"][0]["field"] == "salary"
        assert out[0]["enrich_stats"]["conflicts"][0]["form"] == "15-18K"

    async def test_source_url_is_filled_when_missing(self):
        # 链接写在"备注"列里时，官方 source_url 列应被补上（供岗位来源展示）
        rows = [{"title": "Java", "company": None, "备注": "见 https://jobs.example.com/1"}]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        out, _ = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert out[0]["source_url"] == "https://jobs.example.com/1"

    async def test_multiple_urls_first_wins_second_becomes_conflict(self):
        rows = [{"title": "Java", "company": None, "note": "https://a.example.com/1 https://b.example.com/2"}]
        client = _client(
            {
                "https://a.example.com/1": (200, HTML, JSONLD_PAGE),
                "https://b.example.com/2": (200, HTML, OG_PAGE),
            }
        )
        out, stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert out[0]["company"] == "示例科技"     # 第一个 URL 说了算，结果可复现
        assert out[0]["enrich_stats"]["pages"][0]["url"] == "https://a.example.com/1"

    async def test_row_without_url_is_untouched(self):
        rows = [{"title": "没有链接", "company": None}]
        out, stats = await enrich_rows(rows, config=CFG, client=_client({}), resolver=_resolver)
        assert out[0] == rows[0]
        assert stats["rows_enriched"] == 0
        assert stats["urls_unique"] == 0

    async def test_blocked_url_is_recorded_not_fatal(self):
        rows = [{"title": "Java", "company": None, "source_url": "http://169.254.169.254/x"}]
        out, stats = await enrich_rows(rows, config=CFG, client=_client({}), resolver=_resolver)
        assert stats["rows_enriched"] == 0
        assert stats["blocked"][0]["reason"]

    async def test_unreachable_url_is_recorded_not_fatal(self):
        rows = [{"title": "Java", "company": None, "source_url": "https://jobs.example.com/gone"}]
        out, stats = await enrich_rows(rows, config=CFG, client=_client({}), resolver=_resolver)
        assert stats["rows_enriched"] == 0
        assert stats["errors"]


class TestBudgetGates:
    async def test_max_rows_limits_how_many_rows_are_enriched(self):
        rows = [
            {"title": f"岗位{i}", "company": None, "source_url": "https://jobs.example.com/1"}
            for i in range(4)
        ]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        out, stats = await enrich_rows(
            rows, config=EnrichConfig(enabled=True, max_rows=2, max_urls=10), client=client, resolver=_resolver
        )
        assert stats["rows_enriched"] == 2
        assert stats["rows_budget_skipped"] == 2
        assert stats["budget_exceeded"] is True
        assert out[3]["company"] is None       # 超预算的行保持原样，不做半成品

    async def test_max_urls_limits_unique_fetches(self):
        rows = [
            {"title": "A", "note": "https://a.example.com/1 https://b.example.com/2"},
        ]
        client = _client(
            {
                "https://a.example.com/1": (200, HTML, JSONLD_PAGE),
                "https://b.example.com/2": (200, HTML, OG_PAGE),
            }
        )
        _, stats = await enrich_rows(
            rows, config=EnrichConfig(enabled=True, max_rows=5, max_urls=1), client=client, resolver=_resolver
        )
        assert stats["urls_unique"] == 1
        assert stats["budget_exceeded"] is True

    async def test_url_budget_flag_is_split_from_llm_budget(self):
        """B3-3：URL 上限只该点亮 `budget_url_exceeded`，不能冒充 LLM 预算。

        `budget_exceeded` 保留为两者的"或"，所以它单独看**说不清撞了哪个** ——
        这正是本次要拆开的原因。
        """
        rows = [
            {"title": f"岗位{i}", "company": None, "source_url": "https://jobs.example.com/1"}
            for i in range(4)
        ]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        _out, stats = await enrich_rows(
            rows,
            config=EnrichConfig(enabled=True, max_rows=2, max_urls=10),
            client=client,
            resolver=_resolver,
        )
        assert stats["budget_url_exceeded"] is True
        assert stats["budget_llm_exceeded"] is False
        assert stats["budget_exceeded"] is True

    async def test_max_urls_trip_sets_url_budget_flag(self):
        rows = [{"title": "A", "note": "https://a.example.com/1 https://b.example.com/2"}]
        client = _client(
            {
                "https://a.example.com/1": (200, HTML, JSONLD_PAGE),
                "https://b.example.com/2": (200, HTML, OG_PAGE),
            }
        )
        _out, stats = await enrich_rows(
            rows,
            config=EnrichConfig(enabled=True, max_rows=5, max_urls=1),
            client=client,
            resolver=_resolver,
        )
        assert stats["budget_url_exceeded"] is True
        assert stats["budget_llm_exceeded"] is False

    async def test_no_budget_trip_leaves_both_flags_false(self):
        rows = [{"title": "Java", "company": None, "source_url": "https://jobs.example.com/1"}]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        _out, stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert stats["budget_url_exceeded"] is False
        assert stats["budget_llm_exceeded"] is False
        assert stats["budget_exceeded"] is False

    async def test_same_url_in_two_rows_is_fetched_once(self):
        rows = [
            {"title": "A", "company": None, "source_url": "https://jobs.example.com/1"},
            {"title": "B", "company": None, "source_url": "https://jobs.example.com/1"},
        ]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        out, stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert stats["urls_unique"] == 1
        assert stats["urls_fetched"] == 1        # 同一页只抓一次
        assert out[0]["company"] == "示例科技" and out[1]["company"] == "示例科技"

    async def test_results_are_deterministic(self):
        rows = [{"title": "Java", "company": None, "source_url": "https://jobs.example.com/1"}]
        runs = []
        for _ in range(2):
            client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
            out, _stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
            runs.append(out[0])
        assert runs[0] == runs[1]


class TestFieldsFilledAccounting:
    """B3-3：`rows_enriched`（抓到页）与 `rows_fields_filled`（真补到字段）不是一回事。

    抓取成功 ≠ 富化有产出：页面可能只有 `title`（刻意不可填）或什么都没有。
    只报 `rows_enriched` 会让人误以为"这批数据补上了"，所以两个数都要记。
    """

    async def test_page_with_only_unfillable_title_counts_as_enriched_but_not_filled(self):
        rows = [{"title": "Java", "company": None, "source_url": "https://jobs.example.com/1"}]
        client = _client({"https://jobs.example.com/1": (200, HTML, TITLE_ONLY_PAGE)})
        _out, stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert stats["urls_fetched"] == 1
        assert stats["rows_enriched"] == 1, "页面确实抓到了"
        assert stats["rows_fields_filled"] == 0, "但一个字段都没补到"
        assert stats["fields_filled"] == {}

    async def test_row_with_fillable_field_counts_as_filled(self):
        rows = [{"title": "Java", "company": None, "source_url": "https://jobs.example.com/1"}]
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        out, stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert stats["rows_enriched"] == 1
        assert stats["rows_fields_filled"] == 1
        assert out[0]["company"] == "示例科技"

    async def test_filled_rows_never_exceed_enriched_rows(self):
        """不变式：补到字段的行必然是"抓到过页"的行 —— 两个数一起看才有意义。"""
        rows = [
            {"title": "A", "company": None, "source_url": "https://jobs.example.com/1"},
            {"title": "B", "company": None, "source_url": "https://jobs.example.com/2"},
        ]
        client = _client(
            {
                "https://jobs.example.com/1": (200, HTML, JSONLD_PAGE),
                "https://jobs.example.com/2": (200, HTML, TITLE_ONLY_PAGE),
            }
        )
        _out, stats = await enrich_rows(rows, config=CFG, client=client, resolver=_resolver)
        assert stats["rows_enriched"] == 2
        assert stats["rows_fields_filled"] == 1
        assert stats["rows_fields_filled"] <= stats["rows_enriched"]


class TestCache:
    """缓存用例用「sync 测试 + 单个 `asyncio.run` + NullPool」而不是 `db_session` 夹具。

    原因：`pytest.ini` 设了 `asyncio_default_fixture_loop_scope = session`，异步夹具跑在
    **session 循环**、测试体跑在 **function 循环**；而应用引擎是**池化**的
    （`database.py` `pool_size=20`），连接一旦建立就绑死在某个循环上。夹具里碰过连接、
    或前一个用例留下的池化连接被复用时，就会 `got Future attached to a different loop`
    （2026-09-27 实测）。同一个 `asyncio.run` 里从头做到尾则没有跨循环。
    """

    def test_round_trip_uses_cache_on_second_run(self):
        host = f"c{uuid.uuid4().hex[:8]}.example.com"
        url = f"https://{host}/job/1"
        PUBLIC_RESOLVER_MAP[host] = ["93.184.216.34"]
        rows = [{"title": "Java", "company": None, "source_url": url}]

        async def _run() -> None:
            async with test_session_factory() as session:
                try:
                    client = _client({url: (200, HTML, JSONLD_PAGE)})
                    out1, stats1 = await enrich_rows(
                        rows, session=session, config=CFG, client=client, resolver=_resolver
                    )
                    await session.commit()
                    assert stats1["cache_hits"] == 0 and stats1["urls_fetched"] == 1
                    assert out1[0]["company"] == "示例科技"

                    # 第二次：同一 URL，HTTP 客户端故意只回 404 —— 命中缓存就不该发请求
                    client2 = _client({})
                    out2, stats2 = await enrich_rows(
                        rows, session=session, config=CFG, client=client2, resolver=_resolver
                    )
                    assert stats2["cache_hits"] == 1
                    assert stats2["urls_fetched"] == 0
                    assert out2[0]["company"] == "示例科技"
                finally:
                    PUBLIC_RESOLVER_MAP.pop(host, None)
                    await _drop_cache(session, url)

        asyncio.run(_run())

    def test_payload_carries_cache_version(self):
        host = f"v{uuid.uuid4().hex[:8]}.example.com"
        url = f"https://{host}/job/1"
        PUBLIC_RESOLVER_MAP[host] = ["93.184.216.34"]

        async def _run() -> None:
            async with test_session_factory() as session:
                try:
                    client = _client({url: (200, HTML, JSONLD_PAGE)})
                    await enrich_rows(
                        [{"title": "J", "company": None, "source_url": url}],
                        session=session, config=CFG, client=client, resolver=_resolver,
                    )
                    await session.commit()
                    cached = await load_cache(session, url)
                    # 版本号必须落库：否则提取口径升级后，老缓存会被新代码按新规则解读
                    assert cached is not None and cached["v"] == CACHE_VERSION
                finally:
                    PUBLIC_RESOLVER_MAP.pop(host, None)
                    await _drop_cache(session, url)

        asyncio.run(_run())


class TestFetchOne:
    async def test_returns_fields_and_text(self):
        client = _client({"https://jobs.example.com/1": (200, HTML, JSONLD_PAGE)})
        result = await fetch_one(
            "https://jobs.example.com/1", config=CFG, client=client, resolver=_resolver
        )
        assert result["success"] is True
        assert result["fields"]["company"] == "示例科技"
        assert result["domain"] == "jobs.example.com"
        assert result["blocked_reason"] is None

    async def test_reports_blocked_reason(self):
        result = await fetch_one(
            "http://169.254.169.254/x", config=CFG, client=_client({}), resolver=_resolver
        )
        assert result["success"] is False
        assert result["blocked_reason"]
