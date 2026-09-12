from __future__ import annotations

import re

from langchain_core.tools import tool
from loguru import logger

# Common industry name normalisation map
INDUSTRY_NORMALISATION: dict[str, str] = {
    "互联网": "互联网/IT",
    "移动互联网": "互联网/IT",
    "互联网/电子商务": "互联网/IT",
    "电子商务": "互联网/IT",
    "计算机软件": "互联网/IT",
    "计算机硬件": "互联网/IT",
    "计算机服务": "互联网/IT",
    "IT服务": "互联网/IT",
    "软件开发": "互联网/IT",
    "软件": "互联网/IT",
    "通信/电信": "通信/电信",
    "通信技术": "通信/电信",
    "电子技术": "电子/半导体",
    "半导体": "电子/半导体",
    "金融": "金融",
    "银行": "金融",
    "证券": "金融",
    "保险": "金融",
    "基金": "金融",
    "教育": "教育/培训",
    "培训": "教育/培训",
    "医疗": "医疗/医药",
    "医药": "医疗/医药",
    "制药": "医疗/医药",
    "房地产": "房地产/建筑",
    "建筑": "房地产/建筑",
    "物业管理": "房地产/建筑",
    "制造业": "制造/工业",
    "制造": "制造/工业",
    "汽车": "汽车/制造",
    "汽车制造": "汽车/制造",
    "消费品": "消费品/零售",
    "零售": "消费品/零售",
    "贸易": "贸易/进出口",
    "进出口": "贸易/进出口",
    "物流": "物流/运输",
    "运输": "物流/运输",
    "能源": "能源/化工",
    "化工": "能源/化工",
    "农业": "农业/林业",
    "文化传媒": "文化/传媒",
    "传媒": "文化/传媒",
    "广告": "文化/传媒",
    "酒店": "酒店/旅游",
    "旅游": "酒店/旅游",
    "法律": "法律/咨询",
    "咨询": "法律/咨询",
    "专业服务": "法律/咨询",
    "会计": "财务/审计",
    "审计": "财务/审计",
    "人力资源": "人力资源/猎头",
    "猎头": "人力资源/猎头",
    "政府": "政府/公共事业",
    "非营利": "政府/公共事业",
    "环保": "能源/化工",
}

# Regex patterns for salary parsing.
# Order matters: more specific patterns (with explicit unit indicators) come first.
SALARY_PATTERNS = [
    # 年薪: 20万-30万/年, 20-30万/年, 200000-300000/年
    (re.compile(r"(\d+[\d.]*)\s*[万wW]\s*[-~—至]\s*(\d+[\d.]*)\s*[万wW]?\s*[/年]*", re.UNICODE), "yearly", 1.0),
    (re.compile(r"(\d+[\d.]*)\s*[-~—至]\s*(\d+[\d.]*)\s*[万wW]\s*[/年]*", re.UNICODE), "yearly", 1.0),
    # 年薪 single: 20万/年, 200000/年 (requires at least 万 or /年 indicator)
    (re.compile(r"(\d+[\d.]*)\s*[万wW]\s*[/年]*$", re.UNICODE), "yearly_single", 1.0),
    (re.compile(r"(\d+[\d.]*)\s*[/年]$", re.UNICODE), "yearly_single", 1.0),
    # 日薪: 500-800元/天 (must come before generic monthly)
    (re.compile(r"(\d+[\d.]*)\s*[-~—至]\s*(\d+[\d.]*)\s*元?/天", re.UNICODE), "daily", 22.0),
    (re.compile(r"(\d+[\d.]*)\s*元?/天", re.UNICODE), "daily_single", 22.0),
    # 时薪: 50-80元/时 (must come before generic monthly)
    (re.compile(r"(\d+[\d.]*)\s*[-~—至]\s*(\d+[\d.]*)\s*元?/时", re.UNICODE), "hourly", 176.0),
    (re.compile(r"(\d+[\d.]*)\s*元?/时", re.UNICODE), "hourly_single", 176.0),
    # 月薪: 10K-15K, 10-15K
    (re.compile(r"(\d+[\d.]*)\s*[kK]\s*[-~—至]\s*(\d+[\d.]*)\s*[kK]?", re.UNICODE), "monthly_k", 1000.0),
    (re.compile(r"(\d+[\d.]*)\s*[-~—至]\s*(\d+[\d.]*)\s*[kK]\s*[/月]*", re.UNICODE), "monthly_k", 1000.0),
    # 月薪 with /月 indicator: 15000-25000元/月
    (re.compile(r"(\d+[\d.]*)\s*[-~—至]\s*(\d+[\d.]*)\s*[/月]", re.UNICODE), "monthly", 1.0),
    # 月薪 single with /月: 15000元/月, 10K/月
    (re.compile(r"(\d+[\d.]*)\s*[kK]?\s*[/月]", re.UNICODE), "monthly_single", 1.0),
    # Fallback: bare number range (no unit indicator, assumed monthly)
    (re.compile(r"(\d+[\d.]*)\s*[-~—至]\s*(\d+[\d.]*)", re.UNICODE), "monthly", 1.0),
    # Fallback: bare single number
    (re.compile(r"(\d+[\d.]*)$", re.UNICODE), "monthly_single", 1.0),
]

# K-suffix multiplier for single values
K_MULTIPLIER = 1000.0
WAN_MULTIPLIER = 10000.0


def _remove_html_tags(text: str | None) -> str | None:
    """Remove HTML tags, especially <br> tags."""
    if text is None:
        return None
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fix_none_address(row: dict) -> dict:
    """Fill None/empty city field with a default value."""
    if not row.get("city") or str(row["city"]).strip() in ("", "None", "nan", "无"):
        row["city"] = "未知"
    return row


