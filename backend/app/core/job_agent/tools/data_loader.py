from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool
from loguru import logger

from app.core.job_agent.tools.schema_detect import (
    EXTRA_COLUMN_ALIASES,
    normalize_rows,
)

DEFAULT_COLUMN_MAPPING: dict[str, str] = {
    "岗位名称": "title",
    "职位名称": "title",
    "公司名称": "company",
    "企业名称": "company",
    "工作城市": "city",
    "工作地点": "city",
    "城市": "city",
    "薪资": "salary",
    "薪酬": "salary",
    "工资": "salary",
    "行业": "industry",
    "所属行业": "industry",
    "职位描述": "description",
    "岗位描述": "description",
    "工作描述": "description",
    "任职要求": "requirements",
    "岗位要求": "requirements",
    "职位要求": "requirements",
    "岗位编码": "code",
    "职位编码": "code",
    "职位ID": "code",
    # ── 岗位↔公司 多对多模型（2026-09-27）需要的列 ────────────────────────────────
    # 地域做成**省市两级**（管理端先选省、再选市）；省份与城市分开识别，别只认「城市」。
    "省份": "region",
    "省": "region",
    "所在省份": "region",
    "所在地区": "region",
    "地区": "region",
    "地域": "region",
    # 公司规模（存原文，如 `1000-9999人`）
    "公司规模": "scale",
    "企业规模": "scale",
    "人员规模": "scale",
    "规模": "scale",
    # 原始链接（B3 链接富化与「岗位来源」展示要用）
    "岗位链接": "source_url",
    "职位链接": "source_url",
    "招聘链接": "source_url",
    "详情链接": "source_url",
    "来源链接": "source_url",
    "链接": "source_url",
    "URL": "source_url",
    "url": "source_url",
    # ── 2026-10-03：真实比赛数据表（12 列原始结构）暴露出的别名缺口 ──────────────
    # 这份表里 `薪资范围`/`岗位详情`/`岗位来源地址`/`地址`/`公司类型`/`公司详情`/`更新日期`
    # **全部非空但一列都没命中** → 薪资清洗整段被跳过、岗位详情（435 个不同值）进不了
    # 提取阶段、`<br>` 不清洗、城市被统一填成「未知」。补别名是这批修复的第一要务。
    "地址": "city",  # 形如「上海-杨浦区」，清洗阶段会拆成 城市 + 区县
    "薪资范围": "salary",
    "月薪": "salary",
    "岗位详情": "description",
    "岗位职责": "description",
    "职位详情": "description",
    "岗位来源地址": "source_url",
    "来源地址": "source_url",
    # 裸「公司」也认：`company` 是关键字段。注意 `公司规模`/`公司类型`/`公司详情`/
    # `公司性质` 都有更长的**精确**别名护航（精确优先于包含），不会被它抢走。
    "公司": "company",
    "公司类型": "company_type",
    "公司性质": "company_type",
    "公司详情": "company_detail",
    "企业详情": "company_detail",
    "更新日期": "updated_date",
    # 这两个是**规范字段名本身**（`job_profiles.education_requirement` /
    # `experience_requirement`），表格里直接就叫这个时别当未知列丢掉。
    "学历要求": "education_requirement",
    "经验要求": "experience_requirement",
    "任职资格": "requirements",
    "具体岗位要求": "requirements",
}

#: 列名归一化时忽略的字符（空白 / 下划线 / 连字符 / 全半角括号 / 斜杠 / 标点等）。
_COLUMN_KEY_NOISE = re.compile(r"[\s_\-（）()【】\[\]{}:：/、,，.。·]+")

#: 参与「包含匹配」的最短别名长度。
#: 单字别名（`省`）做包含匹配会大面积误伤（`省市区`、`省份说明`…），所以不放行。
_MIN_CONTAINMENT_ALIAS_LEN = 2


def _normalise_column_key(text: object) -> str:
    """列名归一化（仅用于**比较**）：去噪字符 + 转小写。"""
    return _COLUMN_KEY_NOISE.sub("", str(text)).lower()


