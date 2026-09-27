from __future__ import annotations

import asyncio
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
}


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

    For each column in the DataFrame, look up the mapping. Unknown columns
    are kept as-is.
    """
    result: dict[str, str] = {}
    for col in columns:
        result[col] = mapping.get(col, col)
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
    }
