"""列/体裁自适应：让导入管线既能吃「招聘海报」，也能吃「职业发展路线表」。

**为什么需要**（2026-09-26 实测）：用户的 `job_infor.xlsx` 是职业发展路线表
（`岗位名称 / 岗位晋升 / 换岗 / 所需证书 / 核心技能`），而管线原本只认招聘体裁的列名
（公司/城市/薪资/职位描述/任职要求）→ 84 条里 81 条被质检按"缺公司/城市/薪资"判 D 丢弃。
用户要求：**同一张表可能混着薪资、公司等字段，管线要自己检测有哪些字段再决定怎么写；
将来网页爬取自动填入也要走同一套检测与归一化。**

本模块是纯函数（不碰网络、不调 LLM）：
1. `EXTRA_COLUMN_ALIASES`：非招聘体裁的列别名 → 中间键；
2. `merge_extra_columns()`：把中间键**带中文标签**并入 `requirements` / `description`
   （混列表里本来就有 `description` 时是**追加**而不是覆盖）；
3. `normalize_rows()`：**两阶段检测** —— 先按合并前的列判"是不是职业路线表"，
   合并后再取最终字段集合，然后给出体裁，供质检选择评分口径。

> 两阶段的原因：合并会把中间键（如 `skills_detail`）并进 `requirements` 并删除，
> 合并后就再也看不出"这张表原本是职业路线表"了。

体裁取值：
- `job_posting`：有公司/城市/薪资之一，且没有职业路线特征列 → 用原「招聘信息质量」口径；
- `career_roadmap`：有职业路线特征列但没有招聘字段 → 用「按本表实际字段评估」口径；
- `mixed`：两者都有 → 同样用自适应口径；
- `unknown`：都没有（例如只有 title/description）→ 自适应口径。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

__all__ = [
    "CAREER_ROADMAP_MARKERS",
    "EXTRA_COLUMN_ALIASES",
    "MERGE_RULES",
    "RECRUITING_FIELDS",
    "SchemaProfile",
    "detect_schema",
    "merge_extra_columns",
    "merge_extra_rows",
    "normalize_rows",
]

#: 非招聘体裁的列别名 → 中间键（中间键只在本模块内使用，最终并入 requirements/description）
EXTRA_COLUMN_ALIASES: dict[str, str] = {
    "核心技能": "skills_detail",
    "技能要求": "skills_detail",
    "专业技能": "skills_detail",
    "技能清单": "skills_detail",
    "所需证书": "certificates",
    "证书要求": "certificates",
    "资格证书": "certificates",
    "证书": "certificates",
    "岗位晋升": "career_advancement",
    "晋升路径": "career_advancement",
    "晋升通道": "career_advancement",
    "换岗": "role_transition",
    "转岗": "role_transition",
    "换岗方向": "role_transition",
    "横向发展": "role_transition",
}

#: (中间键, 目标规范字段, 并入时使用的中文标签)；同一目标的多个键按声明顺序追加
MERGE_RULES: tuple[tuple[str, str, str], ...] = (
    ("skills_detail", "requirements", "核心技能"),
    ("certificates", "requirements", "所需证书"),
    ("career_advancement", "description", "岗位晋升"),
    ("role_transition", "description", "换岗方向"),
)

#: 「这张表是不是招聘表」的判据：出现任一即认为具备招聘字段
RECRUITING_FIELDS: frozenset[str] = frozenset({"company", "city", "salary"})

#: 职业发展路线的特征中间键
CAREER_ROADMAP_MARKERS: frozenset[str] = frozenset(
    {"skills_detail", "certificates", "career_advancement", "role_transition"}
)

_EMPTY: tuple[Any, ...] = (None, "", [], {})


def _present(value: Any) -> bool:
    """是否有值（`None`/空串/纯空白/空容器 视为无值）。"""
    if isinstance(value, str):
        return bool(value.strip())
    return value not in _EMPTY


def _collect_fields(rows: list[dict[str, Any]], sample: int) -> set[str]:
    """取「实际出现过非空值」的字段集合（只抽样前 sample 行：几行就够判断表结构）。"""
    fields: set[str] = set()
    for row in rows[:sample]:
        for key, value in row.items():
            if _present(value):
                fields.add(key)
    return fields


def merge_extra_columns(row: dict[str, Any]) -> dict[str, Any]:
    """把中间键带标签并入 `requirements` / `description`（不覆盖已有内容，只追加）。

    例：`{"skills_detail": "Java、Spring", "career_advancement": "全栈工程师"}`
    → `{"requirements": "核心技能：Java、Spring", "description": "岗位晋升：全栈工程师"}`

    若表里本来就有 `description`（混列表），结果是 "原描述\\n岗位晋升：…" —— 两份信息都保留。
    """
    merged = dict(row)
    for source_key, target_key, label in MERGE_RULES:
        value = merged.pop(source_key, None)
        if not _present(value):
            continue
        text = value if isinstance(value, str) else str(value)
        piece = f"{label}：{text}"
        current = merged.get(target_key)
        merged[target_key] = f"{current}\n{piece}" if _present(current) else piece
    return merged


def merge_extra_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """对整批行做中间键合并（`merge_extra_columns` 的批量版）。"""
    return [merge_extra_columns(row) for row in rows]


@dataclass(frozen=True)
class SchemaProfile:
    """一张表「长什么样」的检测结果（用于选评分口径，也可写进导入 stats 供前端展示）。"""

    fields: frozenset[str]
    genre: str
    has_recruiting_fields: bool
    has_career_markers: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "genre": self.genre,
            "fields": sorted(self.fields),
            "has_recruiting_fields": self.has_recruiting_fields,
            "has_career_markers": self.has_career_markers,
        }

    @property
    def is_job_posting(self) -> bool:
        """纯招聘体裁才用原「招聘信息质量」口径；其余（含 mixed/unknown）用自适应口径。"""
        return self.genre == "job_posting"


def _classify(fields: set[str], has_career_markers: bool) -> SchemaProfile:
    has_recruiting = bool(fields & RECRUITING_FIELDS)
    if has_recruiting and not has_career_markers:
        genre = "job_posting"
    elif has_career_markers and not has_recruiting:
        genre = "career_roadmap"
    elif has_recruiting and has_career_markers:
        genre = "mixed"
    else:
        genre = "unknown"
    return SchemaProfile(
        fields=frozenset(fields),
        genre=genre,
        has_recruiting_fields=has_recruiting,
        has_career_markers=has_career_markers,
    )


def detect_schema(rows: list[dict[str, Any]], *, sample: int = 50) -> SchemaProfile:
    """对**未合并**的行判定体裁（特征列还在，能看出来）。

    已合并过的行请用 `normalize_rows()`，否则职业路线特征已被并入 requirements/description，
    会被误判为 `unknown`。
    """
    fields = _collect_fields(rows, sample)
    return _classify(fields, bool(fields & CAREER_ROADMAP_MARKERS))


def normalize_rows(
    rows: list[dict[str, Any]], *, sample: int = 50
) -> tuple[list[dict[str, Any]], SchemaProfile]:
    """两步走：① 用合并前的列判体裁；② 合并中间键并给出最终字段集合。"""
    pre_fields = _collect_fields(rows, sample)
    merged = merge_extra_rows(rows)
    post_fields = _collect_fields(merged, sample)
    profile = _classify(post_fields, bool(pre_fields & CAREER_ROADMAP_MARKERS))
    return merged, profile