def resolve_column(column: str, mapping: dict[str, str]) -> tuple[str | None, str, str | None]:
    """三层列名解析：① 精确 → ② 包含（最长别名优先）→ ③ 未命中。

    返回 ``(规范字段名 | None, 层级, 命中的别名)``，层级取值
    ``"exact"`` / ``"containment"`` / ``"ambiguous"`` / ``"unmapped"``。

    为什么要「包含匹配」（用户 2026-10-03 要求）：表格列名千奇百怪，
    `公司薪资` / `月薪资范围` / `薪资待遇` 都该落到 `salary`，
    不该因为多/少一个字就整列静默丢失。

    ⚠️ **精确优先是必须的**，否则这几组会互相误伤：

    - `地址` ↔ `岗位来源地址`（city vs source_url）
    - `公司名称` ↔ `公司类型` / `公司详情`（company vs company_type/company_detail）

    ⚠️ **只做「别名 ⊂ 列名」一个方向**：反方向（列名 `详情` ⊂ 别名 `公司详情`）
    会把 `详情` 误判成 `company_detail`，所以不做。

    ⚠️ 同长歧义的处理：取**出现位置更靠后**的别名。中文复合词的中心语在后，
    所以 `公司薪资` → `薪资` → salary、`公司地址` → `地址` → city、
    `公司城市` → `城市` → city。只有连位置都相同（= 两条别名归一化后同名却指向
    不同字段，属于**别名表自身写冲突**）才判 ``ambiguous`` 并拒绝映射 —— 这道兜底
    是为了将来有人往别名表里加重复定义时不要静默取错，而不是常见路径。
    """
    if column in mapping:  # ① 精确
        return mapping[column], "exact", column

    key = _normalise_column_key(column)
    if not key:
        return None, "unmapped", None

    # (别名长度, 出现结束位置, 别名, 规范字段)
    hits: list[tuple[int, int, str, str]] = []
    for alias, field in mapping.items():
        alias_key = _normalise_column_key(alias)
        if len(alias_key) < _MIN_CONTAINMENT_ALIAS_LEN:
            continue
        pos = key.find(alias_key)
        if pos >= 0:  # ② 包含（别名 ⊂ 列名）
            hits.append((len(alias_key), pos + len(alias_key), alias, field))

    if not hits:
        return None, "unmapped", None

    hits.sort(key=lambda item: (-item[0], -item[1]))
    best = hits[0]
    tied = [h for h in hits if h[0] == best[0] and h[1] == best[1]]
    if len({h[3] for h in tied}) > 1:  # 同长且同位置 → 真歧义，拒绝
        return None, "ambiguous", None
    return best[3], "containment", best[2]


