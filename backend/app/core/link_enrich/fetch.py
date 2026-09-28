"""HTTP 抓取：SSRF 逐跳复检 + 有界读取 + 落库缓存。

## 为什么自己处理重定向

`follow_redirects=True` 会让 httpx 直接跟到最终地址 —— 于是"公网 URL 302 到
`http://169.254.169.254/`"就绕过了守卫（守卫只知道第一个 URL 是安全的）。
所以这里 `follow_redirects=False`，**每一跳都重新过一遍 `check_url`**。

## 为什么要限制响应体大小

一个恶意的 `/dev/urandom` 式响应或超大页面能把内存吃光。用 `client.stream` +
累计字节数上限，超限即断并**标记 truncation**（不假装拿全了）。

## 缓存

命中 `link_fetch_cache` 就不再发请求（§4.2 第 6 点）。缓存内容是**提取结果**
（见 `models/link_fetch_cache.py`），带 `CACHE_VERSION` 防"代码升级了、老缓存
仍按新口径解读"。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.link_enrich.safety import check_url, resolve_host
from app.core.link_enrich.urls import domain_of, normalise_url, url_hash
from app.domain.models.link_fetch_cache import LinkFetchCache

#: 提取结果的结构版本。**改动 extract.py 的口径时必须 +1**，否则老缓存会被新代码
#: 按新规则解读（详见 `models/link_fetch_cache.py` 的 docstring）。
CACHE_VERSION = 1

#: 只抓"网页"。图片/PDF/压缩包对字段提取毫无用处，白耗流量。
ALLOWED_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/ld+json",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 CareerPlanningBot/1.0"
)

#: 除 HTML 外的常见压缩/编码兜底（不少站不回 content-type）
_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@dataclass
class FetchOutcome:
    """一次抓取的结果。`ok=False` 时 `error` 必非空。"""

    url: str
    final_url: str = ""
    status_code: int | None = None
    body: bytes | None = None
    content_type: str = ""
    ok: bool = False
    error: str | None = None
    #: SSRF 守卫拒绝时的原因（与普通网络错误区分开，便于统计与排查）
    blocked_reason: str | None = None
    truncated: bool = False
    from_cache: bool = False
    cached_payload: dict | None = None


def _content_type_ok(content_type: str) -> bool:
    if not content_type:
        return True  # 不少站不回该头，不能因此拒绝
    lowered = content_type.split(";")[0].strip().lower()
    return any(lowered.startswith(allowed) for allowed in ALLOWED_CONTENT_TYPES)


async def fetch_page(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 20.0,
    max_bytes: int = 2_000_000,
    max_redirects: int = 5,
    resolver=resolve_host,
) -> FetchOutcome:
    """抓一个 URL（含逐跳 SSRF 复检）。**永不抛异常** —— 失败一律返回 `ok=False`。"""
    target = normalise_url(url)
    if not target:
        return FetchOutcome(url=url, error="URL 不规范")

    owned_client = client is None
    if owned_client:
        client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": _ACCEPT},
        )

    try:
        current = target
        for hop in range(max_redirects + 1):
            verdict = await check_url(current, resolver=resolver)
            if not verdict.ok:
                logger.warning("抓取被 SSRF 守卫拒绝 | url={} | reason={}", current, verdict.reason)
                return FetchOutcome(
                    url=url,
                    final_url=current,
                    error=f"安全校验未通过：{verdict.reason}",
                    blocked_reason=verdict.reason,
                )

            async with client.stream("GET", current, follow_redirects=False) as response:
                status = response.status_code
                headers = response.headers

                if 300 <= status < 400 and headers.get("location"):
                    if hop == max_redirects:
                        return FetchOutcome(
                            url=url, final_url=current, status_code=status,
                            error=f"重定向超过 {max_redirects} 跳",
                        )
                    # 相对 Location 要按当前地址解析（不少站回 /job/1 这种相对路径）
                    current = urljoin(current, headers["location"])
                    logger.debug("跟随重定向 | hop={} | to={}", hop + 1, current)
                    continue

                content_type = headers.get("content-type", "")
                if not _content_type_ok(content_type):
                    return FetchOutcome(
                        url=url, final_url=current, status_code=status,
                        content_type=content_type,
                        error=f"非网页内容：{content_type.split(';')[0]}",
                    )

                buffer = bytearray()
                truncated = False
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) >= max_bytes:
                        # 必须**裁到上限**再 break：只 break 的话，这一块多出来的
                        # 部分仍然留在 buffer 里。真实网络下块是 ~64KB 所以溢出有限，
                        # 但单元测试里 MockTransport 一次吐整包，能超出几十倍
                        # （2026-09-27 实测：max_bytes=1000 却拿到 5026 字节）。
                        del buffer[max_bytes:]
                        truncated = True
                        break

                if status >= 400:
                    return FetchOutcome(
                        url=url, final_url=current, status_code=status,
                        content_type=content_type, error=f"HTTP {status}",
                    )

                return FetchOutcome(
                    url=url,
                    final_url=current,
                    status_code=status,
                    body=bytes(buffer),
                    content_type=content_type,
                    ok=True,
                    truncated=truncated,
                )

        return FetchOutcome(url=url, final_url=current, error="重定向处理异常")
    except httpx.TimeoutException:
        return FetchOutcome(url=url, error=f"请求超时（{timeout}s）")
    except httpx.HTTPError as exc:
        return FetchOutcome(url=url, error=f"网络错误：{type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 - 抓取失败种类不可穷举，绝不能冒泡打断导入
        logger.warning("抓取失败 | url={} | error={}", url, exc)
        return FetchOutcome(url=url, error=f"{type(exc).__name__}: {exc}"[:200])
    finally:
        if owned_client:
            await client.aclose()


# ── 缓存读写 ──────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def load_cache(session: AsyncSession, url: str, *, now: datetime | None = None) -> dict | None:
    """读缓存。过期 / 版本不符 / 内容坏了都当未命中（返回 None）。"""
    try:
        row = (
            await session.execute(
                select(LinkFetchCache).where(LinkFetchCache.url_hash == url_hash(url)).limit(1)
            )
        ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - 缓存读失败不该让导入失败
        logger.warning("读抓取缓存失败（按未命中处理）| url={} | error={}", url, exc)
        return None

    if row is None or not row.content:
        return None
    if row.expires_at is not None and row.expires_at <= (now or _now()):
        return None
    try:
        payload = json.loads(row.content)
    except Exception:  # noqa: BLE001 - 缓存里是坏 JSON 时静默当未命中
        logger.warning("抓取缓存内容不是合法 JSON，按未命中处理 | url={}", url)
        return None
    if not isinstance(payload, dict) or payload.get("v") != CACHE_VERSION:
        return None
    return payload


async def store_cache(
    session: AsyncSession,
    url: str,
    *,
    status_code: int | None,
    payload: dict,
    ttl_hours: int = 168,
    now: datetime | None = None,
) -> None:
    """写缓存（按 url_hash upsert）。写失败只告警 —— 缓存是优化，不是正确性依赖。"""
    current = now or _now()
    stamped = {**payload, "v": CACHE_VERSION}
    try:
        row = (
            await session.execute(
                select(LinkFetchCache).where(LinkFetchCache.url_hash == url_hash(url)).limit(1)
            )
        ).scalar_one_or_none()
        expires = current + timedelta(hours=max(ttl_hours, 0)) if ttl_hours else None
        body = json.dumps(stamped, ensure_ascii=False)
        if row is None:
            session.add(
                LinkFetchCache(
                    url_hash=url_hash(url),
                    url=url,
                    domain=domain_of(url),
                    status_code=status_code,
                    content=body,
                    fetched_at=current,
                    expires_at=expires,
                )
            )
        else:
            row.url = url
            row.domain = domain_of(url)
            row.status_code = status_code
            row.content = body
            row.fetched_at = current
            row.expires_at = expires
        await session.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("写抓取缓存失败（忽略）| url={} | error={}", url, exc)


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "CACHE_VERSION",
    "DEFAULT_USER_AGENT",
    "FetchOutcome",
    "fetch_page",
    "load_cache",
    "store_cache",
]
