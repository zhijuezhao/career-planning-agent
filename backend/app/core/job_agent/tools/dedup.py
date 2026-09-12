from __future__ import annotations

from difflib import SequenceMatcher

from langchain_core.tools import tool
from loguru import logger


def _normalise(text: str | None) -> str:
    """Normalise a string for comparison."""
    if not text:
        return ""
    return text.strip().lower()


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


def _fuzzy_dedup(
    rows: list[dict],
    threshold: float = 0.85,
    company_field: str = "company",
    title_field: str = "title",
    city_field: str = "city",
) -> tuple[list[dict], int]:
    """Remove fuzzy duplicates by company+title+city similarity.

    Returns (deduped rows, number of duplicates removed).
    """
    deduped: list[dict] = []
    removed = 0

    for row in rows:
        is_dup = False
        row_company = _normalise(row.get(company_field))
        row_title = _normalise(row.get(title_field))
        row_city = _normalise(row.get(city_field))

        for existing in deduped:
            existing_company = _normalise(existing.get(company_field))
            existing_title = _normalise(existing.get(title_field))
            existing_city = _normalise(existing.get(city_field))

            # Same city
            if row_city != existing_city:
                continue

            # Same company (exact match)
            if row_company and existing_company and row_company != existing_company:
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

    Performs two-stage deduplication:
    1. Exact dedup by job code (e.g. 岗位编码) — removes rows with the same code.
    2. Fuzzy dedup by company + title + city — removes rows with the same company
       and city where titles are similar above the threshold.

    Args:
        rows: List of job data dicts.
        code_field: Field name for exact dedup (default "code").
        fuzzy_threshold: Similarity threshold for fuzzy title matching (0.0-1.0, default 0.85).
        company_field: Field name for company (default "company").
        title_field: Field name for job title (default "title").
        city_field: Field name for city (default "city").

    Returns:
        Dict with total (int), deduped_rows (list[dict]),
        exact_dedup_count (int), and fuzzy_dedup_count (int).
    """
    logger.info(
        "Deduplicating jobs | rows={} | fuzzy_threshold={}",
        len(rows),
        fuzzy_threshold,
    )

    # Stage 1: exact dedup
    after_exact, exact_removed = _exact_dedup(rows, code_field)
    logger.info("Exact dedup | before={} | after={} | removed={}", len(rows), len(after_exact), exact_removed)

    # Stage 2: fuzzy dedup
    after_fuzzy, fuzzy_removed = _fuzzy_dedup(
        after_exact,
        threshold=fuzzy_threshold,
        company_field=company_field,
        title_field=title_field,
        city_field=city_field,
    )
    logger.info(
        "Fuzzy dedup | before={} | after={} | removed={}",
        len(after_exact),
        len(after_fuzzy),
        fuzzy_removed,
    )

    return {
        "total": len(after_fuzzy),
        "deduped_rows": after_fuzzy,
        "exact_dedup_count": exact_removed,
        "fuzzy_dedup_count": fuzzy_removed,
    }
