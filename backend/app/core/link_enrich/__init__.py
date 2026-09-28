"""Link Enrich（B3-1）：表格里的链接 → 抓取 → 结构化提取 → 确定性合并。**零 LLM**。

主计划 §4 的 L0/L1 两层在这里落地：

| 模块 | 层 | 职责 |
|---|---|---|
| `urls` | L0 | 正则扫字段值里的 URL，规范化、按域名分组 |
| `safety` | — | 抓取前的 SSRF 守卫（公网判定、逐跳复检由 `fetch` 执行） |
| `fetch` | L1 | httpx 抓取（有界读取、逐跳复检）+ `link_fetch_cache` 缓存 |
| `extract` | L1 | JSON-LD(JobPosting) → og/meta → 正文，逐级降级 |
| `merge` | — | 表格值优先的确定性合并 + provenance + 冲突记录 |
| `service` | — | 编排、预算闸门、统计（供导入流水线与 C4 工具共用） |

L2（XPath 模板）/L3（LLM 精简提取）/L4（冲突裁决）属于 **B3-2**，不在本包当前范围。
"""

from app.core.link_enrich.service import EnrichConfig, enrich_rows, fetch_one

__all__ = ["EnrichConfig", "enrich_rows", "fetch_one"]
