from __future__ import annotations

from difflib import SequenceMatcher

from langchain_core.tools import tool
from loguru import logger

from app.core.dedup_keys import (
    job_dedup_key,
    normalise_company_name,
    normalise_source_url,
    normalise_title,
)


def _normalise(text: object) -> str:
    """Normalise a value for comparison.

    空值一律当空串：`float('nan')`（Excel 空单元格经 pandas 读入后的形态）是
    **truthy**，`if not text` 拦不住它，随后 `text.strip()` 会抛
    `'float' object has no attribute 'strip'`，直接炸掉整单导入（实测）。
    """
    if text is None:
        return ""
    value = str(text).strip().lower()
    return "" if value in ("nan", "none") else value


def _similar(a: str, b: str) -> float:
    """Compute string similarity ratio."""
    return SequenceMatcher(None, _normalise(a), _normalise(b)).ratio()


def _identity_key(
    row: dict,
    code_field: str = "code",
    url_field: str = "source_url",
) -> tuple[str, str] | None:
    """每条招聘的**唯一标识**：`("code", 岗位编码)` 优先，其次 `("url", 去查询串的链接)`。

    都没有才返回 ``None``（该行将回落到「(岗位名, 公司) + 模糊」两级去重）。

    为什么优先级是「编码 → 链接」（用户 2026-10-03 拍板）：
    岗位编码是本表自带的稳定主键（实测 524 行里 487 个唯一值，与链接**严格 1:1**）；
    链接虽然也能唯一标识，但带导出会话参数（见 `normalise_source_url`），
    且更长短更易变，所以只作次选。
    """
    code = str(row.get(code_field) or "").strip()
    if code and code not in ("None", "nan"):
        return ("code", code)

    url = normalise_source_url(row.get(url_field))
    if url:
        return ("url", url)

    return None


def _is_fuzzy_duplicate(
    row: dict,
    candidates: list[dict],
    threshold: float,
    company_field: str,
    title_field: str,
    city_field: str,
) -> bool:
    """`row` 是否与 `candidates` 里某一行「同公司 + 近似岗位名」（P2 口径）。

    规则（与旧实现的差别写在下面，只有这一处实现，避免逻辑漂移）：

    * **公司不同 → 直接不是同一个岗位**（新粒度下是两条画像）；
    * **城市「两边都有且不同」才否决**：旧实现要求城市完全相等，于是一张只有部分行
      带城市的表会出现"同公司同名、一个有城市一个没有"被判成两个岗位；
    * **公司只有一边有时不否决**（"未知"不等于"另一家"）。
    """
    row_company = normalise_company_name(row.get(company_field)) or ""
    row_title = normalise_title(row.get(title_field))
    row_city = _normalise(row.get(city_field))

    for existing in candidates:
        existing_company = normalise_company_name(existing.get(company_field)) or ""
        existing_title = normalise_title(existing.get(title_field))
        existing_city = _normalise(existing.get(city_field))

        # 两边都写了公司且不同 → 不是同一个岗位（新粒度：同岗不同公司保留两条）
        if row_company and existing_company and row_company != existing_company:
            continue

        # 两边都写了城市且不同 → 不是同一个岗位；只有一边有城市则不否决
        if row_city and existing_city and row_city != existing_city:
            continue

        if row_title and existing_title and _similar(row_title, existing_title) >= threshold:
            return True

    return False


#: 单阶段删除比例超过这个值就在结果里报「告警」（0.5 = 50%）。
#
# 为什么需要（2026-10-03）：真实事故里 `(岗位名, 公司)` 一级把 100 行删成 1 行
# （删掉 99%），工单却报 `completed` + `success_count=1`，管理员**看不到任何异常**。
# 护栏不阻止删除（有些表确实几乎全重复），但必须让"删了很多"这件事显式可见。
_MAX_STAGE_REMOVAL_RATIO = 0.5


def _removal_alerts(stages: list[tuple[str, int, int]]) -> list[str]:
    """把「某阶段删得太多」折算成可读告警（``(阶段名, 输入行数, 删除行数)``）。"""
    alerts: list[str] = []
    for name, before, removed in stages:
        if before > 0 and removed / before > _MAX_STAGE_REMOVAL_RATIO:
            alerts.append(
                f"{name} 阶段删除 {removed}/{before} 行"
                f"（>{_MAX_STAGE_REMOVAL_RATIO:.0%}），请确认表内是否确实大量重复"
            )
    return alerts


