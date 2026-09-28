#!/usr/bin/env python
"""B3-2 真栈验收：L2 模板复用 + L3 **真实模型**学习（验证"同域第 2 页 0 调用"）。

为什么单独一个脚本
------------------
`test_core` 里 89 条 B3-2 用例把机制钉得很死，但它们**全部用假模型**。本脚本用
**真实网关**跑一次 L3，回答两个 mock 回答不了的问题：

1. 真实模型在我们这套提示词 + 候选菜单 + 后置校验下，**能不能产出可用的定位式**？
   （提示词写得好不好、菜单给得对不对，只有真模型能证伪）
2. 学到的模板在**同域的下一个页面**上是否真的 0 调用、且取到的是**那一页的值**？
   （这条是 B3-2 省 token 的全部意义）

第 2 条尤其重要：如果模板只是"记住了第一页的值"，那它就毫无价值 —— 所以脚本用
**结构相同、内容不同**的第二页来验，断言拿到的是**第二页自己的值**。

用法
----
    # 需要先开两个开关（都默认关）：
    #   根 .env 加 LINK_ENRICH_ENABLED=true、LINK_ENRICH_LLM_ENABLED=true
    #   docker compose up -d backend
    docker exec -e PYTHONPATH=/app/backend -e PYTHONIOENCODING=utf-8 -w /app/backend \
        career_backend python scripts/acceptance_link_enrich_llm.py

    # 附加：再抓一个**真实**招聘页试一次（可能因页面没有可定位字段而跳过，不算失败）
    ... python scripts/acceptance_link_enrich_llm.py --with-real-page

退出码：0 = 全通过；1 = 有失败项。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.core.link_enrich.budget import LlmBudget  # noqa: E402
from app.core.link_enrich.extract import parse_html  # noqa: E402
from app.core.link_enrich.fetch import fetch_page  # noqa: E402
from app.core.link_enrich.llm_extract import learn_link_fields  # noqa: E402
from app.core.link_enrich.service import EnrichConfig, enrich_rows  # noqa: E402
from app.core.link_enrich.xpath import build_xpath_candidates  # noqa: E402
from app.domain.models.link_fetch_cache import LinkFetchCache  # noqa: E402
from app.domain.models.link_xpath_template import LinkXpathTemplate  # noqa: E402
from app.infrastructure.database import async_session_factory  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

PREFIX = f"accllm{int(time.time())}"
DOMAIN = f"{PREFIX}.example.com"

#: 同一站点的两个页面：**结构完全相同、值不同**（岗位页换一条招聘就是这样）
PAGE_ONE = """<html><head><title>高级 Java 开发工程师</title></head><body>
<ul class="job-params">
  <li><span class="p-label">薪资</span><span class="p-value">25-40K·14薪</span></li>
  <li><span class="p-label">城市</span><span class="p-value">深圳市南山区</span></li>
  <li><span class="p-label">经验</span><span class="p-value">5-10年</span></li>
  <li><span class="p-label">学历</span><span class="p-value">本科及以上</span></li>
  <li><span class="p-label">行业</span><span class="p-value">互联网</span></li>
</ul>
<div class="job-detail-content">负责核心交易系统的设计与开发。</div>
</body></html>"""

PAGE_TWO = """<html><head><title>数据分析师</title></head><body>
<ul class="job-params">
  <li><span class="p-label">薪资</span><span class="p-value">18-25K</span></li>
  <li><span class="p-label">城市</span><span class="p-value">杭州市余杭区</span></li>
  <li><span class="p-label">经验</span><span class="p-value">3-5年</span></li>
  <li><span class="p-label">学历</span><span class="p-value">硕士</span></li>
  <li><span class="p-label">行业</span><span class="p-value">金融科技</span></li>
