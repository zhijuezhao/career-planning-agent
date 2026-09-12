from __future__ import annotations

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from loguru import logger


def _extract_main_content(soup: BeautifulSoup) -> str:
    """Extract the main text content from a BeautifulSoup object.

    Prioritises article/main/content elements, then falls back to body text.
    """
    # Try common content containers
    for selector in ("article", "main", "[role=main]", ".content", "#content", ".article", "#article"):
        container = soup.select_one(selector)
        if container:
            text = container.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return text

    # Fallback: body text
    body = soup.find("body")
    if body:
        text = body.get_text(separator="\n", strip=True)
        return text

    return ""


def _clean_text(text: str) -> str:
    """Clean extracted text by removing excessive whitespace and short lines."""
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if len(line) > 10:
            lines.append(line)
    return "\n".join(lines)


@tool
async def url_fetcher(url: str, timeout: float = 30.0) -> dict:
    """Fetch text content from a URL.

    Uses httpx to fetch the page and BeautifulSoup to extract the main
    text content and page title. If parsing fails, falls back to returning
    the raw response text.

    Args:
        url: The URL to fetch content from.
        timeout: Request timeout in seconds (default 30).

    Returns:
        Dict with url (str), content (str), title (str or None),
        success (bool), error (str or None), and is_ai_enriched (bool).
    """
    logger.info("URL fetcher tool | url={}", url)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")

        # Extract title
        title = None
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Extract main content
        raw_content = _extract_main_content(soup)
        if not raw_content:
            # Fallback: use raw text
            raw_content = soup.get_text(separator="\n", strip=True)

        content = _clean_text(raw_content)

        if not content:
            logger.warning("URL fetcher: extracted empty content | url={}", url)
            return {
                "url": url,
                "content": "",
                "title": title,
                "success": True,
                "is_ai_enriched": False,
                "error": "Page returned no meaningful text content",
            }

        logger.info("URL fetcher: success | url={} | title={!r:.50} | chars={}",
                    url, title, len(content))
        return {
            "url": url,
            "content": content,
            "title": title,
            "success": True,
            "is_ai_enriched": False,
            "error": None,
        }

    except httpx.HTTPStatusError as exc:
        logger.warning("URL fetcher: HTTP error | url={} | status={}", url, exc.response.status_code)
        return {
            "url": url,
            "content": "",
            "title": None,
            "success": False,
            "is_ai_enriched": False,
            "error": f"HTTP {exc.response.status_code}",
        }
    except httpx.TimeoutException:
        logger.warning("URL fetcher: timeout | url={}", url)
        return {
            "url": url,
            "content": "",
            "title": None,
            "success": False,
            "is_ai_enriched": False,
            "error": "Request timeout",
        }
    except Exception as exc:
        logger.warning("URL fetcher: failed | url={} | error={}", url, exc)
        return {
            "url": url,
            "content": "",
            "title": None,
            "success": False,
            "is_ai_enriched": False,
            "error": str(exc),
        }
