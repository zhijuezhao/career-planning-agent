"""L0 层：URL 发现（零 LLM、零网络）。

设计要点（主计划 §4.1 L0）：**正则扫字段值里的完整 URL，按 domain 去重分组**。
这一层不花任何 token，也不发请求，纯粹是"这张表里哪些单元格写了链接"。

为什么先看 `source_url` 键：`data_loader.DEFAULT_COLUMN_MAPPING` 已把
「岗位链接/职位链接/招聘链接/详情链接/来源链接/链接/URL/url」统一映射成
`source_url`（见 `data_loader.py:50-58`）。所以绝大多数情况下链接就在这一个键里，
先扫它可以让"每行优先用官方链接列"成为确定性行为，而不是靠字典顺序碰运气。
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

#: 命中 http(s) 链接。**不含**空白与常见中英文包裹符号 —— 表格里链接常被写在
#: "详情：" 后面或括号里，尾随标点必须切掉，否则会把 "https://a.com/job。" 当成
#: 路径的一部分去请求（实测 404）。
_URL_RE = re.compile(r"https?://[^\s<>\"'`，。；！？、）】》」』\]]+", re.IGNORECASE)

#: 链接尾部可能粘上的标点（中英文），逐个剥掉
_TRAILING_JUNK = ".,;:!?'\"`)]}>,，。；：！？、）】》」』"

#: 先扫这个键，再扫其余键
_PREFERRED_KEY = "source_url"

#: 单行 URL 数量上限（防止一个"备注"单元格塞了几十条链接把预算吃光）
DEFAULT_PER_ROW_LIMIT = 3


def normalise_url(url: str) -> str:
    """规范化 URL：去首尾空白/尾随标点、host 小写、去 fragment、补空路径。

    **保留 query**：不少招聘站的岗位 id 就在 query 里（`?jobId=123`），
    去掉 query 会让不同岗位变成同一个缓存键。
    """
    text = (url or "").strip().strip(_TRAILING_JUNK)
    if not text:
        return ""
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if not netloc:
        return ""
    # 去掉默认端口，让 `https://a.com:443/x` 与 `https://a.com/x` 共用一个缓存键
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    elif netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def url_hash(url: str) -> str:
    """缓存主键：`sha256(规范化 URL)`。

    必须与 `link_fetch_cache.url_hash VARCHAR(64)` 对齐 —— sha256 的十六进制
    正好 64 字符，无需截断。
    """
    return hashlib.sha256(normalise_url(url).encode("utf-8")).hexdigest()


def domain_of(url: str) -> str:
    """取域名（小写、去 `www.`），供 `link_fetch_cache.domain` 与 provenance 用。"""
    host = urlsplit(normalise_url(url)).hostname or ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def find_urls(value: object) -> list[str]:
    """从一个单元格值里挖出 URL（保序、去重）。非字符串一律返回空。"""
    if not isinstance(value, str) or not value:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.findall(value):
        candidate = normalise_url(match)
        if candidate and candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    return found


def discover_row_urls(row: dict, *, per_row_limit: int = DEFAULT_PER_ROW_LIMIT) -> list[str]:
    """扫一整行，返回该行的 URL 列表（`source_url` 键优先，其余按原顺序）。

    只认**字符串值**：表格里的数字/日期/布尔不可能藏链接，跳过它们可以少跑正则。
    """
    if not isinstance(row, dict):
        return []

    ordered_keys: list[str] = []
    if _PREFERRED_KEY in row:
        ordered_keys.append(_PREFERRED_KEY)
    ordered_keys.extend(k for k in row if k != _PREFERRED_KEY)

    urls: list[str] = []
    seen: set[str] = set()
    for key in ordered_keys:
        for url in find_urls(row.get(key)):
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= per_row_limit:
                return urls
    return urls


def group_by_domain(urls: list[str]) -> dict[str, list[str]]:
    """按域名分组（保序）。用于统计"这次导入涉及哪些站"与后续 XPath 模板按域复用。"""
    grouped: dict[str, list[str]] = {}
    for url in urls:
        grouped.setdefault(domain_of(url), []).append(url)
    return grouped


__all__ = [
    "DEFAULT_PER_ROW_LIMIT",
    "discover_row_urls",
    "domain_of",
    "find_urls",
    "group_by_domain",
    "normalise_url",
    "url_hash",
]
