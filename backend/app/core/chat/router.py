"""意图路由（§11.1 的 ②）—— C1 只做 **L1 规则层**。

链路::

    ① 输入安全闸门（确定性）
    ② 本模块：
         L1 规则 / 关键词 / 实体抽取（**0 token**）→ 命中即走确定型工作流，**不进 agent**
         L2 embedding 相似度（**本轮未实现**，§11.4 的 P3 范围只到 L1）
         L3 都没中 → 既有 ReAct agent（**零行为变化**）
    ③ 输出合规    ④ 可视化

**规则是故意写窄的** —— 只认「纯目录 / 纯分布」这类**没有过滤条件**的问法
（例如「有哪些岗位」）。带条件的（例如「现在有哪些前端岗位」）**故意不命中**，理由是：

1. 要抢走它，就得用规则去硬解析"前端"这种过滤条件 —— 那是 P4/C2 真正做 ``job_search``
   时该干的事，现在硬解析只会做出一半正确的结果；
2. 不命中 = 行为与 C1 之前**逐字一致**，不会悄悄改掉既有测试与线上表现。

所以 ``route()`` 是**纯函数**（无 I/O、不读 DB、不碰模型），可以直接在单测里断言。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class L1Rule:
    """一条 L1 规则：正则命中 → 走 ``workflow``，并可抽取参数。"""

    name: str
    workflow: str
    patterns: tuple[str, ...]
    #: 静态参数（直接并进工作流入参）
    params: dict[str, Any] = field(default_factory=dict)
    #: 实体抽取：正则捕获组序号 → 参数名（如「前 20 个岗位」里的 20）
    captures: dict[int, str] = field(default_factory=dict)


#: L1 规则表。**顺序即优先级，第一条命中即返回。**
L1_RULES: tuple[L1Rule, ...] = (
    L1Rule(
        name="job_catalog.count",
        workflow="job_catalog",
        patterns=(
            r"^(现在|目前|当前)?(一共|总共)?有(多少|几)(个)?岗位",
            r"岗位(一共|总共)?有(多少|几)(个)",
        ),
        params={"mode": "list"},
    ),
    L1Rule(
        name="job_catalog.list.limit",
        workflow="job_catalog",
        patterns=(r"^(列出|看看|展示|给我)?前\s*(\d+)\s*个?岗位",),
        params={"mode": "list"},
        # 第 2 个捕获组是条数（第 1 个是可选动词）
        captures={2: "limit"},
    ),
    L1Rule(
        name="job_catalog.list",
        workflow="job_catalog",
        patterns=(
            r"岗位(列表|清单)",
            # 结尾锚定：`现在有哪些前端岗位` 因为中间多了「前端」而**不会**命中
            r"^(现在|目前|当前)?有(哪些|什么)岗位[？?！!。.\s]*$",
            r"^(列出|看看|展示|给我)(全部|所有)?岗位",
        ),
        params={"mode": "list"},
    ),
    L1Rule(
        name="job_catalog.distribution",
        workflow="job_catalog",
        patterns=(
            r"岗位(分布|大类|类别|分类)",
            r"^(现在|目前|当前)?有(哪些|什么)(方向|大类|类别|分类)",
            r"岗位.*(方向|类别|大类).*(分布|统计)",
        ),
        params={"mode": "distribution"},
    ),
)


@dataclass(frozen=True)
class RouteDecision:
    """路由结论。``layer == "L3"`` 表示"没命中任何工作流，交给 agent"。"""

    layer: str
    workflow: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    rule: str | None = None

    @property
    def is_workflow(self) -> bool:
        """是否命中确定型工作流（True 时**不许**建 agent、不许调模型）。"""
        return self.workflow is not None


def route(message: str) -> RouteDecision:
    """L1 路由：纯函数、无 I/O、0 token。未命中 → ``RouteDecision(layer="L3")``。"""
    text = (message or "").strip()
    if not text:
        return RouteDecision(layer="L3")

    for rule in L1_RULES:
        for pattern in rule.patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is None:
                continue

            params: dict[str, Any] = dict(rule.params)
            for group, key in rule.captures.items():
                raw = match.group(group)
                if raw is None:
                    continue
                params[key] = int(raw) if raw.isdigit() else raw

            return RouteDecision(
                layer="L1",
                workflow=rule.workflow,
                params=params,
                rule=rule.name,
            )

    return RouteDecision(layer="L3")


__all__ = ["L1_RULES", "L1Rule", "RouteDecision", "route"]
