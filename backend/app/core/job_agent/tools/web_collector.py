from __future__ import annotations

import httpx
from langchain_core.tools import tool
from loguru import logger

from app.config import get_settings

# DuckDuckGo Lite API endpoint
_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"


async def _search_tavily(keywords: str, max_results: int) -> list[dict]:
    """Search using Tavily API."""
    settings = get_settings()
    api_key = settings.tavily_api_key
    if not api_key:
        logger.info("Tavily API key not configured, skipping")
        return []

    url = f"{settings.tavily_base_url.rstrip('/')}/search"
    payload = {
        "api_key": api_key,
        "query": keywords,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        logger.info("Tavily search | keywords={!r:.60} | hits={}", keywords, len(results))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "source": "tavily",
            }
            for r in results
        ]
    except Exception as exc:
        logger.warning("Tavily search failed | keywords={!r:.60} | error={}", keywords, exc)
        return []


async def _search_duckduckgo(keywords: str, max_results: int) -> list[dict]:
    """Search using DuckDuckGo Lite (no API key required)."""
    try:
        params = {"q": keywords}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(_DDG_LITE_URL, params=params)
            resp.raise_for_status()
            html = resp.text

        # Simple HTML parsing to extract results from DuckDuckGo Lite
        results = _parse_ddg_lite_html(html, max_results)
        logger.info("DuckDuckGo search | keywords={!r:.60} | hits={}", keywords, len(results))
        return results
    except Exception as exc:
        logger.warning("DuckDuckGo search failed | keywords={!r:.60} | error={}", keywords, exc)
        return []


def _parse_ddg_lite_html(html: str, max_results: int) -> list[dict]:
    """Parse DuckDuckGo Lite HTML to extract search results."""
    results: list[dict] = []
    # Split by result table rows
    # DDG Lite returns results in a simple HTML table format
    import re

    # Find all result links in the HTML
    # Pattern: <a rel="nofollow" href="URL">TITLE</a> followed by snippet
    link_pattern = re.compile(r'<a\s+rel="nofollow"\s+href="([^"]+)"[^>]*>([^<]+)</a>')
    snippet_pattern = re.compile(r'<td\s+class="result-snippet">([^<]*)</td>')

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(links):
        if i >= max_results:
            break
        snippet = snippets[i] if i < len(snippets) else ""
        results.append({
            "title": title.strip(),
            "url": url,
            "snippet": snippet.strip(),
            "source": "duckduckgo",
        })

    return results


@tool
async def web_collector(
    keywords: str,
    max_results: int = 10,
    source_filter: list[str] | None = None,
) -> dict:
    """Collect job/industry data from the web using search engines.

    Uses Tavily API as the primary search provider (requires TAVILY_API_KEY
    in .env) and falls back to DuckDuckGo Lite if Tavily is unavailable.

    Args:
        keywords: Search keywords (e.g. "前端开发 行业趋势 2024").
        max_results: Maximum number of results to collect (default 10, max 50).
        source_filter: Optional list of allowed domains (e.g.
                       ["zhaopin.com", "lagou.com"]). If provided, only
                       results from these domains are returned.

    Returns:
        Dict with total (int), results (list[dict]), and source (str).
        Each result has: title, url, snippet, source.
    """
    max_results = min(max(max_results, 1), 50)
    logger.info("Web collector tool | keywords={!r:.60} | max_results={}", keywords, max_results)

    # Primary: Tavily
    results = await _search_tavily(keywords, max_results)

    # Fallback: DuckDuckGo
    if not results:
        logger.info("Tavily returned no results, falling back to DuckDuckGo")
        results = await _search_duckduckgo(keywords, max_results)

    # Apply source filter if provided
    if source_filter and results:
        allowed = {d.lower() for d in source_filter}
        filtered = [
            r for r in results
            if any(d in r["url"].lower() for d in allowed)
        ]
        if filtered:
            results = filtered
        # If filter removes everything, keep original results with a note

    used_source = results[0]["source"] if results else "none"
    logger.info("Web collection complete | source={} | results={}", used_source, len(results))
    return {
        "total": len(results),
        "results": results[:max_results],
        "source": used_source,
    }
