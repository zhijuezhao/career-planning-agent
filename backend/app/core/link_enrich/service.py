"""Link Enrich v1（B3-1）编排层：发现 → 抓取 → 提取 → 合并 → 统计。**零 LLM**。

## 一次调用的完整流程

1. **逐行发现 URL**（L0，纯本地正则），按 dtype 只扫字符串单元格；
2. **缓存命中**：命中 `link_fetch_cache` 的 URL 直接复用提取结果，不发请求；
3. **并发抓取**未命中的 URL（信号量限流）→ L1 提取 → 写缓存；
4. **逐行按 URL 顺序合并**（`merge.py`，表格值优先）；
5. 产出聚合统计（可直接写进 `data_import_jobs.stats.link_enrich`）。

## 两个并发相关的约束

- **`AsyncSession` 不能并发使用**。所以"读缓存 / 写缓存"这两段 DB 操作**串行**，
  只有中间的网络抓取是并发的。别图省事把 DB 调用塞进 `gather` —— 那会触发
  SQLAlchemy 的 "concurrent operations are not permitted"。
- 抓取结果**先全部拿到、再按行序合并**（而不是"谁先回来谁先合并"）。HTTP 完成
  顺序是不确定的，若边完成边合并，同一批数据两次运行可能得到不同的字段值 ——
  导入结果必须可复现。

## 预算闸门（§4.5）

行数与 URL 数都有上限，超限只**截断并标 `budget_exceeded`**，不做部分失败：
宁可少富化几行，也不能让一次误上传把外部站点刷爆（也避免被目标站封 IP）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from app.config import get_settings
from app.core.link_enrich.budget import LlmBudget
from app.core.link_enrich.extract import extract_page, parse_html
from app.core.link_enrich.fetch import (
    CACHE_VERSION,
    FetchOutcome,
    fetch_page,
    load_cache,
    store_cache,
)
from app.core.link_enrich.llm_extract import learn_link_fields
from app.core.link_enrich.merge import merge_link_fields
from app.core.link_enrich.safety import resolve_host
from app.core.link_enrich.templates import load_templates, record_outcome
from app.core.link_enrich.urls import discover_row_urls, domain_of, group_by_domain
from app.core.link_enrich.urls import url_hash as make_url_hash
from app.core.link_enrich.xpath import EXTRACTABLE_FIELDS, apply_xpath

#: 统计里各类列表的长度上限（JSONB 是要落库的，不能无限增长）
MAX_LIST = 20

#: 每行最多抓几个链接（一个"备注"格里塞十几条链接时兜底）
MAX_URLS_PER_ROW = 3


@dataclass
class EnrichConfig:
    """一次富化的配置快照（从 `Settings` 取，便于测试直接构造）。"""

    enabled: bool = False
    max_rows: int = 20
    max_urls: int = 30
    timeout_s: float = 20.0
    concurrency: int = 4
    cache_ttl_hours: int = 168
    max_bytes: int = 2_000_000
    max_text_chars: int = 4000
    max_redirects: int = 5
    #: B3-2：L3（LLM 精简提取）独立开关，默认关（用户裁决 A）
    llm_enabled: bool = False
    max_llm_calls: int = 10
    max_tokens: int = 50_000

    @classmethod
    def from_settings(cls, settings=None) -> EnrichConfig:
        s = settings or get_settings()
        return cls(
            enabled=bool(s.link_enrich_enabled),
            max_rows=int(s.link_enrich_max_rows),
            max_urls=int(s.link_enrich_max_urls),
            timeout_s=float(s.link_enrich_timeout_s),
            concurrency=max(1, int(s.link_enrich_concurrency)),
            cache_ttl_hours=int(s.link_enrich_cache_ttl_hours),
            max_bytes=int(s.link_enrich_max_bytes),
            max_text_chars=int(s.link_enrich_max_text_chars),
            max_redirects=int(s.link_enrich_max_redirects),
            llm_enabled=bool(s.link_enrich_llm_enabled),
            max_llm_calls=int(s.link_enrich_max_llm_calls),
            max_tokens=int(s.link_enrich_max_tokens),
        )


def _bounded(bucket: list, item: Any) -> None:
    if len(bucket) < MAX_LIST:
        bucket.append(item)


@dataclass
class _UrlPayload:
    """一个 URL 的提取结果（缓存命中或现抓）。"""

    url: str
    fields: dict = field(default_factory=dict)
    tier_of: dict = field(default_factory=dict)
    tiers_hit: tuple = ()
    text: str = ""
    from_cache: bool = False
    ok: bool = False
    error: str | None = None
    blocked_reason: str | None = None
    truncated: bool = False
    #: 该 URL 的原始响应体（**仅现抓的**有；缓存命中的没有，L2/L3 只对现抓的页跑）
    body: bytes | None = None
    #: 本页是否已经过 L2/L3（XPath 模板 / LLM 学习）。写进缓存用于"层升级后不复用旧缓存"
    llm_layer: bool = False

    def to_cache(self) -> dict:
        return {
            "v": CACHE_VERSION,
            "url": self.url,
            "domain": domain_of(self.url),
            "fields": self.fields,
            "tier_of": self.tier_of,
            "tiers_hit": list(self.tiers_hit),
            "text": self.text,
            "truncated": self.truncated,
            # L2/L3 的成果也进缓存（fields 里已含），并标记"这一份是带 LLM 层的"。
            # 规则：**零成本层写的缓存不会被 LLM 层复用** —— 否则用户刚打开 LLM 开关
            # 却因为缓存命中而看不到任何变化，会以为功能没生效（见 `enrich_rows` 读缓存段）。
            "llm": self.llm_layer,
        }

    @classmethod
    def from_cached_payload(cls, url: str, payload: dict) -> _UrlPayload:
        """⚠️ **方法名绝不能叫 `from_cache`**：那会与下面的同名字段撞车 ——
        dataclass 先给 `from_cache` 设了类属性默认值，随后这个 `def` 又把它**覆盖成
        绑定方法**，于是 `payload.from_cache` 永远是真值（2026-09-27 实测：
        统计里 `urls_fetched` 恒为 0，而字段却填得好好的）。"""
        return cls(
            url=url,
            fields=payload.get("fields") or {},
            tier_of=payload.get("tier_of") or {},
            tiers_hit=tuple(payload.get("tiers_hit") or ()),
            text=payload.get("text") or "",
            from_cache=True,
            ok=bool(payload.get("fields") or payload.get("text")),
            llm_layer=bool(payload.get("llm")),
        )


async def _apply_templates_and_llm(
    payloads: dict[str, _UrlPayload],
    *,
    cfg: EnrichConfig,
    session,
    budget: LlmBudget,
    stats: dict,
    now: datetime | None,
) -> None:
    """L2（模板复用，零 LLM）→ L3（LLM 学模板，每域一次）。

    只处理**现抓的页**：缓存命中的 payload 没有响应体，而且它的字段本就是
    上一次（可能带 L2/L3）的结果 —— 没有重算的必要。

    L2 **不受 LLM 开关约束**：模板是已经付过费学到的资产，复用它是零成本的。
    只有"学新模板"（L3）才需要 LLM 开关与预算。
    """
    template_cache: dict[str, dict[str, str]] = {}
    attempted_domains: set[str] = set()

    for target, payload in payloads.items():
        if payload.from_cache or not payload.ok or not payload.body:
            continue
        if cfg.llm_enabled:
            # 标记"这一份缓存是在 LLM 层开启时写的" → 以后可被复用（见读缓存段）
            payload.llm_layer = True

        wanted = [f for f in EXTRACTABLE_FIELDS if not payload.fields.get(f)]
        if not wanted:
            continue

        tree = parse_html(payload.body)
        if tree is None:
            _bounded(stats["errors"], f"{target}：L2/L3 跳过（HTML 解析失败）")
            continue

        domain = domain_of(target)

        # ── L2：用已学的模板取值（0 调用、0 网络）───────────────────────
        if domain not in template_cache:
            template_cache[domain] = (
                await load_templates(session, domain) if session is not None else {}
            )
        templates = template_cache[domain]
        # 循环变量别叫 `field`：它会遮蔽 `dataclasses.field`（本模块顶部导入了它）
        for field_name in list(wanted):
            expr = templates.get(field_name)
            if not expr:
                continue
            values = apply_xpath(tree, expr, limit=1)
            hit = bool(values and values[0].strip())
            if session is not None:
                await record_outcome(session, domain, field_name, hit=hit, now=now)
            if not hit:
                continue
            payload.fields[field_name] = values[0].strip()
            payload.tier_of[field_name] = "xpath"
            stats["template_hits"] += 1
            wanted.remove(field_name)

        if not wanted:
            continue

        # ── L3：还缺字段才学（每域一次，受开关与预算约束）────────────────
        if not cfg.llm_enabled:
            continue
        if domain in attempted_domains:
            continue
        attempted_domains.add(domain)

        result = await learn_link_fields(
            domain=domain,
            tree=tree,
            text=payload.text,
            session=session,
            budget=budget,
            fields=tuple(wanted),
            max_text_chars=cfg.max_text_chars,
        )
        if result.skipped:
            key = result.skipped
            stats["llm_skipped"][key] = stats["llm_skipped"].get(key, 0) + 1
        if result.error:
            _bounded(stats["errors"], f"L3@{domain}：{result.error}")
        if result.learned:
            _bounded(stats["llm_domains"], domain)
            stats["templates_learned"] += len(result.learned)
        for name, value in result.fields.items():
            payload.fields[name] = value
            payload.tier_of[name] = "llm"


def _merge_budget_stats(stats: dict, budget: LlmBudget) -> None:
    """把预算账本并进统计。

    `budget_exceeded` 要**或**上去而不是覆盖：URL 预算（max_rows/max_urls）也会把它
    置真，而 LLM 预算只是另一个来源。覆盖会把先前的"撞了 URL 上限"抹掉。

    B3-3 起同时写 `budget_llm_exceeded`（LLM 那一半，来源明确）。
    `budget_url_exceeded` 由 URL 预算的两处截断点自己置真，这里不碰 ——
    它可能在**没走到 LLM 层**时就已是真（如 `unique_urls` 为空提前返回）。
    """
    llm = budget.as_stats()
    stats["llm_calls"] = llm["llm_calls"]
    stats["tokens_used"] = llm["tokens_used"]
    stats["tokens_input"] = llm["tokens_input"]
    stats["tokens_output"] = llm["tokens_output"]
    stats["budget_llm_exceeded"] = bool(llm["budget_exceeded"])
    stats["budget_exceeded"] = bool(stats.get("budget_exceeded")) or bool(llm["budget_exceeded"])


async def _fetch_and_extract(
    url: str,
    *,
    config: EnrichConfig,
    client: httpx.AsyncClient | None,
    resolver,
) -> tuple[_UrlPayload, FetchOutcome]:
    """抓 + 提取（含缓存写入所需信息）。不发 DB 请求 —— 由调用方串行落缓存。"""
    outcome = await fetch_page(
        url,
        client=client,
        timeout=config.timeout_s,
        max_bytes=config.max_bytes,
        max_redirects=config.max_redirects,
        resolver=resolver,
    )
    if not outcome.ok or outcome.body is None:
        return (
            _UrlPayload(
                url=url,
                error=outcome.error,
                blocked_reason=outcome.blocked_reason,
            ),
            outcome,
        )

    facts = extract_page(
        outcome.body,
        url=outcome.final_url or url,
        max_text_chars=config.max_text_chars,
    )
    payload = _UrlPayload(
        url=url,
        fields=facts.fields,
        tier_of=facts.tier_of,
        tiers_hit=facts.tiers_hit,
        text=facts.text,
        ok=bool(facts.fields or facts.text),
        error=facts.error,
        truncated=outcome.truncated,
        body=outcome.body,
    )
    return payload, outcome


async def enrich_rows(
    rows: list[dict],
    *,
    session=None,
    config: EnrichConfig | None = None,
    client: httpx.AsyncClient | None = None,
    resolver=resolve_host,
    now: datetime | None = None,
) -> tuple[list[dict], dict]:
    """对一批行做链接富化。

    返回 `(新行列表, 统计)`。**不改传入的 rows**（返回的是新 dict，便于对照测试）。
    `session` 为 None 时不使用缓存（照样能跑）。
    """
    cfg = config or EnrichConfig.from_settings()
    rows = list(rows or [])

    stats: dict[str, Any] = {
        "enabled": cfg.enabled,
        "rows_scanned": len(rows),
        "rows_with_url": 0,
        "rows_enriched": 0,
        # B3-3（2026-09-29）：`rows_enriched` 只代表"至少抓到一个页面"，可能一个字段
        # 都没补到（页面抓到了但没有可用字段）。真正能回答"富化到底有没有用"的是
        # 这个数 —— **至少补到 1 个字段**的行数。两者都留着，差值即"白抓的行"。
        "rows_fields_filled": 0,
        "rows_budget_skipped": 0,
        "urls_found": 0,
        "urls_unique": 0,
        "urls_fetched": 0,
        "cache_hits": 0,
        "http_hits": 0,
        "jsonld_hits": 0,
        "og_hits": 0,
        "text_hits": 0,
        "fields_filled": {},
        "conflicts_count": 0,
        "conflicts": [],
        "blocked": [],
        "errors": [],
        # B3-3（2026-09-29）：一个 `budget_exceeded` 说不清是撞了哪个上限 ——
        # URL 上限（max_rows/max_urls，由**上传者的行数**决定）与 LLM 上限
        # （调用次数/token，由**表里有几个域**决定）的处置方式完全不同，UI 必须分开。
        # `budget_exceeded` 保留为两者的**或**（向后兼容既有测试与验收脚本）。
        "budget_url_exceeded": False,
        "budget_llm_exceeded": False,
        "budget_exceeded": False,
        # ── B3-2（L2/L3）─────────────────────────────────────────────
        "template_hits": 0,
        "templates_learned": 0,
        "llm_calls": 0,
        "tokens_used": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "llm_domains": [],
        "llm_skipped": {},
    }
    if not cfg.enabled:
        logger.info("Link Enrich 未启用（LINK_ENRICH_ENABLED=false），跳过")
        return rows, stats

    # ── 1. L0 发现（纯本地）─────────────────────────────────────────────
    # row_urls[i] = 第 i 行发现的 URL；只给"真正要富化"的前 max_rows 行排计划
    row_urls: list[list[str]] = [discover_row_urls(r, per_row_limit=MAX_URLS_PER_ROW) for r in rows]
    stats["urls_found"] = sum(len(u) for u in row_urls)
    stats["rows_with_url"] = sum(1 for u in row_urls if u)

    planned_rows = 0
    plan: dict[int, list[str]] = {}
    unique_urls: list[str] = []
    seen: set[str] = set()

    for index, urls in enumerate(row_urls):
        if not urls:
            continue
        if planned_rows >= cfg.max_rows:
            stats["rows_budget_skipped"] += 1
            stats["budget_url_exceeded"] = True
            stats["budget_exceeded"] = True
            continue
        planned_rows += 1
        kept: list[str] = []
        for url in urls:
            if len(unique_urls) >= cfg.max_urls:
                stats["budget_url_exceeded"] = True
                stats["budget_exceeded"] = True
                break
            key = make_url_hash(url)
            if key in seen:
                kept.append(url)
                continue
            seen.add(key)
            unique_urls.append(url)
            kept.append(url)
        plan[index] = kept

    stats["urls_unique"] = len(unique_urls)
    if not unique_urls:
        logger.info("Link Enrich：本次导入没有发现可用链接 | rows={}", len(rows))
        return rows, stats

    logger.info(
        "Link Enrich 开始 | rows={} | rows_with_url={} | urls_unique={} | domains={}",
        len(rows),
        stats["rows_with_url"],
        len(unique_urls),
        list(group_by_domain(unique_urls)),
    )

    # ── 2. 读缓存（串行 DB）────────────────────────────────────────────
    payloads: dict[str, _UrlPayload] = {}
    misses: list[str] = []
    if session is not None:
        for url in unique_urls:
            cached = await load_cache(session, url, now=now)
            if cached is None:
                misses.append(url)
                continue
            # 缓存与 LLM 层的**一致性规则**：零成本层写的缓存（`llm=false`）在 LLM 层
            # 打开后**不再复用** —— 否则用户刚打开开关却因缓存命中而看不到任何变化，
            # 会以为功能没生效。代价是一次重新抓取（受 urls 预算约束）。
            if cfg.llm_enabled and not cached.get("llm"):
                misses.append(url)
                continue
            payloads[url] = _UrlPayload.from_cached_payload(url, cached)
            stats["cache_hits"] += 1
    else:
        misses = list(unique_urls)

    # ── 3. 并发抓取（只并发网络，不并发 DB）─────────────────────────────
    outcomes: dict[str, FetchOutcome] = {}
    if misses:
        semaphore = asyncio.Semaphore(cfg.concurrency)

        async def _one(target: str) -> tuple[str, _UrlPayload, FetchOutcome]:
            async with semaphore:
                return (target, *await _fetch_and_extract(
                    target, config=cfg, client=client, resolver=resolver
                ))

        results = await asyncio.gather(*(_one(u) for u in misses), return_exceptions=True)
        for item in results:
            if isinstance(item, BaseException):
                # gather 里单个任务崩了不该毁掉整批（_fetch_and_extract 内部已兜底，
                # 走到这里说明是更意外的错误）
                _bounded(stats["errors"], f"抓取任务异常：{type(item).__name__}")
                continue
            target, payload, outcome = item
            payloads[target] = payload
            outcomes[target] = outcome

    # ── 4. L2 模板复用 + L3 LLM 学模板（只对"现抓的页"）─────────────────
    budget = LlmBudget(max_calls=cfg.max_llm_calls, max_tokens=cfg.max_tokens)
    await _apply_templates_and_llm(
        payloads, cfg=cfg, session=session, budget=budget, stats=stats, now=now
    )
    _merge_budget_stats(stats, budget)

    # ── 5. 写缓存（串行 DB；放在 L2/L3 之后，好让缓存带上它们的成果与标记）──
    if session is not None:
        for target, payload in payloads.items():
            if payload.from_cache:
                continue
            outcome = outcomes.get(target)
            if payload.ok:
                await store_cache(
                    session,
                    target,
                    status_code=outcome.status_code if outcome else None,
                    payload=payload.to_cache(),
                    ttl_hours=cfg.cache_ttl_hours,
                    now=now,
                )

    # ── 5. 逐行按 URL 顺序合并（确定性）─────────────────────────────────
    enriched: list[dict] = []
    for index, row in enumerate(rows):
        targets = plan.get(index)
        if not targets:
            enriched.append(dict(row))
            continue

        new_row = dict(row)
        per_row: list[dict] = []
        row_conflicts: list[dict] = []
        provenance: dict[str, str] = {}
        filled: list[str] = []
        tiers = {"jsonld": 0, "og": 0, "text": 0}
        cache_hits = 0
        fetched = 0
        row_errors: list[str] = []
        winning_url = ""

        for target in targets:
            payload = payloads.get(target)
            if payload is None:
                continue
            if payload.from_cache:
                cache_hits += 1
            else:
                fetched += 1
            if not payload.ok:
                if payload.error:
                    _bounded(row_errors, f"{target}：{payload.error}")
                if payload.blocked_reason:
                    _bounded(stats["blocked"], {"url": target, "reason": payload.blocked_reason})
                continue
            if payload.truncated:
                _bounded(row_errors, f"{target}：响应体超过大小上限，已截断")
            if not winning_url:
                winning_url = target

            for tier in payload.tiers_hit:
                if tier in tiers:
                    tiers[tier] += 1

            outcome = merge_link_fields(
                new_row,
                payload.fields,
                domain=domain_of(target),
                tier_of=payload.tier_of,
            )
            new_row.update(outcome.filled)
            filled.extend(outcome.filled.keys())
            provenance.update(outcome.provenance)
            for conflict in outcome.conflicts:
                conflict["url"] = target
                _bounded(row_conflicts, conflict)
                stats["conflicts_count"] += 1
                _bounded(
                    stats["conflicts"],
                    {"row": str(new_row.get("title") or "")[:80], **conflict},
                )
            per_row.append(
                {
                    "url": target,
                    "tiers_hit": list(payload.tiers_hit),
                    "filled": sorted(outcome.filled.keys()),
                    "conflicts": len(outcome.conflicts),
                    "from_cache": payload.from_cache,
                }
            )

        if winning_url and not new_row.get("source_url"):
            new_row["source_url"] = winning_url

        if per_row:
            stats["rows_enriched"] += 1
            # B3-3：只有真的补到字段才算"富化有产出"（抓到了页但 0 字段不算）
            if filled:
                stats["rows_fields_filled"] += 1
            for key in filled:
                stats["fields_filled"][key] = stats["fields_filled"].get(key, 0) + 1
            new_row["enrich_stats"] = {
                "version": CACHE_VERSION,
                "urls": targets,
                "pages": per_row,
                "sources": tiers,
                "filled": sorted(set(filled)),
                "conflicts": row_conflicts,
                "provenance": provenance,
                "cache_hits": cache_hits,
                "fetched": fetched,
                "errors": row_errors,
            }
        enriched.append(new_row)

    # ── 6. 汇总 ─────────────────────────────────────────────────────────
    for payload in payloads.values():
        if not payload.ok:
            continue
        if not payload.from_cache:
            stats["urls_fetched"] += 1
            stats["http_hits"] += 1
        if "jsonld" in payload.tiers_hit:
            stats["jsonld_hits"] += 1
        if "og" in payload.tiers_hit:
            stats["og_hits"] += 1
        if "text" in payload.tiers_hit:
            stats["text_hits"] += 1
    for payload in payloads.values():
        if payload.error and not payload.blocked_reason:
            _bounded(stats["errors"], f"{payload.url}：{payload.error}")

    logger.info(
        "Link Enrich 完成 | enriched={} | fetched={} | cache_hits={} | "
        "jsonld={} og={} text={} | conflicts={} | budget_exceeded={}",
        stats["rows_enriched"],
        stats["urls_fetched"],
        stats["cache_hits"],
        stats["jsonld_hits"],
        stats["og_hits"],
        stats["text_hits"],
        stats["conflicts_count"],
        stats["budget_exceeded"],
    )
    return enriched, stats


async def fetch_one(
    url: str,
    *,
    session=None,
    config: EnrichConfig | None = None,
    client: httpx.AsyncClient | None = None,
    resolver=resolve_host,
) -> dict:
    """抓单个 URL 并返回结构化结果 —— **C4 `link_fetch` 工具的后端**。

    与导入路径共用同一套守卫/抓取/提取，避免"工具里再写一遍"（P6 的既定做法）。
    """
    cfg = config or EnrichConfig.from_settings()
    cached = await load_cache(session, url) if session is not None else None
    if cached is not None:
        payload = _UrlPayload.from_cached_payload(url, cached)
        outcome = None
    else:
        payload, outcome = await _fetch_and_extract(
            url, config=cfg, client=client, resolver=resolver
        )
        if session is not None and payload.ok:
            await store_cache(
                session,
                url,
                status_code=outcome.status_code if outcome else None,
                payload=payload.to_cache(),
                ttl_hours=cfg.cache_ttl_hours,
            )

    return {
        "url": url,
        "domain": domain_of(url),
        "success": payload.ok,
        "from_cache": payload.from_cache,
        "status_code": outcome.status_code if outcome else None,
        "tiers_hit": list(payload.tiers_hit),
        "fields": payload.fields,
        "text": payload.text,
        "truncated": payload.truncated,
        "error": payload.error,
        "blocked_reason": payload.blocked_reason,
    }


__all__ = ["EnrichConfig", "enrich_rows", "fetch_one"]
