"""C4 工具：`link_fetch` —— 抓一个招聘链接并返回结构化字段。**0 LLM 调用**。

定位
----
模型在对话里遇到「这个岗位链接里写了什么」时，不必把整页 HTML 塞进上下文：
本工具在**服务端**抓取并抽好字段（公司/城市/薪资/描述…），只把结构化结果回给模型。

实现**不重写一遍抓取**（P6 的既定做法）：直接复用 B3-1 的
`core/link_enrich`（同一套 SSRF 守卫、逐跳复检、缓存、提取、正文切分），
否则"导入路径"和"工具路径"迟早会走出两套安全口径。

安全
----
URL 来自**模型**（而模型可能被用户话术诱导），所以这里的守卫是硬要求：
`safety.check_url` 拒绝内网/回环/链路本地/单标签主机名，重定向逐跳复检。
被拒绝时返回 `success=false` 并给出原因，而不是抛异常 —— 模型能读到原因并换路。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from loguru import logger

from app.core.link_enrich import EnrichConfig, fetch_one
from app.infrastructure.database import async_session_factory

#: 回给模型的正文上限。配置里的 `max_text_chars`（默认 4000）是**入库/喂管线**的口径；
#: 对话场景要更省 —— 4000 字符≈2000+ token，一次工具调用就吃掉小半上下文。
DEFAULT_RETURN_CHARS = 1500


@tool
async def link_fetch(url: str, max_chars: int = DEFAULT_RETURN_CHARS) -> dict:
    """Fetch a job-posting URL on the server and return its structured fields.

    Use this when the user gives a link to a job posting (or asks what a link
    contains) instead of pasting the text. Parsing happens on the server, so
    the raw HTML never enters this conversation.

    Args:
        url: The web address to read (must be http/https, public internet).
        max_chars: Max characters of page text to return (default 1500).

    Returns:
        Dict with success (bool), url, domain, from_cache (bool), status_code,
        tiers_hit (list of "jsonld"/"og"/"text"), fields (dict with any of
        title/company/city/region/salary/industry/education_requirement/
        experience_requirement/description/requirements), text (str, may be
        empty), text_truncated (bool), and error (str or None). On a security
        rejection, success is False and error explains why.
    """
    logger.info("link_fetch 工具 | url={} | max_chars={}", url, max_chars)

    cfg = EnrichConfig.from_settings()
    limit = max(0, int(max_chars or 0)) or DEFAULT_RETURN_CHARS

    try:
        # 缓存要读写，所以自己开 session（与 job_search 等工具同一做法）
        async with async_session_factory() as session:
            try:
                result = await fetch_one(url, session=session, config=cfg)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 - 工具绝不能把异常抛进 ReAct 循环
        logger.warning("link_fetch 失败 | url={} | error={}", url, exc)
        return {
            "success": False,
            "url": url,
            "domain": "",
            "error": f"抓取失败：{type(exc).__name__}: {exc}"[:200],
        }

    text = result.get("text") or ""
    clipped = text[:limit]
    payload: dict[str, Any] = {
        "success": result.get("success", False),
        "url": result.get("url"),
        "domain": result.get("domain"),
        "from_cache": result.get("from_cache", False),
        "status_code": result.get("status_code"),
        "tiers_hit": result.get("tiers_hit") or [],
        "fields": result.get("fields") or {},
        "text": clipped,
        "text_chars": len(text),
        "text_truncated": len(text) > len(clipped),
        "error": result.get("error"),
    }
    if result.get("blocked_reason"):
        # 把"这是安全拦截"和"网络不通"分开 —— 否则模型会反复重试同一个内网地址
        payload["error"] = f"该地址被安全策略拒绝：{result['blocked_reason']}"
        payload["blocked"] = True

    logger.info(
        "link_fetch 完成 | url={} | success={} | tiers={} | fields={}",
        url,
        payload["success"],
        payload["tiers_hit"],
        sorted(payload["fields"]),
    )
    return payload


__all__ = ["DEFAULT_RETURN_CHARS", "link_fetch"]
