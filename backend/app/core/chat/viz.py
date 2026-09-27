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


#: 雷达图默认量程（六维都是 1–5 分）
RADAR_MAX = 5

#: 多序列配色（与 bar_option 的主色同一族，前端不再自己配色）
RADAR_COLORS: tuple[str, ...] = ("#409eff", "#67c23a", "#e6a23c", "#f56c6c", "#909399")


def radar_option(
    dimensions: list[str],
    series: dict[str, list[float]],
    *,
    max_value: float = RADAR_MAX,
) -> dict[str, Any]:
    """多序列雷达图 option（P5：六维对比）。

    Args:
        dimensions: 轴（六维名，顺序即轴顺序 —— 传 `DIMENSION_ORDER` 保证两侧同序）。
        series: `{序列名: 各维分数}`。**同名序列只出现一次**，顺序即图例顺序。
        max_value: 量程上限（默认 5）。

    Returns:
        ECharts option。只用 ``RadarChart`` + ``Radar/Legend/Tooltip`` ——
        admin ``components/EChart.vue`` 已注册这四项（2026-09-27 P5 补的，
        此前**没注册 Radar**，图会静默不渲染）。

    ⚠️ **缺维**：某序列没有某一维的分时**传 `None`**（ECharts 会断开），
    **不要**用 0 顶替 —— 0 在雷达上会被读成"这一维极差"，而事实是"没有可比数据"。
    """
    if not dimensions:
        raise ValueError("radar_option 需要至少一个维度")

    indicators = [{"name": dim, "max": max_value} for dim in dimensions]
    data = []
    for index, (name, values) in enumerate(series.items()):
        if len(values) != len(dimensions):
            raise ValueError(
                f"序列 {name!r} 的分值个数（{len(values)}）与维度数（{len(dimensions)}）不一致"
            )
        data.append(
            {
                "name": name,
                "value": list(values),
                "itemStyle": {"color": RADAR_COLORS[index % len(RADAR_COLORS)]},
                "areaStyle": {"opacity": 0.12},
            }
        )

    return {
        "tooltip": {"trigger": "item"},
        "legend": {"bottom": 0, "data": list(series)},
        "radar": {
            "indicator": indicators,
            "radius": "62%",
            "center": ["50%", "46%"],
            "axisName": {"fontSize": 11},
        },
        "series": [{"type": "radar", "data": data}],
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
    "RADAR_COLORS",
    "RADAR_MAX",
    "TABLE_KIND",
    "VizKind",
    "bar_option",
    "echarts_viz",
    "is_valid_viz",
    "normalise_viz",
    "radar_option",
    "table_viz",
]