</ul>
<div class="job-detail-content">负责经营数据的指标体系与看板建设。</div>
</body></html>"""

#: 第二页上每个字段的**真实值**（用来证明模板拿到的是本页的值，不是记住了第一页）。
#: ⚠️ `city` 写的是**归一化后**的期望：合并层会过 `normalise_geo_name`（任务 4 定的
#: 「统一短名」口径），而它只剥最后一个行政后缀 —— `杭州市余杭区` → `杭州市余杭`。
#: 那是**既有**行为（表格里手写区级城市也一样），不是 B3-2 引入的，故此处按真实行为
#: 断言；已在计划文档里记为待裁决项。
PAGE_TWO_EXPECT = {
    "salary": "18-25K",
    "city": "杭州市余杭",
    "experience_requirement": "3-5年",
    "education_requirement": "硕士",
    "industry": "金融科技",
}


class Checker:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: object, detail: str = "") -> bool:
        passed = bool(ok)
        self.results.append((name, passed, detail))
        line = f"[{'PASS' if passed else 'FAIL'}] {name}"
        if detail:
            line += f" | {detail}"
        print(line, flush=True)
        return passed

    def note(self, message: str) -> None:
        print(f"[NOTE] {message}", flush=True)

    def summary(self) -> int:
        failed = [name for name, ok, _ in self.results if not ok]
        print(f"\n[SUMMARY] {len(self.results) - len(failed)}/{len(self.results)} 项通过", flush=True)
        if failed:
            print("[FAILED] " + "、".join(failed), file=sys.stderr)
            return 1
        return 0


def _client(body: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              content=body.encode("utf-8"))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _resolver(host: str) -> list[str]:
    if host != DOMAIN:
        raise OSError(host)
    return ["93.184.216.34"]


def _config(**over) -> EnrichConfig:
    base = dict(
        enabled=True, llm_enabled=True, max_rows=5, max_urls=5,
        timeout_s=10.0, concurrency=1, max_llm_calls=5, max_tokens=20_000,
    )
    base.update(over)
    return EnrichConfig(**base)


async def _cleanup() -> None:
    async with async_session_factory() as session:
        await session.execute(delete(LinkXpathTemplate).where(LinkXpathTemplate.domain == DOMAIN))
        await session.execute(delete(LinkFetchCache).where(LinkFetchCache.url.like(f"https://{DOMAIN}%")))
        await session.commit()


async def run_checks(with_real_page: bool) -> int:
    c = Checker()
    settings = get_settings()
    c.check("总开关已打开（LINK_ENRICH_ENABLED）", settings.link_enrich_enabled)
    c.check("LLM 层开关已打开（LINK_ENRICH_LLM_ENABLED）", settings.link_enrich_llm_enabled)
    if not (settings.link_enrich_enabled and settings.link_enrich_llm_enabled):
        print("\n请先在根 .env 里把两个开关设为 true 并 docker compose up -d backend", file=sys.stderr)
        return 1

    from app.core.llm.gateway import get_llm_gateway

    gateway = get_llm_gateway()
    c.note(
        f"网关（脚本进程从 env 构建，DB 路由快照在脚本里不加载）："
        f"models={gateway.list_models()} default={gateway.current_model}"
    )

    url1 = f"https://{DOMAIN}/job/1"
    url2 = f"https://{DOMAIN}/job/2"

    await _cleanup()
    try:
        # ── 第一页：真实模型学一次 ──────────────────────────────────────
        async with async_session_factory() as session:
            out1, stats1 = await enrich_rows(
                [{"title": "高级 Java 开发工程师", "company": None, "salary": None,
                  "city": None, "industry": None, "source_url": url1}],
                session=session, config=_config(),
                client=_client(PAGE_ONE), resolver=_resolver,
            )
            await session.commit()
            templates = (await session.execute(
                select(LinkXpathTemplate).where(LinkXpathTemplate.domain == DOMAIN)
            )).scalars().all()

        print("\n--- 第一页（真实模型调用）---")
        print(f"llm_calls={stats1['llm_calls']} tokens={stats1['tokens_used']} "
              f"templates_learned={stats1['templates_learned']} fields_filled={stats1['fields_filled']}")
        for row in templates:
            print(f"  学到 {row.field:24} ← {row.xpath}")

        c.check("真实模型至少学到一个定位式", stats1["templates_learned"] >= 1,
                f"learned={stats1['templates_learned']}")
        c.check("token 计量生效（用量被记录）", stats1["tokens_used"] > 0,
                f"tokens={stats1['tokens_used']}")
        c.check("第一页字段被补齐", bool(out1[0].get("salary")) or bool(out1[0].get("city")),
                f"salary={out1[0].get('salary')} city={out1[0].get('city')}")

        # ── 第二页：同域同结构 → 必须 0 调用，且取到**本页**的值 ──────────
        async with async_session_factory() as session:
            out2, stats2 = await enrich_rows(
                [{"title": "数据分析师", "company": None, "salary": None, "city": None,
                  "experience_requirement": None, "education_requirement": None,
                  "industry": None, "source_url": url2}],
                session=session, config=_config(),
                client=_client(PAGE_TWO), resolver=_resolver,
            )
            await session.commit()

        print("\n--- 第二页（应走模板，0 调用）---")
        print(f"llm_calls={stats2['llm_calls']} template_hits={stats2['template_hits']} "
              f"cache_hits={stats2['cache_hits']}")
        for field, expected in PAGE_TWO_EXPECT.items():
            got = out2[0].get(field)
            print(f"  {field:24} 期望={expected!r:18} 实得={got!r}")

        c.check("第二页零 LLM 调用", stats2["llm_calls"] == 0, f"llm_calls={stats2['llm_calls']}")
        c.check("第二页命中模板", stats2["template_hits"] >= 1, f"hits={stats2['template_hits']}")
        # 还有 1~2 个字段（如 company/level）这一页根本没有对应元素 → 候选菜单为空 →
        # 按设计**不发请求**（没有可复用的定位式可学，花 token 只换一次性的值不划算）
        c.note(f"第二页 L3 跳过原因统计：{stats2.get('llm_skipped')}")
        correct = [f for f, exp in PAGE_TWO_EXPECT.items() if out2[0].get(f) == exp]
        c.check(
            "模板取到的是**第二页自己的值**（不是记住第一页）",
            len(correct) == len(PAGE_TWO_EXPECT),
            f"正确 {len(correct)}/{len(PAGE_TWO_EXPECT)}：{sorted(correct)}",
        )

        # ── 可选：真实抓一个页面再试一次（不作为通过条件）────────────────
        if with_real_page:
            c.note("附加：抓一个真实招聘页看候选质量（不参与通过率）")
            real_url = "https://jobs.lever.co/leverdemo/58db3f8e-b108-47d1-9e6e-87a1712497cd"
            outcome = await fetch_page(real_url, timeout=25.0)
            if not outcome.ok or not outcome.body:
                c.note(f"真实页面抓取失败：{outcome.error}")
            else:
                tree = parse_html(outcome.body)
                menu = build_xpath_candidates(tree)
                c.note(f"真实页面候选数={len(menu)} 字段={sorted({m.field for m in menu})}")
                async with async_session_factory() as session:
                    result = await learn_link_fields(
                        domain="jobs.lever.co", tree=tree, text="", session=session,
                        budget=LlmBudget(max_calls=2, max_tokens=8000), candidates=menu,
                    )
                    await session.commit()
                    await session.execute(
                        delete(LinkXpathTemplate).where(LinkXpathTemplate.domain == "jobs.lever.co")
                    )
                    await session.commit()
                c.note(
                    f"真实页面学习结果：learned={result.learned} skipped={result.skipped} "
                    f"error={result.error} tokens={result.usage.total_tokens}"
                )
    finally:
        await _cleanup()

    return c.summary()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="B3-2 链接富化 LLM 层真栈验收")
    parser.add_argument("--with-real-page", action="store_true", help="附加真实页面探测（不计通过率）")
    args = parser.parse_args(argv)
    return asyncio.run(run_checks(args.with_real_page))


if __name__ == "__main__":
    raise SystemExit(main())
