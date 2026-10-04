"""岗位聚合（B4-c，2026-10-03 用户拍板 **S2 + 顺序 B**）的**纯数据层**。

用户的两个决定（原话）：

1. **顺序 B（先聚合再评分）**：「方案我想是通过大模型判断，进行综合性评估，从而取其
   精华去其糟粕，合成完整的岗位画像」+「不能将聚合后的画像进行六维评分吗」——
   **对**。逐条评分再取均值有三个问题：① 成本高（每行一次画像调用）；② 1–5 分是**序数**，
   取均值不严谨；③ 信息不足的行模型会保守打 3 → 全体趋中、丧失区分度。
   所以：**先把一组招聘综合成一份"岗位综合画像卡"，再对这张卡评一次六维**。
2. **audit 优先**：综合卡必须**落库**（`job_profiles.aggregate_card`），
   且要包含 `excluded_noise`（模型显式说出它丢了什么）与 `level_objections`
   （模型对等级初判的异议）——否则"取其精华去其糟粕"无从复核。

本模块只做纯计算（分组 / 组输入拼装 / 薪资统计 / 卡片校验），**不碰 DB、不调 LLM**：

* `group_raw_rows()`   —— 把原始行按 `(归一化岗位名, 终裁等级)` 分组；
* `build_group_input()` —— 组输入拼装（带字符预算，防 prompt 爆掉）；
* `compute_salary_stats()` —— 薪资统计（用户要求"两者都存"：包络 + 中位数区间 + 原文）；
* `normalise_card()`   —— 模型输出的防御性解析（键名漂移兜底，与 `portrait_builder` 同风格）。
"""

from __future__ import annotations

import json
from collections import Counter
from statistics import median
from typing import Any

from app.core.job_agent.levels import (
    assign_levels,
    normalise_level,
    salary_bounds,
)

__all__ = [
    "CARD_LIST_KEYS",
    "CARD_TARGET_KEYS",
    "MAX_GROUP_INPUT_CHARS",
    "PER_ROW_DETAIL_CHARS",
    "PAYLOAD_EXTRACT_KEYS",
    "PAYLOAD_SOURCE_KEYS",
    "build_group_input",
    "build_payload",
    "compute_salary_stats",
    "display_title",
    "group_raw_rows",
    "normalise_card",
]

#: 写进 `job_raw_data.payload` 的**抽取结果**字段。
#: 这些字段在 `job_raw_data` 上**没有列**（表只有 title/company/city/salary/... 十列），
#: 而聚合阶段必须读到它们 —— 不落 payload 就等于聚合时无据可依。
PAYLOAD_EXTRACT_KEYS: tuple[str, ...] = (
    "hard_skills",
    "soft_skills",
    "education_requirement",
    "experience_requirement",
    "level",
    "level_basis",
)

#: 写进 `payload` 的**原始表字段**（同样没有列可放，且审计/追溯要用）。
PAYLOAD_SOURCE_KEYS: tuple[str, ...] = (
    "code",
    "source_url",
    "district",
    "company_type",
    "company_detail",
    "updated_date",
    "salary_raw",
)

#: 组内**单条**招聘喂给模型的详情字符上限
PER_ROW_DETAIL_CHARS = 300

#: 整个组输入的字符上限。超过就走 map-reduce（先分组内小批综合，再归并）。
#: 实测最大组 41 条 × ~200 字 ≈ 8,200 字，远低于此值 —— 阈值是护栏不是常态。
MAX_GROUP_INPUT_CHARS = 30_000

#: 综合卡里**期望**出现的键（缺失不算失败，但要记 warning）
CARD_TARGET_KEYS: tuple[str, ...] = (
    "role",
    "level",
    "posting_count",
    "consensus_duties",
    "consensus_requirements",
    "core_skills",
    "bonus_skills",
    "salary_range",
    "education_range",
    "experience_range",
    "city_distribution",
    "top_companies",
    "differentiators",
    "excluded_noise",
    "level_objections",
)

#: 这些键必须是**数组**（模型偶尔给字符串，下游会展示，统一成数组更省事）
CARD_LIST_KEYS: frozenset[str] = frozenset(
    {
        "consensus_duties",
        "consensus_requirements",
        "core_skills",
        "bonus_skills",
        "city_distribution",
        "top_companies",
        "differentiators",
        "excluded_noise",
        "level_objections",
    }
)


