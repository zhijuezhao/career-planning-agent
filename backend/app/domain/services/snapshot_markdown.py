"""画像快照 → Markdown（P1-4 下载渲染器）。

纯函数、无 IO：单测可直接喂 `SimpleNamespace`，不需要数据库，也不依赖 FastAPI。

用途与前端 `utils/preview.ts` 的 `snapshotMarkdown` **不同**：
- 这里产出的是**导出物**（带六维分数表格与原始表单附录，可存档/交付）；
- 前端那份只服务于弹窗预览（更轻，不带附录）。
"""

from __future__ import annotations

import json
from typing import Any

MAX_SECTION_CHARS = 2000
MAX_CELL_CHARS = 200
MAX_APPENDIX_CHARS = 4000
EMPTY = "（暂无）"


def render(snapshot: Any, username: str | None = None) -> str:
    """把快照对象渲染成可下载的 Markdown 文本。

    `snapshot` 用鸭子类型（读 ORM 的几个 `*_json` 属性），便于测试与复用。
    """
    serial = getattr(snapshot, "serial_no", None) or getattr(snapshot, "id", "")
    lines: list[str] = [f"# 画像快照 {serial}", ""]

    meta: list[tuple[str, Any]] = [
        ("快照ID", getattr(snapshot, "id", None)),
        ("用户ID", getattr(snapshot, "user_id", None)),
        ("用户名", username),
        ("描述", getattr(snapshot, "description", None)),
        ("生成时间", _fmt_time(getattr(snapshot, "created_at", None))),
        ("匹配状态", "已匹配" if getattr(snapshot, "matched_at", None) else "待匹配"),
        ("匹配时间", _fmt_time(getattr(snapshot, "matched_at", None))),
    ]
    for label, value in meta:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        lines.append(f"- **{label}**：{value}")

    five_layers = getattr(snapshot, "five_layers_json", None) or {}
    if five_layers:
        lines += ["", "## 五层画像", ""]
        for name, content in five_layers.items():
            lines += [f"### {name}", "", _to_markdown(content), ""]

    scores = getattr(snapshot, "six_dim_scores_json", None) or {}
    if scores:
        lines += ["## 六维分数", "", "| 维度 | 分数 |", "| --- | --- |"]
        for name, score in scores.items():
            lines.append(f"| {name} | {score} |")
        lines.append("")

    form_raw = getattr(snapshot, "form_raw_json", None) or {}
    if form_raw:
        lines += [
            "## 原始表单（附录）",
            "",
            "```json",
            _truncate(_dumps(form_raw), MAX_APPENDIX_CHARS),
            "```",
        ]

    return "\n".join(lines).strip() + "\n"


def _to_markdown(value: Any, depth: int = 0) -> str:
    """任意 JSON 值 → Markdown（对象成 `- **键**：值`，数组成列表，标量成段落）。"""
    if value is None or value == "" or value == [] or value == {}:
        return EMPTY

    indent = "  " * depth

    if isinstance(value, dict):
        parts: list[str] = []
        for key, val in value.items():
            if isinstance(val, (dict, list)):
                parts.append(f"{indent}- **{key}**：")
                parts.append(_to_markdown(val, depth + 1))
            else:
                parts.append(f"{indent}- **{key}**：{_short(val)}")
        return "\n".join(parts)

    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, (dict, list)):
                parts.append(f"{indent}-")
                parts.append(_to_markdown(item, depth + 1))
            else:
                parts.append(f"{indent}- {_short(item)}")
        return "\n".join(parts)

    return _truncate(str(value), MAX_SECTION_CHARS)


def _short(value: Any) -> str:
    return _truncate(str(value), MAX_CELL_CHARS)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…（已截断）"


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _fmt_time(value: Any) -> str | None:
    if value is None:
        return None
    formatted = getattr(value, "strftime", None)
    if callable(formatted):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)