def _clean_industry(industry: str | None, custom_map: dict[str, str] | None = None) -> str | None:
    """Normalise industry name using a canonical mapping.

    Tries exact match, then substring match, then returns the original value.
    """
    if not industry or str(industry).strip() in ("", "None", "nan", "无"):
        return None

    industry = industry.strip()

    # Build merged map
    norm_map = dict(INDUSTRY_NORMALISATION)
    if custom_map:
        norm_map.update(custom_map)

    # Exact match
    if industry in norm_map:
        return norm_map[industry]

    # Substring match (pick longest matching key)
    matched_key = ""
    for key in norm_map:
        if key in industry and len(key) > len(matched_key):
            matched_key = key

    if matched_key:
        return norm_map[matched_key]

    return industry


def _parse_salary_value(value_str: str) -> float:
    """Parse a salary value string, handling K and 万 suffixes."""
    value_str = value_str.strip().upper().replace("K", "").replace("W", "").replace("万", "")
    try:
        return float(value_str)
    except ValueError:
        return 0.0


def _normalize_salary(salary_str: str | None) -> str | None:
    """Normalise salary string to monthly range format 'min-max'.

    Handles 4 original formats: 月薪, 年薪, 日薪, 时薪.
    Returns None for unparseable or '面议' values.
    """
    if not salary_str or str(salary_str).strip() in ("", "None", "nan", "无"):
        return None

    salary_str = salary_str.strip()

    # 薪资面议
    if "面议" in salary_str:
        return None

    # Try each pattern
    for pattern, fmt, multiplier in SALARY_PATTERNS:
        match = pattern.search(salary_str)
        if not match:
            continue

        if fmt in ("yearly", "monthly_k", "monthly", "daily", "hourly"):
            # Range format
            v1 = _parse_salary_value(match.group(1))
            v2 = _parse_salary_value(match.group(2))
            if fmt == "yearly":
                # 年薪 → convert to monthly
                min_val = round(v1 * WAN_MULTIPLIER / 12)
                max_val = round(v2 * WAN_MULTIPLIER / 12)
            elif fmt == "daily":
                min_val = round(v1 * multiplier)
                max_val = round(v2 * multiplier)
            elif fmt == "hourly":
                min_val = round(v1 * multiplier)
                max_val = round(v2 * multiplier)
            elif fmt == "monthly_k":
                min_val = round(v1 * multiplier)
                max_val = round(v2 * multiplier)
            else:
                min_val = round(v1)
                max_val = round(v2)

            if min_val > max_val:
                min_val, max_val = max_val, min_val

            if min_val == max_val:
                return str(min_val)
            return f"{min_val}-{max_val}"

        else:
            # Single value format
            v = _parse_salary_value(match.group(1))
            if fmt == "yearly_single":
                v = round(v * WAN_MULTIPLIER / 12)
            elif fmt == "daily_single":
                v = round(v * multiplier)
            elif fmt == "hourly_single":
                v = round(v * multiplier)
            elif fmt == "monthly_single":
                v = round(v)  # already monthly

            return str(v)

    return salary_str


@tool
async def clean_job_data(
    rows: list[dict],
    industry_custom_map: dict[str, str] | None = None,
) -> dict:
    """Apply rule-based cleaning to job data rows.

    Performs the following cleaning operations on each row:
    - Remove HTML tags (especially <br>) from all text fields
    - Fill empty city values with '未知'
    - Normalise industry names to a canonical set
    - Convert salary to monthly range format (min-max)

    Args:
        rows: List of job data dicts (from load_excel_data).
        industry_custom_map: Optional custom industry normalisation overrides.

    Returns:
        Dict with total (int), cleaned_rows (list[dict]), and stats (dict)
        reporting counts of each cleaning operation applied.
    """
    logger.info("Cleaning job data | rows={}", len(rows))

    stats = {
        "html_tags_removed": 0,
        "city_fixed": 0,
        "industry_normalised": 0,
        "salary_normalised": 0,
        "salary_cleared": 0,  # 面议 → None
    }

    text_fields = {"title", "company", "city", "industry", "description", "requirements", "salary"}

    cleaned_rows: list[dict] = []
    for row in rows:
        cleaned = dict(row)

        # HTML tag removal for all text fields
        for field in text_fields:
            if field in cleaned and isinstance(cleaned[field], str):
                original = cleaned[field]
                cleaned[field] = _remove_html_tags(cleaned[field])
                if cleaned[field] != original:
                    stats["html_tags_removed"] += 1

        # Fix None address
        if not cleaned.get("city") or str(cleaned["city"]).strip() in ("", "None", "nan", "无"):
            cleaned["city"] = "未知"
            stats["city_fixed"] += 1

        # Industry normalisation
        if "industry" in cleaned or any(k in cleaned for k in ("industry", "所属行业", "行业")):
            ind_key = "industry" if "industry" in cleaned else ("所属行业" if "所属行业" in cleaned else "行业")
            orig_ind = cleaned[ind_key]
            normalised = _clean_industry(orig_ind, industry_custom_map)
            if normalised != orig_ind:
                cleaned[ind_key] = normalised
                stats["industry_normalised"] += 1

        # Salary normalisation
        if "salary" in cleaned:
            orig_salary = cleaned["salary"]
            normalised = _normalize_salary(orig_salary)
            if normalised is None and orig_salary is not None and str(orig_salary).strip() not in ("", "None", "nan"):
                stats["salary_cleared"] += 1
            elif normalised != orig_salary:
                stats["salary_normalised"] += 1
            cleaned["salary"] = normalised

        cleaned_rows.append(cleaned)

    logger.info("Cleaning complete | stats={}", stats)
    return {"total": len(cleaned_rows), "cleaned_rows": cleaned_rows, "stats": stats}
