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
from app.core.link_enrich.extract import extract_page
from app.core.link_enrich.fetch import (
    CACHE_VERSION,
    FetchOutcome,
    fetch_page,
    load_cache,
    store_cache,
)
from app.core.link_enrich.merge import merge_link_fields
from app.core.link_enrich.safety import resolve_host
from app.core.link_enrich.urls import discover_row_urls, domain_of, group_by_domain
from app.core.link_enrich.urls import url_hash as make_url_hash

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
        )


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
        "budget_exceeded": False,
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
            stats["budget_exceeded"] = True
            continue
        planned_rows += 1
        kept: list[str] = []
        for url in urls:
            if len(unique_urls) >= cfg.max_urls:
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
            else:
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

    # ── 4. 写缓存（串行 DB）─────────────────────────────────────────────
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