def _detect_engine(file_path: str) -> str:
    """Detect pandas Excel engine from file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".xls":
        return "xlrd"
    if ext in (".xlsx", ".xlsm"):
        return "openpyxl"
    msg = f"Unsupported file extension: {ext}. Expected .xls or .xlsx."
    raise ValueError(msg)


def _build_column_mapping(columns: list[str], mapping: dict[str, str]) -> dict[str, str]:
    """Build a mapping from actual DataFrame columns to canonical field names.

    三层解析（精确 → 包含 → 未命中），**未命中列保留原名**（不丢数据）。
    返回类型保持 ``dict[str, str]``，调用方与既有测试不受影响。
    """
    result: dict[str, str] = {}
    for col in columns:
        field, _tier, _via = resolve_column(col, mapping)
        result[col] = field or col
    return result


def _normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
    """去首尾空白，并把空单元格统一成 None。

    Excel 的空单元格会被 pandas 读成 NaN（float）。原样往下传会踩两个坑：
    1. 去重阶段 `_normalise()` 里 `if not text` 拦不住 NaN（`bool(nan)` 是 True），
       随后 `text.strip()` 抛 `'float' object has no attribute 'strip'` ——
       实测让整单导入在 33% 处失败；
    2. `json.dumps(row)` 会把 NaN 写成 `NaN`，严格 JSON 不允许，送进 LLM 提示词是隐患。
    """
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    return df.astype(object).where(df.notna(), None)


def _load_excel_sync(file_path: str, sheet_name: str | int, nrows: int | None) -> list[dict]:
    """Synchronous Excel loading via pandas."""
    engine = _detect_engine(file_path)
    df = pd.read_excel(file_path, sheet_name=sheet_name, engine=engine, nrows=nrows, dtype=str)
    return _normalise_frame(df).to_dict(orient="records")


def _load_csv_sync(file_path: str, nrows: int | None) -> list[dict]:
    """Synchronous CSV loading via pandas.

    先按 UTF-8（含 BOM）读取，遇编码错误再回退 GBK —— 中文导出的 CSV
    常见 GBK 编码。仅编码错误触发回退，其它异常（文件损坏、空文件等）
    直接抛出，由上层转成可见错误。
    """
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            df = pd.read_csv(
                file_path,
                nrows=nrows,
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
            )
            return _normalise_frame(df).to_dict(orient="records")
        except UnicodeDecodeError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _load_rows_sync(file_path: str, sheet_name: str | int, nrows: int | None) -> list[dict]:
    """按扩展名分派读取实现（S7-2：新增 .csv 分支）。"""
    if Path(file_path).suffix.lower() == ".csv":
        return _load_csv_sync(file_path, nrows)
    return _load_excel_sync(file_path, sheet_name, nrows)


def read_raw_table(
    file_path: str,
    sheet_name: str | int = 0,
    nrows: int | None = None,
) -> tuple[list[str], list[dict]]:
    """读**原始**表格（**不做列名映射**）：返回 `(列名, 行字典)`。

    B3 切片要在「映射之前」按原始列把小片写出去，这样每片仍是一张**自解释的表**
    （管理员能直接打开看是哪几行），处理时再走同一套映射 + 清洗 + 去重。
    与 `load_excel_data` 共用同一个读取实现，避免两处解析规则漂移。
    """
    rows = _load_rows_sync(file_path, sheet_name, nrows)
    columns = list(rows[0].keys()) if rows else []
    return columns, rows


@tool
async def load_excel_data(
    file_path: str,
    sheet_name: str | int = 0,
    nrows: int | None = None,
    column_mapping: dict[str, str] | None = None,
) -> dict:
    """Load job data from an Excel or CSV file.

    Reads .xls (xlrd engine) / .xlsx (openpyxl engine) / .csv (pandas, UTF-8
    with GBK fallback) files and returns job records as a list of dictionaries.
    Column names are normalised to canonical field names via a built-in mapping.

    Args:
        file_path: Absolute or relative path to the Excel/CSV file.
        sheet_name: Sheet name or 0-based index (default 0 = first sheet).
                    Ignored for CSV files.
        nrows: Maximum number of rows to read (default None = all rows).
        column_mapping: Optional override mapping of columns to canonical
                        field names. Merged over the default mapping.

    Returns:
        Dict with keys: total (int), rows (list[dict]), columns (list[str]),
        schema (dict: 体裁与字段检测结果 —— 见 `schema_detect`).
        On failure: {"total": 0, "rows": [], "columns": [], "error": str}.
    """
    logger.info("Loading job data file | path={}", file_path)

    # 基线映射（招聘体裁）+ 非招聘体裁的列别名（职业发展路线表等）
    merged_mapping = dict(DEFAULT_COLUMN_MAPPING)
    merged_mapping.update(EXTRA_COLUMN_ALIASES)
    if column_mapping:
        merged_mapping.update(column_mapping)

    try:
        raw_rows: list[dict] = await asyncio.to_thread(
            _load_rows_sync, file_path, sheet_name, nrows
        )
    except Exception as e:
        logger.error("Failed to load job data file | path={} | error={}", file_path, e)
        return {"total": 0, "rows": [], "columns": [], "error": str(e)}

    if not raw_rows:
        return {"total": 0, "rows": [], "columns": []}

    columns = list(raw_rows[0].keys())
    col_mapping = _build_column_mapping(columns, merged_mapping)

    # 列匹配可见性（2026-10-03）：未命中的列**必须留下痕迹**。
    # 原实现静默保留原名，于是 `薪资范围`/`岗位详情`/`岗位来源地址` 等 7 个非空列
    # 在 524 行文件里一条都没进流水线，管理员却看不到任何异常。
    column_match: list[dict] = []
    for col in columns:
        field, tier, via = resolve_column(col, merged_mapping)
        column_match.append({
            "column": col,
            "field": field or col,
            "tier": tier,
            "via": via,
        })
    unmapped = [c["column"] for c in column_match if c["tier"] != "exact" and c["tier"] != "containment"]
    if unmapped:
        logger.warning(
            "Import: 有列未识别，将按原名保留（请确认是否需要补别名）| columns={}", unmapped
        )

    mapped_rows: list[dict] = []
    for row in raw_rows:
        mapped = {col_mapping.get(k, k): v for k, v in row.items()}
        mapped_rows.append(mapped)

    # 归一化 + 体裁检测（A 层）：
    # 把 `核心技能/所需证书/岗位晋升/换岗` 之类带标签并入 requirements/description，
    # 并给出「这张表是招聘海报还是职业发展路线表」——质检据此选评分口径（B 层）。
    normalized_rows, schema = normalize_rows(mapped_rows)

    logger.info(
        "Job data loaded | path={} | total={} | columns={} | schema={}",
        file_path,
        len(normalized_rows),
        columns,
        schema.as_dict(),
    )
    return {
        "total": len(normalized_rows),
        "rows": normalized_rows,
        "columns": columns,
        "schema": schema.as_dict(),
        # 列匹配轨迹（B3 导入预检要用：管理员先看「哪列没认出来」再决定是否跑 LLM）
        "column_match": column_match,
    }