def build_payload(data: dict) -> dict:
    """把一行的「抽取结果」与「原始表字段」打包进 `payload`（供聚合阶段读取 + 审计）。"""
    extract = {key: data.get(key) for key in PAYLOAD_EXTRACT_KEYS if data.get(key) not in (None, "")}
    source = {key: data.get(key) for key in PAYLOAD_SOURCE_KEYS if data.get(key) not in (None, "")}
    return {"extract": extract, "source": source}


def _row_field(row: dict, key: str) -> Any:
    """取字段：先在行本身上找，再去 `payload.extract` / `payload.source` 里找。

    为什么两层：落库后等级/技能在 `payload` 里（没有列），而 title/salary 在列上。
    聚合时要能**用同一个函数**读这两种形态。
    """
    if row.get(key) not in (None, ""):
        return row.get(key)
    payload = row.get("payload") or {}
    for bucket in ("extract", "source"):
        value = (payload.get(bucket) or {}).get(key)
        if value not in (None, ""):
            return value
    return None


def group_raw_rows(
    rows: list[dict],
    *,
    titles: set[str] | None = None,
) -> dict[tuple[str, str], list[dict]]:
    """按 `(归一化岗位名, 终裁等级)` 分组。

    ``titles`` 给定时只处理这些 `title_key`（用于"只重算本次导入碰到的岗位"）。

    等级由 `levels.assign_levels()` 统一算出（规则 C + 文本依据 + ≥3 终裁），
    所以分组结果与"画像落到哪一条"完全一致 —— 两处各算一遍必然漂移。
    """
    if not rows:
        return {}

    # `assign_levels` 读的是 canonical 字段名；从 payload 里补回缺失的 salary/description
    prepared: list[dict] = []
    for row in rows:
        prepared.append(
            {
                "title": _row_field(row, "title"),
                "salary": _row_field(row, "salary"),
                "description": _row_field(row, "description"),
                "requirements": _row_field(row, "requirements"),
            }
        )
    levels = assign_levels(prepared)

    groups: dict[tuple[str, str], list[dict]] = {}
    for row, level_info in zip(rows, levels):
        title_key = level_info["title_key"]
        if not title_key:
            continue
        if titles is not None and title_key not in titles:
            continue
        group_level = normalise_level(level_info["group_level"])
        enriched = dict(row)
        enriched["_level"] = level_info["level"]
        enriched["_group_level"] = group_level
        enriched["_level_basis"] = level_info["level_basis"]
        groups.setdefault((title_key, group_level), []).append(enriched)
    return groups


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_group_input(
    group_rows: list[dict],
    *,
    per_row_detail_chars: int = PER_ROW_DETAIL_CHARS,
    max_chars: int = MAX_GROUP_INPUT_CHARS,
) -> str:
    """把一组的招聘拼成给模型的紧凑输入（带字符预算）。

    用**结构化字段**而不是原始 岗位详情：抽取结果已经把描述压缩到约 30%
    （实测 1979 字 → 182 字），token 省下大半，且口径统一。
    """
    lines: list[str] = []
    used = 0
    for index, row in enumerate(group_rows, start=1):
        description = str(_row_field(row, "description") or "").replace("\n", " ")
        requirements = str(_row_field(row, "requirements") or "").replace("\n", " ")
        if len(description) > per_row_detail_chars:
            description = description[:per_row_detail_chars] + "…"
        if len(requirements) > per_row_detail_chars:
            requirements = requirements[:per_row_detail_chars] + "…"

        entry = {
            "n": index,
            "岗位": _row_field(row, "title"),
            "等级初判": row.get("_level"),
            "等级依据": row.get("_level_basis"),
            "公司": _row_field(row, "company"),
            "城市": _row_field(row, "city"),
            "薪资": _row_field(row, "salary"),
            "薪资原文": _row_field(row, "salary_raw"),
            "学历": _row_field(row, "education_requirement"),
            "经验": _row_field(row, "experience_requirement"),
            "行业": _row_field(row, "industry"),
            "硬技能": _row_field(row, "hard_skills"),
            "软技能": _row_field(row, "soft_skills"),
            "岗位详情": description or None,
            "任职要求": requirements or None,
        }
        line = _compact_json({k: v for k, v in entry.items() if v not in (None, "", [], {})})
        if used + len(line) > max_chars:
            lines.append(f"…（共 {len(group_rows)} 条，其余因长度预算省略）")
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


