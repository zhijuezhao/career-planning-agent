"""L1 合并层：链接值 vs 表格值 → 确定性合并（零 LLM）。

规则来自主计划 §4.3，一句话：**表格值优先，空位才用链接补，冲突只记录不改写**。

1. 表格为空 → 用链接值填充；
2. 两值都有 → **保留表格值**，链接值进 `conflicts`（绝不静默覆盖用户的原文）；
3. 枚举字段（`industry` / `level` / `education_requirement`）**先规范化再比对** ——
   否则「互联网」vs「互联网/IT」、「本科」vs「本科及以上」会被误判成冲突，把冲突
   列表刷成一堆假警报，真冲突反而被淹没；
4. 每个字段记 provenance：`form` / `link:<domain>`。

**长文本字段（`description` / `requirements`）不参与冲突判定**：两段正文永远"不相等"，
判定它们冲突没有信息量，只会让 stats 里全是噪音。它们是"空则补"，不是"冲突待裁"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.services.company_service import normalise_geo_name

#: 允许被链接值填充的字段（与 `upsert_job_profile` 读的行键一致）。
#: **刻意不含 `title`**：它是去重键（`title_key` 唯一索引），按链接标题改写会让
#: 同一个岗位在两次导入里分裂成两条记录 —— 代价远大于收益。
LINKABLE_FIELDS = (
    "company",
    "city",
    "region",
    "salary",
    "industry",
    "level",
    "education_requirement",
    "experience_requirement",
    "description",
    "requirements",
)

#: 枚举型：比对前先切词（§4.3 第 3 条）
ENUM_FIELDS = frozenset({"industry", "level", "education_requirement"})

#: 长文本：不判冲突（见模块 docstring）
NO_CONFLICT_FIELDS = frozenset({"description", "requirements"})

#: 地域字段：写库前统一成短名（与下拉选项同一套规则）
GEO_FIELDS = frozenset({"city", "region"})

_ENUM_SPLIT_RE = re.compile(r"[/、,，;；|·•\-—–\s()（）\[\]]+")

_EMPTY = (None, "", [], {})


@dataclass
class MergeOutcome:
    """合并结果。`filled` 由调用方 `row.update(...)` 应用。"""

    filled: dict[str, Any] = field(default_factory=dict)
    conflicts: list[dict] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)


def enum_tokens(value: object) -> set[str]:
    """把枚举值切成词集合："互联网/IT" → {"互联网", "it"}。"""
    if value in _EMPTY:
        return set()
    return {tok for tok in _ENUM_SPLIT_RE.split(str(value).strip().lower()) if tok}


def is_conflict(key: str, form_value: Any, link_value: Any) -> bool:
    """两个都非空时，是否算"真冲突"。

    枚举字段用**两步**判定（先包含、再切词），因为中文枚举没有统一分隔符：
    「本科及以上」切词切不开（没有 `/`、`、`），只能靠包含关系认出来。

    1. 任一字符串包含另一个 → 不冲突（`本科` ⊂ `本科及以上`）；
    2. 切词后有交集 → 不冲突（`互联网` ∩ `互联网/IT`）；
    3. 都不满足 → 冲突（`初级` vs `高级`、`大专` vs `硕士`）。
    """
    if key in NO_CONFLICT_FIELDS:
        return False
    left = " ".join(str(form_value).split()).lower()
    right = " ".join(str(link_value).split()).lower()
    if key in ENUM_FIELDS:
        if left and right and (left in right or right in left):
            return False
        return not (enum_tokens(form_value) & enum_tokens(link_value))
    return left != right


def _normalise_for_fill(key: str, value: Any) -> Any:
    """填充前归一化。

    - 地域：统一短名（与写库/下拉共用一套规则）。这一步同时承担**占位值识别** ——
      `normalise_geo_name("未知")` 返回 `None`，所以清洗阶段补的「未知」在合并看来
      等于"没有值"，链接里真实的城市才有机会填进来；
    - 长文本（description/requirements）：**只去首尾空白** —— 用 `" ".join(split())`
      会把正文的换行全压成空格，段落结构就没了（岗位描述的可读性主要靠分段）；
    - 其余短字段：压掉多余空白（表格里常见全角空格）。
    """
    if key in GEO_FIELDS:
        return normalise_geo_name(value)
    if not isinstance(value, str):
        return value
    if key in NO_CONFLICT_FIELDS:
        return value.strip()
    return " ".join(value.split()).strip()


def merge_link_fields(
    row: dict,
    link_fields: dict,
    *,
    domain: str = "",
    tier_of: dict | None = None,
) -> MergeOutcome:
    """把 `link_fields`（来自链接）合并进 `row`（表格行），返回该做什么。

    纯函数：**不改 `row`**，由调用方决定何时应用 —— 便于测试与"先统计后落库"。
    """
    outcome = MergeOutcome()
    if not isinstance(row, dict) or not isinstance(link_fields, dict):
        return outcome

    source = f"link:{domain}" if domain else "link"

    for key in LINKABLE_FIELDS:
        link_value = _normalise_for_fill(key, link_fields.get(key))
        if link_value in _EMPTY:
            continue

        # ⚠️ **表格值也要过一遍归一化**，不能直接 `row.get(key)`：
        #   1. 清洗阶段会给缺失城市补占位值「未知」（`pre_cleaner.py:281`）。若不归一化，
        #      表格侧永远"非空"→ 链接里的真实城市**永远补不进来**，还会记一条假冲突
        #      （2026-09-27 真机验收实测：form="未知" vs link="Arlington, TX" 被判冲突）；
        #   2. 写库用的是短名（`广东`），若表格里是 `广东省`，直接比对会把
        #      `广东省` vs `广东` 误判成冲突 —— 归一化后两者相等，冲突消失。
        form_value = _normalise_for_fill(key, row.get(key)) if key in GEO_FIELDS else row.get(key)
        if form_value in _EMPTY:
            # 规则 1：表格空（或只有占位值）→ 链接值填充
            outcome.filled[key] = link_value
            outcome.provenance[key] = source
            continue

        # 规则 2：表格有值 → 保留表格值；只有"真冲突"才记录
        outcome.provenance[key] = "form"
        if is_conflict(key, form_value, link_value):
            outcome.conflicts.append(
                {
                    "field": key,
                    "form": str(form_value)[:200],
                    "link": str(link_value)[:200],
                    "tier": (tier_of or {}).get(key, ""),
                }
            )

    return outcome


__all__ = [
    "ENUM_FIELDS",
    "GEO_FIELDS",
    "LINKABLE_FIELDS",
    "NO_CONFLICT_FIELDS",
    "MergeOutcome",
    "enum_tokens",
    "is_conflict",
    "merge_link_fields",
]
