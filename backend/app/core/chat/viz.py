"""可视化（``viz``）载荷的契约与构造 —— C1（§11.1 的 ⑤）。

一个 viz 描述**一种视觉**，前端按 ``kind`` 分发：

- ``kind`` ∈ ``radar | bar | line | pie`` → 用 ``option``（**ECharts option**）。
  后端直接产 option 是本项目既有惯例（见 ``core/resume_agent/visualization.build_radar_option``），
  前端只负责把它塞进 ``<EChart>``。
- ``kind == "table"`` → 用 ``columns`` + ``rows``（纯表格，不需要 ECharts）。

约定：
- 一条助手消息可以有**多个** viz —— ``chat_messages.viz`` 存 JSONB **数组**，
  SSE 逐个发 ``{"type": "viz", ...}``。
- viz 一律是**纯数据**（可 JSON 序列化、可直接落库），不含 ORM 对象。
- 前端遇到不认识的 ``kind`` 就跳过 —— 与既有 SSE 兼容策略一致
  （HANDOFF 约定 9：学生端 switch 无 default 分支，未知事件类型被忽略）。
"""

from __future__ import annotations

from typing import Any, Literal

#: 前端按这个值分发渲染器
VizKind = Literal["radar", "bar", "line", "pie", "table"]

#: 需要 ECharts 渲染的 kind（其余是纯表格）
ECHARTS_KINDS: frozenset[str] = frozenset({"radar", "bar", "line", "pie"})

TABLE_KIND = "table"


def echarts_viz(kind: str, title: str, option: dict[str, Any]) -> dict[str, Any]:
    """ECharts 类 viz（``radar`` / ``bar`` / ``line`` / ``pie``）。

    Args:
        kind: 必须是 ``ECHARTS_KINDS`` 之一（写错直接抛，避免产出前端渲染不了的载荷）。
        title: 图题（与 ECharts option 里的 title 分开，前端负责显示，避免重复）。
        option: ECharts option。
    """
    if kind not in ECHARTS_KINDS:
        raise ValueError(f"不是 ECharts 类 kind：{kind!r}（可选 {sorted(ECHARTS_KINDS)}）")
    return {"kind": kind, "title": title, "option": option}


def table_viz(title: str, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    """表格类 viz（不需要 ECharts）。"""
    return {
        "kind": TABLE_KIND,
        "title": title,
        "columns": list(columns),
        "rows": [list(row) for row in rows],
    }


def bar_option(categories: list[str], values: list[int], *, series_name: str = "数量") -> dict[str, Any]:
    """柱状图 option，只用到 admin ``components/EChart.vue`` **已注册**的组件。

    即 ``BarChart`` + ``Grid/Tooltip`` —— 所以 C1 端到端**不需要**再往那个组件里加注册项。
    """
    return {
        "grid": {"left": 56, "right": 24, "top": 24, "bottom": 96},
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "data": list(categories),
            "axisLabel": {"interval": 0, "rotate": 38, "fontSize": 11},
        },
        "yAxis": {"type": "value", "minInterval": 1},
        "series": [
            {
                "name": series_name,
                "type": "bar",
                "data": list(values),
                "barMaxWidth": 32,
                "itemStyle": {"color": "#409eff"},
            }
        ],
    }


def is_valid_viz(item: Any) -> bool:
    """单条 viz 的合法性（落库/下发前的最后一道闸，防止工作流写出脏载荷）。"""
    if not isinstance(item, dict):
        return False
    kind = item.get("kind")
    if kind == TABLE_KIND:
        return isinstance(item.get("columns"), list) and isinstance(item.get("rows"), list)
    if kind in ECHARTS_KINDS:
        return isinstance(item.get("option"), dict)
    return False


def normalise_viz(raw: Any) -> list[dict[str, Any]]:
    """把任意输入收敛成「合法 viz 列表」：``None`` → ``[]``，非法项直接丢掉（不抛错）。"""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [item for item in items if is_valid_viz(item)]


__all__ = [
    "ECHARTS_KINDS",
    "TABLE_KIND",
    "VizKind",
    "bar_option",
    "echarts_viz",
    "is_valid_viz",
    "normalise_viz",
    "table_viz",
]
