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

# ── 薪资归一化（2026-10-03 用户拍板重写）─────────────────────────────────────
#
# 规则（按优先级）：
#   1. 空 / `面议`                    → None
#   2. 单位倍数：`万` ×10000，`K/k` ×1000，否则 ×1
#   3. 周期倍数：`/天` ×22，`/时` ×176，否则 ×1
#   4. `N薪` → ×(N/12)
#   5. **显式年化**（出现 `年薪` / `/年` / `每年`）→ ÷12
#
# ⚠️ 裸 `X-Y万` **按月薪**处理（×10000，**不 ÷12**）。
#    旧实现（13 条正则）把带 `万` 的范围一律当年薪 ÷12 —— 实测让这份 524 行表里
#    **70 行薪资错 12 倍**（`1.2-1.3万` → `1000-1083`，真实应为 `12000-13000`）。
#    更糟的是质检模型会自己发现这个矛盾并据此扣分（实测「薪资信息」只给 10~40 分），
#    把本该 B 级的行压成 C 级 —— 所以这不只是数据准确性问题，而是画像质量问题。
#
# 为什么改成「先剥单位字符、再取数字」而不是继续堆正则：
#    旧写法对 `20万-30万/年`（两侧都带「万」）必须专门写一条正则，漏一条就整类失配。
#    先把 `万/K/元` 从待解析文本里去掉、只留纯数字区间，单位由**独立判定**得到，
#    组合数是 3（单位）× 3（周期）× 显式年化，而不是 13 条互斥正则。
_DAILY_FACTOR = 22.0  # 月工作日
_HOURLY_FACTOR = 176.0  # 月工时
_WAN_MULTIPLIER = 10000.0
_K_MULTIPLIER = 1000.0

#: 显式年化的标志（只有这些才 ÷12）
_YEARLY_HINT = re.compile(r"年薪|每年|/\s*年|年\s*薪")
#: `13薪` / `14薪` 的月数
_MONTHS_HINT = re.compile(r"(\d+)\s*薪")
#: 数字区间（分隔符覆盖 - ~ — 至 到）
_NUM_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—至到]\s*(\d+(?:\.\d+)?)")
#: 单个数字
_NUM_SINGLE = re.compile(r"(\d+(?:\.\d+)?)")
#: 取数字前要剥掉的单位字符（`万`/`元`/`K` 由独立判定处理）
_UNIT_CHARS = str.maketrans("", "", "万元kK ")


def _normalize_salary(salary_str: str | None) -> str | None:
    """把薪资文本归一化成**月薪区间** `"min-max"`（单值时只给一个数）。

    返回 ``None`` 表示「没有可用薪资」（空值或 `面议`）；无法解析的原文**原样返回**
    （宁保留原文让人看见，也不要丢掉）。

    规则见模块内 `_normalize_salary` 上方的注释块。
    """
    if not salary_str or str(salary_str).strip() in ("", "None", "nan", "无"):
        return None

    text = str(salary_str).strip()

    # 1) 薪资面议 → 视为没有薪资
    if "面议" in text:
        return None

    # 2) 单位倍数
    if "万" in text:
        scale = _WAN_MULTIPLIER
    elif re.search(r"\d\s*[kK]", text):
        scale = _K_MULTIPLIER
    else:
        scale = 1.0

    # 3) 周期倍数
    if "天" in text:
        period = _DAILY_FACTOR
    elif "时" in text:
        period = _HOURLY_FACTOR
    else:
        period = 1.0

    # 4) N 薪（月数折算）
    months = 1.0
    months_match = _MONTHS_HINT.search(text)
    if months_match:
        months = float(months_match.group(1)) / 12.0

    # 5) 显式年化才 ÷12
    year_div = 12.0 if _YEARLY_HINT.search(text) else 1.0

    # 剥掉单位字符后取数字（这样 `20万-30万/年` 与 `20-30万/年` 走同一条路径）
    numeric = text.translate(_UNIT_CHARS)

    rng = _NUM_RANGE.search(numeric)
    if rng:
        low = float(rng.group(1)) * scale * period * months / year_div
        high = float(rng.group(2)) * scale * period * months / year_div
    else:
        single = _NUM_SINGLE.search(numeric)
        if not single:
            return text  # 解析不了 → 原样保留
        low = high = float(single.group(1)) * scale * period * months / year_div

    low_i, high_i = round(low), round(high)
    if low_i > high_i:  # 写反了（`10K-8K`）→ 换回来
        low_i, high_i = high_i, low_i

    return str(low_i) if low_i == high_i else f"{low_i}-{high_i}"


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


