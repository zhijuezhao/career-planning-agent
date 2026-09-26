from __future__ import annotations

from difflib import SequenceMatcher

from langchain_core.tools import tool
from loguru import logger

from app.core.dedup_keys import job_dedup_key, normalise_company_name, normalise_title


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


def _exact_dedup(rows: list[dict], code_field: str = "code") -> tuple[list[dict], int]:
    """Remove exact duplicates by job code field.

    Returns (deduped rows, number of duplicates removed).
    """
    seen_codes: set[str] = set()
    deduped: list[dict] = []
    removed = 0

    for row in rows:
        code = str(row.get(code_field, "")).strip()
        if code and code not in ("None", "nan", ""):
            if code in seen_codes:
                removed += 1
                continue
            seen_codes.add(code)
        deduped.append(row)

    return deduped, removed


def _exact_dedup_by_title_company(
    rows: list[dict],
    company_field: str = "company",
    title_field: str = "title",
) -> tuple[list[dict], int]:
    """按 `(归一化岗位名, 归一化公司)` 精确去重（P2，0 token、确定性优先）。

    与落库粒度（`job_profiles.title_key` + `company_id`）对齐：同一个文件里
    "同岗位同名公司"是重复行；"同岗位不同公司"**保留**（新粒度下是两条画像）。
    公司为空的行按"未知公司"处理 —— 与已知公司**不**视为同一行，
    避免把"某公司的 Java 岗"和"没写公司的 Java 岗"提前合并掉（落库层会收养，见 §17）。
    """
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    removed = 0

    for row in rows:
        key = job_dedup_key(row.get(title_field), row.get(company_field))
        if not key[0]:  # 没有岗位名：交给后面的清洗/质检去管，不在这里吞掉
            deduped.append(row)
            continue
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        deduped.append(row)

    return deduped, removed


def _fuzzy_dedup(
    rows: list[dict],
    threshold: float = 0.85,
    company_field: str = "company",
    title_field: str = "title",
    city_field: str = "city",
) -> tuple[list[dict], int]:
    """按"同公司内近似岗位名"模糊去重（P2 调整）。

    与旧实现的区别（旧口径是 §15 之前的"公司+岗位+城市"）：

    * **公司不同 → 直接不是同一个岗位**（新粒度下是两条画像），旧实现只在
      "两边公司都非空且不同"时跳过，这里保持一致；
    * **城市改成"两边都有且不同才否决"**：旧实现要求城市完全相等，
      一旦某张表只有部分行带城市，就会出现"同公司同名、一个有城市一个没有"被判成两个岗位；
    * 公司只有一边有时**不**否决（"未知"不等于"另一家"）。
    """
    deduped: list[dict] = []
    removed = 0

    for row in rows:
        is_dup = False
        row_company = normalise_company_name(row.get(company_field)) or ""
        row_title = normalise_title(row.get(title_field))
        row_city = _normalise(row.get(city_field))

        for existing in deduped:
            existing_company = normalise_company_name(existing.get(company_field)) or ""
            existing_title = normalise_title(existing.get(title_field))
            existing_city = _normalise(existing.get(city_field))

            # 两边都写了公司且不同 → 不是同一个岗位（新粒度：同岗不同公司保留两条）
            if row_company and existing_company and row_company != existing_company:
                continue

            # 两边都写了城市且不同 → 不是同一个岗位；只有一边有城市则不否决
            if row_city and existing_city and row_city != existing_city:
                continue

            # Similar title
            if row_title and existing_title:
                similarity = _similar(row_title, existing_title)
                if similarity >= threshold:
                    is_dup = True
                    break

        if is_dup:
            removed += 1
        else:
            deduped.append(row)

    return deduped, removed


@tool
async def deduplicate_jobs(
    rows: list[dict],
    code_field: str = "code",
    fuzzy_threshold: float = 0.85,
    company_field: str = "company",
    title_field: str = "title",
    city_field: str = "city",
) -> dict:
    """Remove duplicate job records.

    Performs three-stage deduplication:
    1. Exact dedup by job code (e.g. 岗位编码) — removes rows with the same code.
    2. Exact dedup by `(岗位名, 公司)`（P2 起与落库粒度一致）—— 归一化后完全相同即重复。
    3. Fuzzy dedup within the same company — titles similar above the threshold.

    Args:
        rows: List of job data dicts.
        code_field: Field name for exact dedup (default "code").
        fuzzy_threshold: Similarity threshold for fuzzy title matching (0.0-1.0, default 0.85).
        company_field: Field name for company (default "company").
        title_field: Field name for job title (default "title").
        city_field: Field name for city (default "city").

    Returns:
        Dict with total (int), deduped_rows (list[dict]),
        exact_dedup_count (int), title_company_dedup_count (int),
        and fuzzy_dedup_count (int).
    """
    logger.info(
        "Deduplicating jobs | rows={} | fuzzy_threshold={}",
        len(rows),
        fuzzy_threshold,
    )

    # Stage 1: exact dedup by job code
    after_exact, exact_removed = _exact_dedup(rows, code_field)
    logger.info("Exact dedup | before={} | after={} | removed={}", len(rows), len(after_exact), exact_removed)

    # Stage 2: exact dedup by (title, company) —— P2：与落库键同粒度
    after_key, key_removed = _exact_dedup_by_title_company(
        after_exact, company_field=company_field, title_field=title_field
    )
    logger.info(
        "Title+company dedup | before={} | after={} | removed={}",
        len(after_exact),
        len(after_key),
        key_removed,
    )

    # Stage 3: fuzzy dedup（同公司内近似岗位名）
    after_fuzzy, fuzzy_removed = _fuzzy_dedup(
        after_key,
        threshold=fuzzy_threshold,
        company_field=company_field,
        title_field=title_field,
        city_field=city_field,
    )
    logger.info(
        "Fuzzy dedup | before={} | after={} | removed={}",
        len(after_key),
        len(after_fuzzy),
        fuzzy_removed,
    )

    return {
        "total": len(after_fuzzy),
        "deduped_rows": after_fuzzy,
        "exact_dedup_count": exact_removed,
        "title_company_dedup_count": key_removed,
        "fuzzy_dedup_count": fuzzy_removed,
    }
