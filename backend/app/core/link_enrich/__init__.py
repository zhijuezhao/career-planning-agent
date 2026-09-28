"""Link Enrich：表格里的链接 → 抓取 → 结构化提取 → 确定性合并。

主计划 §4.1 的五层闸门，本包已实现到 L3（**L4 未做**，理由见计划 §31.1）：

| 模块 | 层 | token | 职责 |
|---|---|---|---|
| `urls` | L0 | 0 | 正则扫字段值里的 URL，规范化、按域名分组 |
| `safety` | — | 0 | 抓取前的 SSRF 守卫（公网判定；逐跳复检由 `fetch` 执行） |
| `fetch` | L1 | 0 | httpx 抓取（有界读取、逐跳复检）+ `link_fetch_cache` 缓存 |
| `extract` | L1 | 0 | JSON-LD(JobPosting) → og/meta → 正文，逐级降级 |
| `xpath` | L2/L3 | 0 | 候选定位式生成、**白名单校验**、应用 |
| `templates` | L2 | 0 | `link_xpath_templates` 的读写（命中/未命中、自愈覆盖） |
| `llm_extract` | L3 | **贵** | 让模型从候选菜单里**挑**定位式（每域一次） |
| `budget` | — | — | L3 的调用数/token 闸门 |
| `merge` | — | 0 | 表格值优先的确定性合并 + provenance + 冲突记录 |
| `service` | — | — | 编排、预算、统计（供导入流水线与 C4 工具共用） |

**两个开关**：`LINK_ENRICH_ENABLED`（总开关，默认关）与 `LINK_ENRICH_LLM_ENABLED`
（只关 L3，默认关）。零成本层（L0/L1/L2）可以单独开 —— L2 复用已学模板是零成本的，
不受 LLM 开关约束。

**L4（模型裁决表格值 vs 链接值）未实现**：它是全流程唯一会让模型改掉用户表格里已有
值的环节，而目前没有真实冲突样本可供判断质量，故留待后续（用户裁决）。
"""

from app.core.link_enrich.service import EnrichConfig, enrich_rows, fetch_one

__all__ = ["EnrichConfig", "enrich_rows", "fetch_one"]
