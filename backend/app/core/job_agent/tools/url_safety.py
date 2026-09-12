from __future__ import annotations

from urllib.parse import urlparse

import httpx
from langchain_core.tools import tool
from loguru import logger

# Safe domains that are commonly used for job postings
DEFAULT_WHITELIST: set[str] = {
    "zhaopin.com",
    "zhilian.com",
    "lagou.com",
    "maimai.cn",
    "liepin.com",
    "51job.com",
    "jobui.com",
    "shixi.com",
    "dajie.com",
    "yingjiesheng.com",
    "hihr.com",
    "100offer.com",
    "bosszhipin.com",
    "zhipin.com",
    "kanzhun.com",
    "linkedin.com",
    "linkedin.cn",
    "indeed.com",
}

# Known unsafe patterns
DEFAULT_BLACKLIST: set[str] = {
    "example.com",
    "malware.com",
    "phishing.com",
}


def _extract_domain(url: str) -> str:
    """Extract the domain from a URL, handling various formats."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove port if present
        if ":" in domain:
            domain = domain.split(":")[0]
        # Remove www. prefix for matching
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return url.lower()


def _check_domain_safety(
    domain: str,
    whitelist: set[str] | None = None,
    blacklist: set[str] | None = None,
) -> tuple[bool, str]:
    """Check if a domain is safe based on whitelist/blacklist.

    Returns (is_safe, reason).
    """
    wl = whitelist or DEFAULT_WHITELIST
    bl = blacklist or DEFAULT_BLACKLIST

    # Check blacklist first (exact and subdomain match)
    for bad in bl:
        if domain == bad or domain.endswith("." + bad):
            return False, f"Domain '{domain}' is blacklisted"

    # Check if domain is known-safe (whitelist)
    for safe in wl:
        if domain == safe or domain.endswith("." + safe):
            return True, f"Domain '{domain}' is whitelisted"

    # Unknown domain — allow but flag as unchecked
    return True, f"Domain '{domain}' is not on any list (unchecked)"


async def _check_url_reachability(url: str, timeout: float = 10.0) -> tuple[bool, str, int | None]:
    """Perform a HEAD request to check if the URL is reachable.

    Returns (is_reachable, status_text, status_code).
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.head(url)
            if response.status_code < 400:
                return True, f"HTTP {response.status_code}", response.status_code
            return False, f"HTTP {response.status_code}", response.status_code
    except httpx.TimeoutException:
        return False, "Connection timeout", None
    except httpx.ConnectError:
        return False, "Connection refused", None
    except Exception as exc:
        return False, f"Check failed: {exc}", None


@tool
async def url_safety_check(
    url: str,
    whitelist: list[str] | None = None,
    blacklist: list[str] | None = None,
    check_reachability: bool = True,
) -> dict:
    """Check the safety of a URL before fetching its content.

    Validates the URL format, checks against domain whitelist/blacklist,
    and optionally performs a HEAD request to verify reachability.

    Args:
        url: The URL to check.
        whitelist: Optional override list of safe domains.
        blacklist: Optional override list of unsafe domains.
        check_reachability: Whether to perform a HEAD request (default True).

    Returns:
        Dict with is_safe (bool), reason (str), domain (str),
        reachable (bool or None), status_code (int or None), and
        status_text (str or None).
    """
    logger.info("URL safety check tool | url={}", url)

    # Convert optional lists to sets
    wl_set = set(whitelist) if whitelist else None
    bl_set = set(blacklist) if blacklist else None

    # Extract domain
    domain = _extract_domain(url)
    logger.debug("URL safety check | parsed domain={}", domain)

    # Domain check
    is_safe, reason = _check_domain_safety(domain, wl_set, bl_set)

    result: dict = {
        "is_safe": is_safe,
        "reason": reason,
        "domain": domain,
        "reachable": None,
        "status_code": None,
        "status_text": None,
    }

    # Reachability check
    if check_reachability and is_safe:
        reachable, status_text, status_code = await _check_url_reachability(url)
        result["reachable"] = reachable
        result["status_code"] = status_code
        result["status_text"] = status_text
        if not reachable:
            result["is_safe"] = False
            result["reason"] = f"URL not reachable: {status_text}"

    return result