@tool
async def deduplicate_jobs(
    rows: list[dict],
    code_field: str = "code",
    fuzzy_threshold: float = 0.85,
    company_field: str = "company",
    title_field: str = "title",
    city_field: str = "city",
    url_field: str = "source_url",
) -> dict:
    """Remove duplicate job records.

    **标识优先**的三级去重（2026-10-03 用户拍板，改造自旧的三阶段实现）：

    1. **按唯一标识去重**：`岗位编码`（`code_field`）→ `岗位来源地址`（`url_field`，
       会去掉查询串）。有标识的行到此为止 —— **跳过**后面两级。
    2. **`(岗位名, 公司)` 精确去重**：只对**没有唯一标识**的行生效。
    3. **同公司内近似岗位名模糊去重**：同样只对没有唯一标识的行生效。

    为什么改成这样（真实事故）：用户的 524 行表有 `岗位编码`（487 个唯一值），
    但旧实现第 1 级只按 `code` 去重（524→487 正确），**紧接着第 2 级又按
    `(岗位名, 公司)` 把 487 行并成 384 行** —— 被并掉的 103 行编码各不相同、
    城市/日期也不同（如美团把「APP推广」投在 8 个城市），是**独立的真实招聘**。
    更极端的一次：4366 行、`岗位名称` 只有 9 个类别且无公司列 → 第 2 级把 100 行
    并成 **1 行**，工单却报 `completed`。

    Args:
        rows: List of job data dicts.
        code_field: 唯一编码列（默认 `code`）。
        fuzzy_threshold: 模糊去重阈值（0.0-1.0，默认 0.85）。
        company_field: 公司列（默认 `company`）。
        title_field: 岗位名列（默认 `title`）。
        city_field: 城市列（默认 `city`）。
        url_field: 来源链接列（默认 `source_url`）。

    Returns:
        Dict with total (int), deduped_rows (list[dict]),
        exact_dedup_count / title_company_dedup_count / fuzzy_dedup_count (int,
        **键名保持兼容**，语义见下), identity_count (有唯一标识的行数),
        unidentified_count (无标识、走了第 2/3 级的行数),
        以及 dedup_alerts (list[str]，单阶段删除比例过高时的告警)。
    """
    logger.info(
        "Deduplicating jobs | rows={} | fuzzy_threshold={}",
        len(rows),
        fuzzy_threshold,
    )

    deduped: list[dict] = []
    seen_identity: set[tuple[str, str]] = set()
    seen_title_company: set[tuple[str, str]] = set()
    #: 无标识且已保留的行 —— 供模糊去重比对（有标识的行不参与模糊比对）
    unidentified_kept: list[dict] = []

    identity_removed = 0
    key_removed = 0
    fuzzy_removed = 0
    identity_count = 0

    for row in rows:
        identity = _identity_key(row, code_field, url_field)

        # ── 第 1 级：唯一标识（命中即跳过后面两级）─────────────────────────
        if identity is not None:
            identity_count += 1
            if identity in seen_identity:
                identity_removed += 1
                continue
            seen_identity.add(identity)
            deduped.append(row)
            continue

        # ── 第 2 级：(岗位名, 公司) 精确（仅无标识行）──────────────────────
        key = job_dedup_key(row.get(title_field), row.get(company_field))
        if key[0]:  # 没有岗位名：不在这里吞掉，交给清洗/质检去管
            if key in seen_title_company:
                key_removed += 1
                continue
            seen_title_company.add(key)

        # ── 第 3 级：同公司内近似岗位名（仅无标识行）───────────────────────
        if _is_fuzzy_duplicate(
            row, unidentified_kept, fuzzy_threshold, company_field, title_field, city_field
        ):
            fuzzy_removed += 1
            continue

        unidentified_kept.append(row)
        deduped.append(row)

    logger.info(
        "Identity dedup | with_identity={} | removed={}",
        identity_count,
        identity_removed,
    )
    logger.info(
        "Title+company/fuzzy dedup (无标识行) | unidentified={} | tc_removed={} | fuzzy_removed={}",
        len(unidentified_kept) + key_removed + fuzzy_removed,
        key_removed,
        fuzzy_removed,
    )

    alerts = _removal_alerts(
        [
            ("按唯一标识去重", len(rows), identity_removed),
            ("(岗位名, 公司) 精确去重", len(rows) - identity_removed, key_removed),
            ("模糊去重", len(rows) - identity_removed, fuzzy_removed),
        ]
    )
    if alerts:
        logger.warning("去重删除比例过高 | alerts={}", alerts)

    return {
        "total": len(deduped),
        "deduped_rows": deduped,
        # 键名保持兼容：`exact_dedup_count` 现在是「按唯一标识（编码/链接）删除数」
        "exact_dedup_count": identity_removed,
        "title_company_dedup_count": key_removed,
        "fuzzy_dedup_count": fuzzy_removed,
        # 新增可观测字段
        "identity_count": identity_count,
        "unidentified_count": len(unidentified_kept) + key_removed + fuzzy_removed,
        "dedup_alerts": alerts,
    }