def compute_salary_stats(group_rows: list[dict]) -> dict:
    """组内薪资统计（用户要求「两者都存」）。

    返回::

        {
          "envelope": "4000-37500",   # 区间包络：下限的最小 ~ 上限的最大
          "median": "7000-10000",     # 中位数区间
          "raw": ["1.2-1.3万", "面议", ...],   # 原始文本（去重、按出现次数排序、有上限）
          "n": 29,                     # 能解析出薪资的条数
          "negotiable": 3              # 面议条数
        }
    """
    lows: list[int] = []
    highs: list[int] = []
    raw_texts: Counter[str] = Counter()
    negotiable = 0

    for row in group_rows:
        raw = _row_field(row, "salary_raw")
        if raw:
            raw_texts[str(raw)] += 1
        bounds = salary_bounds(_row_field(row, "salary"))
        if bounds is None:
            if raw and "面议" in str(raw):
                negotiable += 1
            continue
        lows.append(bounds[0])
        highs.append(bounds[1])

    if not lows:
        return {
            "envelope": None,
            "median": None,
            "raw": [text for text, _ in raw_texts.most_common(5)],
            "n": 0,
            "negotiable": negotiable,
        }

    envelope = _render_range(min(lows), max(highs))
    median_interval = _render_range(int(median(lows)), int(median(highs)))
    return {
        "envelope": envelope,
        "median": median_interval,
        "raw": [text for text, _ in raw_texts.most_common(5)],
        "n": len(lows),
        "negotiable": negotiable,
    }


def _render_range(low: int, high: int) -> str:
    """区间渲染：下限等于上限时只给一个数（与 `_normalize_salary` 的单值写法一致）。

    否则会出现 `"5200-5200"` 这种读起来像 bug 的输出 —— 实测组内全是单值时很常见。
    """
    return str(low) if low == high else f"{low}-{high}"


def display_title(group_rows: list[dict]) -> str:
    """组内用于显示的岗位名（取出现最多的原始写法；都没有就退回首行的 key）。

    为什么要它：分组键是**归一化**后的 `title_key`（小写、空白折叠），
    直接写进 `job_profiles.title` 会变成 `java`、`app推广` 这种难看形式。
    用户明确要求「岗位名不补全」—— 那就照抄表格里的原始写法，取众数最稳。
    """
    titles = Counter(
        str(_row_field(row, "title")).strip()
        for row in group_rows
        if _row_field(row, "title")
    )
    if titles:
        return titles.most_common(1)[0][0]
    return ""


def normalise_card(data: Any, *, role: str, level: str, posting_count: int) -> tuple[dict, list[str]]:
    """模型输出的**防御性解析**：返回 `(卡片, 问题列表)`。

    与 `portrait_builder` 同风格 —— 历史教训是模型会换键名/包一层，
    只认一个名字的话下游取不到值、静默落空。

    * 非 dict → 视为不可用（问题列表给出原因）；
    * 列表键给成字符串 → 包成单元素列表；
    * 缺失的键**补空**（不算失败）但记进问题列表，便于发现"模型漏输出"；
    * `role` / `level` / `posting_count` 以**我们自己的值**为准（模型不该改身份）。
    """
    problems: list[str] = []
    if not isinstance(data, dict):
        return {}, [f"模型输出不是 JSON 对象（{type(data).__name__}）"]

    card: dict[str, Any] = {}
    for key in CARD_TARGET_KEYS:
        if key not in data:
            problems.append(f"缺少键 {key}")
            continue
        value = data[key]
        if key in CARD_LIST_KEYS:
            if value is None or value == "":
                value = []
            elif not isinstance(value, list):
                value = [value]
            card[key] = [str(item) for item in value]
        else:
            card[key] = value

    # 身份字段以调用方的值为准（模型写歪了不采纳，但要记下来）
    for key, expected in (("role", role), ("level", level), ("posting_count", posting_count)):
        actual = card.get(key)
        if actual is not None and str(actual) != str(expected):
            problems.append(f"{key} 不一致：模型给 {actual!r}，实际 {expected!r}（已按实际值落库）")
        card[key] = expected

    return card, problems
