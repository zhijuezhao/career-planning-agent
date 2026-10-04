"""岗位等级划分（B4，2026-10-03 用户拍板 **S2 顺序 + 规则 C**）。

用户的原话与决定
----------------

1. **顺序 S2**：「先做好综合的岗位信息，然后按照规则进行划分，划分出初中高级岗位」，
   但选定的是 S2 —— 规则**先给每条招聘初判等级（带依据）**，再按 `(岗位名, 等级)`
   分组综合，最后规则**终裁**（组太小就并入「不限」）。这样等级信息不会在"先综合"
   那一步被抹平。
2. **规则 C**：绝对阈值 `6000 / 12000` 定档；**但**该岗位薪资跨度 ≥5× 时改用**该岗位
   自己的分位点**（p33 / p66）作阈值 —— 否则 `日语翻译 4000-9000` 和
   `Java 4000-37500` 用同一把尺子，日语翻译会被整体压到初级。
3. **最小样本量 ≥3**：不足 3 条的等级不单独出画像，并入「不限」。
4. **面议**：有文本依据按依据，**无依据就「不限」**（不自己编）。
5. 阈值：`<6000 初级 / 6000–12000 中级 / ≥12000 高级`。

实测数据（真实 524 行表，供复查规则是否合理）
--------------------------------------------

* 月薪下限分位：p10=3000 / p25=4000 / **p50=6000** / p75=8000 / p90=10000 / max=37500；
* 岗位内薪资跨度：`C/C++ 23.3×`、`Java 21.3×`、`前端开发 15.2×`（需校准）
  vs `档案管理 3.4×`、`实施工程师 3.3×`（绝对阈值够用）；
* 按规则 A（纯绝对阈值）分布：初级 45% / 中级 42% / 高级 8% / 不限 5% → 100 组。

⚠️ **等级是"推断"，必须可审计**：每条都产出 ``level_basis``（如 `"文本:应届"` /
`"薪资:5200→初级档"` / `"薪资:18000→岗位内p66以上"`），落进 `payload` 供人工复核。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ABS_SENIOR_MIN",
    "ABS_JUNIOR_MAX",
    "LEVEL_ADVANCED",
    "LEVEL_BASIC",
    "LEVEL_INTERMEDIATE",
    "LEVEL_UNLIMITED",
    "LEVELS",
    "MIN_GROUP_SIZE",
    "SPAN_RATIO_THRESHOLD",
    "SalaryReference",
    "assign_levels",
    "build_salary_reference",
    "classify_level",
    "finalize_group_level",
    "group_counts",
    "normalise_level",
    "salary_bounds",
]

#: 等级取值（`job_profiles.level` 是 `String(20)`，都放得下）
LEVEL_UNLIMITED = "不限"
LEVEL_BASIC = "初级"
LEVEL_INTERMEDIATE = "中级"
LEVEL_ADVANCED = "高级"
LEVELS: tuple[str, ...] = (LEVEL_BASIC, LEVEL_INTERMEDIATE, LEVEL_ADVANCED, LEVEL_UNLIMITED)

#: 绝对阈值（规则 A/C 的基准；用户 2026-10-03 选定）
ABS_JUNIOR_MAX = 6000  # < 6000 → 初级
ABS_SENIOR_MIN = 12000  # ≥ 12000 → 高级；中间 → 中级

#: 岗位内薪资跨度达到这个倍数 → 改用该岗位自己的分位点（规则 C 的校准）
SPAN_RATIO_THRESHOLD = 5.0

#: 一个等级至少要有这么多条招聘，才值得单独综合出一份画像（用户选定 ≥3）
MIN_GROUP_SIZE = 3

# ── 文本依据（最直接的等级证据）──────────────────────────────────────────────
# 顺序即优先级：先高级后初级，避免 `10年以上` 被 `1年以上` 抢先命中。
_TEXT_ADVANCED = re.compile(r"5\s*年以上|五年以上|8\s*年以上|10\s*年以上|5\s*[-~—至]\s*\d+\s*年|资深")
_TEXT_INTERMEDIATE = re.compile(r"3\s*[-~—至]\s*5\s*年|三年以上|3\s*年以上|4\s*年以上")
_TEXT_BASIC = re.compile(r"应届|实习|在校|毕业生|无经验|1\s*[-~—至]\s*3\s*年|一年以上|1\s*年以上|2\s*年以上")

_TEXT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_TEXT_ADVANCED, LEVEL_ADVANCED),
    (_TEXT_INTERMEDIATE, LEVEL_INTERMEDIATE),
    (_TEXT_BASIC, LEVEL_BASIC),
)

_RANGE = re.compile(r"(\d+)\s*-\s*(\d+)")
_SINGLE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class SalaryReference:
    """某个岗位名下的薪资参照（决定用绝对阈值还是岗位内分位点）。"""

    #: 岗位内月薪下限的最小 / 最大值（用于算跨度）
    low_min: int | None = None
    low_max: int | None = None
    #: 岗位内 p33 / p66（`use_quantiles` 为真时当阈值用）
    p33: int | None = None
    p66: int | None = None
    #: 跨度倍数（`low_max / low_min`）
    span_ratio: float | None = None
    #: 是否改用岗位内分位点（跨度 ≥ `SPAN_RATIO_THRESHOLD`）
    use_quantiles: bool = False

    def thresholds(self) -> tuple[int, int]:
        """返回 `(初级上界, 高级下界)`。"""
        if self.use_quantiles and self.p33 is not None and self.p66 is not None:
            return self.p33, self.p66
        return ABS_JUNIOR_MAX, ABS_SENIOR_MIN


def salary_bounds(normalized: object) -> tuple[int, int] | None:
    """把 `pre_cleaner._normalize_salary` 的输出解析成数值区间。

    接受的形态：`"12000-13000"` / `"9000"` / `None` / `"面议"`（后者返回 None）。
    """
    if normalized is None:
        return None
    text = str(normalized).strip()
    if not text or text in ("None", "nan", "面议"):
        return None
    match = _RANGE.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = _SINGLE.search(text)
    if match:
        value = int(match.group(1))
        return value, value
    return None


def _percentile(sorted_values: list[int], ratio: float) -> int | None:
    if not sorted_values:
        return None
    index = min(int(len(sorted_values) * ratio), len(sorted_values) - 1)
    return sorted_values[index]


def build_salary_reference(lows: list[int]) -> SalaryReference:
    """由某个岗位名下所有「月薪下限」构建参照（跨度够大就启用岗位内分位点）。"""
    values = sorted(v for v in lows if v and v > 0)
    if not values:
        return SalaryReference()

    low_min, low_max = values[0], values[-1]
    span_ratio = (low_max / low_min) if low_min > 0 else None
    use_quantiles = bool(span_ratio and span_ratio >= SPAN_RATIO_THRESHOLD)

    return SalaryReference(
        low_min=low_min,
        low_max=low_max,
        p33=_percentile(values, 1 / 3),
        p66=_percentile(values, 2 / 3),
        span_ratio=span_ratio,
        use_quantiles=use_quantiles,
    )


def _text_level(text: str | None) -> tuple[str, str] | None:
    """按文本线索定级；返回 `(等级, 依据)` 或 None。"""
    if not text:
        return None
    for pattern, level in _TEXT_RULES:
        match = pattern.search(text)
        if match:
            return level, f"文本:{match.group(0)}"
    return None


def classify_level(
    *,
    title: str | None,
    salary_normalized: object,
    description: str | None = None,
    requirements: str | None = None,
    reference: SalaryReference | None = None,
) -> tuple[str, str]:
    """给**一条招聘**定级，返回 `(等级, 依据)`。

    优先级（用户 2026-10-03：**有依据按依据、无依据就"不限"，不自己编**）：

    1. **文本依据**（岗位详情 / 任职要求里显式的年限、应届/实习）—— 最直接；
    2. **薪资依据** —— 表内原文，规则 C：跨度 ≥5× 用岗位内 p33/p66，否则用绝对阈值；
    3. 都没有 → `不限`（`level_basis="无依据"`）。
    """
    if not title or not str(title).strip():
        return LEVEL_UNLIMITED, "无岗位名"

    # ① 文本依据
    found = _text_level(description) or _text_level(requirements)
    if found is not None:
        return found

    # ② 薪资依据
    bounds = salary_bounds(salary_normalized)
    if bounds is None:
        return LEVEL_UNLIMITED, "无依据（面议/无薪资且无文本线索）"

    low = bounds[0]
    ref = reference or SalaryReference()
    junior_max, senior_min = ref.thresholds()

    if ref.use_quantiles:
        where = f"岗位内p33={junior_max}/p66={senior_min}"
    else:
        where = f"绝对阈值{junior_max}/{senior_min}"

    if low < junior_max:
        return LEVEL_BASIC, f"薪资:{low}→初级档（{where}）"
    if low >= senior_min:
        return LEVEL_ADVANCED, f"薪资:{low}→高级档（{where}）"
    return LEVEL_INTERMEDIATE, f"薪资:{low}→中级档（{where}）"


def assign_levels(
    rows: list[dict],
    *,
    title_field: str = "title",
    salary_field: str = "salary",
    description_field: str = "description",
    requirements_field: str = "requirements",
    min_group_size: int = MIN_GROUP_SIZE,
) -> list[dict]:
    """给整批行定级（按岗位名分别算薪资参照，再逐条定级）。

    Returns:
        与 `rows` 等长的列表，每项 `{"level": str, "level_basis": str,
        "title_key": str, "group_level": str, "reference": SalaryReference}`。

        `group_level` 是**终裁后**的等级：某等级不足 `min_group_size` 条时并入 `不限`
        （用户选定 ≥3）。`level` 保留初判结果，便于审计"初判 vs 终裁"的差异。
    """
    # ① 按岗位名收集月薪下限
    by_title: dict[str, list[int]] = {}
    for row in rows:
        key = _title_key(row.get(title_field))
        if not key:
            continue
        bounds = salary_bounds(row.get(salary_field))
        if bounds is not None:
            by_title.setdefault(key, []).append(bounds[0])

    references = {key: build_salary_reference(lows) for key, lows in by_title.items()}

    # ② 逐条初判
    results: list[dict] = []
    for row in rows:
        key = _title_key(row.get(title_field))
        level, basis = classify_level(
            title=row.get(title_field),
            salary_normalized=row.get(salary_field),
            description=row.get(description_field),
            requirements=row.get(requirements_field),
            reference=references.get(key),
        )
        results.append(
            {
                "level": level,
                "level_basis": basis,
                "title_key": key,
                "group_level": level,  # 终裁前先等于初判
                "reference": references.get(key),
            }
        )

    # ③ 终裁：不足 min_group_size 的等级并入「不限」（「不限」是兜底，永远保留）
    counts = group_counts([(r["title_key"], r["level"]) for r in results])
    for result in results:
        key, level = result["title_key"], result["level"]
        if not key or level == LEVEL_UNLIMITED:
            continue
        if counts.get((key, level), 0) < min_group_size:
            result["group_level"] = LEVEL_UNLIMITED
            result["level_basis"] = (
                f"{result['level_basis']}；该等级仅 {counts.get((key, level), 0)} 条"
                f"（<{min_group_size}）→ 并入「不限」"
            )

    return results


def finalize_group_level(count: int, level: str) -> str:
    """单个 `(岗位名, 等级)` 组的终裁结果（供调用方在别处复用同一规则）。"""
    if level == LEVEL_UNLIMITED:
        return LEVEL_UNLIMITED
    return level if count >= MIN_GROUP_SIZE else LEVEL_UNLIMITED


def normalise_level(value: object) -> str:
    """把任意来源的等级值收敛到 `LEVELS` 之一；认不出来的一律 `不限`。

    为什么必须有（B4）：岗位唯一键现在是 `(title_key, level)`，落库前若不收敛，
    任何自由文本（`3-5年`、`高级工程师`、`senior`）都会各建一条画像 ——
    等于把刚做好的等级分层又炸开。宁可落到「不限」也不要创造新档位。
    """
    if value is None:
        return LEVEL_UNLIMITED
    text = " ".join(str(value).split()).strip()
    if not text or text.lower() in ("none", "nan", "null", "-"):
        return LEVEL_UNLIMITED
    if text in LEVELS:
        return text
    # 常见别名（表格/模型可能写成这些）
    aliases = {
        "实习": LEVEL_BASIC,
        "应届": LEVEL_BASIC,
        "entry": LEVEL_BASIC,
        "junior": LEVEL_BASIC,
        "mid": LEVEL_INTERMEDIATE,
        "middle": LEVEL_INTERMEDIATE,
        "senior": LEVEL_ADVANCED,
        "高级工程师": LEVEL_ADVANCED,
        "中级工程师": LEVEL_INTERMEDIATE,
        "初级工程师": LEVEL_BASIC,
    }
    return aliases.get(text.lower(), aliases.get(text, LEVEL_UNLIMITED))


def group_counts(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """统计 `(岗位名, 等级)` 的条数。"""
    counts: dict[tuple[str, str], int] = {}
    for key, level in pairs:
        if not key:
            continue
        counts[(key, level)] = counts.get((key, level), 0) + 1
    return counts


def _title_key(title: object) -> str:
    """与 `dedup_keys.normalise_title` 同口径（落库唯一键就是它）。"""
    from app.core.dedup_keys import normalise_title

    return normalise_title(title)