#: 地址第二段（区县）里的**脏值**：这些不是区县名。
#: 实测来源：导出工具把空的区县写成字面 `None`（本表 17 行）。
_ADDRESS_DISTRICT_NOISE = frozenset(
    {"none", "nan", "null", "无", "未知", "不限", "-", "--", "—", "/", "其他", ""}
)


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


def _split_address(value: object) -> tuple[str | None, str | None]:
    """把「城市-区县」拆成 ``(城市, 区县)``；脏值段当「没有」。

    实测（2026-10-03）这份 524 行表里 `地址` 有 **17 行**形如 `常德-None` / `杭州-None`：
    `None` 是导出工具留下的**字面字符串**，不是区县名。原样保留会让城市变成
    `常德-None`，与地域下拉选项永远对不上（用户要求「输出纯城市名」）。

    同时把 `区县` 单独取出来（`job_company_links` 没有区县列，先留在行里，
    由 B4 的 `payload` 归档；将来要按区县筛选就有现成数据）。
    """
    if value is None:
        return None, None
    text = " ".join(str(value).split()).strip()
    if not text or text.lower() in _ADDRESS_DISTRICT_NOISE:
        return None, None
    if "-" not in text:
        return text, None

    parts = [p.strip() for p in text.split("-")]
    city = parts[0] or None
    district = "-".join(p for p in parts[1:] if p and p.lower() not in _ADDRESS_DISTRICT_NOISE)
    return city, (district or None)


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
        "city_cleaned": 0,  # 地址成功拆出「纯城市名」（可能同时得到区县）
        "district_extracted": 0,  # 区县有效并已单独取出
        "city_fixed": 0,
        "industry_normalised": 0,
        "salary_normalised": 0,
        "salary_cleared": 0,  # 面议 → None
        "skipped_no_title": 0,  # 分类标题行/缺岗位名 → 直接丢弃
    }

    text_fields = {"title", "company", "city", "industry", "description", "requirements", "salary"}

    cleaned_rows: list[dict] = []
    for row in rows:
        cleaned = dict(row)

        # 丢弃没有岗位名称的行（2026-09-26）。
        # 用户的表格常用分组标题行（如「测试类」「人工智能/算法类」）来分区，这类行只有
        # 序号、岗位名称为空 —— 它们不是岗位数据，若继续走后面 3 次 LLM（质检/提取/画像）
        # 既白烧 token，又会生成垃圾画像。实测 `job_infor.xlsx` 有 2 行这种标题行。
        title = cleaned.get("title")
        if not str(title or "").strip() or str(title).strip() in ("None", "nan"):
            stats["skipped_no_title"] += 1
            logger.debug("Skip row without title | row={}", str(row)[:120])
            continue

        # HTML tag removal for all text fields
        for field in text_fields:
            if field in cleaned and isinstance(cleaned[field], str):
                original = cleaned[field]
                cleaned[field] = _remove_html_tags(cleaned[field])
                if cleaned[field] != original:
                    stats["html_tags_removed"] += 1

        # 地址规范化（2026-10-03）：`城市-区县` 拆开、丢掉脏区县（`常德-None` → `常德`）。
        # 放在「HTML 清洗之后、行业归一之前」，因为它产出 `city` 与 `district` 两个字段。
        raw_city = cleaned.get("city")
        city, district = _split_address(raw_city)
        if city:
            if str(city) != str(raw_city):
                stats["city_cleaned"] += 1
            cleaned["city"] = city
            if district:
                cleaned["district"] = district
                stats["district_extracted"] += 1
        else:
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

        # Salary normalisation（主值 = 折算后的月薪区间）
        if "salary" in cleaned:
            orig_salary = cleaned["salary"]
            normalised = _normalize_salary(orig_salary)
            if normalised is None and orig_salary is not None and str(orig_salary).strip() not in ("", "None", "nan"):
                stats["salary_cleared"] += 1
            elif normalised != orig_salary:
                stats["salary_normalised"] += 1
            cleaned["salary"] = normalised
            # **保留原文**（用户 2026-10-03 拍板：主值 ×N/12、同时保留原始文本）。
            # `salary` 会被折算值覆盖，原文是审计「折算对不对」的唯一依据
            # （如 `1.2-1.3万` → `12000-13000` 是否合理、`·13薪` 有没有被算进去）。
            if orig_salary not in (None, "", "None", "nan"):
                cleaned["salary_raw"] = orig_salary

        cleaned_rows.append(cleaned)

    logger.info("Cleaning complete | stats={}", stats)
    return {"total": len(cleaned_rows), "cleaned_rows": cleaned_rows, "stats": stats}
