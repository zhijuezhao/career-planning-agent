from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool
from loguru import logger

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


def _load_excel_sync(file_path: str, sheet_name: str | int, nrows: int | None) -> list[dict]:
    """Synchronous Excel loading via pandas."""
    engine = _detect_engine(file_path)
    df = pd.read_excel(file_path, sheet_name=sheet_name, engine=engine, nrows=nrows, dtype=str)
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    return df.to_dict(orient="records")


@tool
async def load_excel_data(
    file_path: str,
    sheet_name: str | int = 0,
    nrows: int | None = None,
    column_mapping: dict[str, str] | None = None,
) -> dict:
    """Load job data from an Excel file.

    Reads .xls (xlrd engine) or .xlsx (openpyxl engine) files and returns
    job records as a list of dictionaries. Column names are normalised to
    canonical field names via a built-in mapping.

    Args:
        file_path: Absolute or relative path to the Excel file.
        sheet_name: Sheet name or 0-based index (default 0 = first sheet).
        nrows: Maximum number of rows to read (default None = all rows).
        column_mapping: Optional override mapping of Excel columns to canonical
                        field names. Merged over the default mapping.

    Returns:
        Dict with keys: total (int), rows (list[dict]), columns (list[str]).
    """
    logger.info("Loading Excel file | path={}", file_path)

    merged_mapping = dict(DEFAULT_COLUMN_MAPPING)
    if column_mapping:
        merged_mapping.update(column_mapping)

    try:
        raw_rows: list[dict] = await asyncio.to_thread(
            _load_excel_sync, file_path, sheet_name, nrows
        )
    except Exception as e:
        logger.error("Failed to load Excel file | path={} | error={}", file_path, e)
        return {"total": 0, "rows": [], "columns": [], "error": str(e)}

    if not raw_rows:
        return {"total": 0, "rows": [], "columns": []}

    columns = list(raw_rows[0].keys())
    col_mapping = _build_column_mapping(columns, merged_mapping)

    mapped_rows: list[dict] = []
    for row in raw_rows:
        mapped = {col_mapping.get(k, k): v for k, v in row.items()}
        mapped_rows.append(mapped)

    logger.info("Excel loaded | path={} | total={} | columns={}", file_path, len(mapped_rows), columns)
    return {"total": len(mapped_rows), "rows": mapped_rows, "columns": columns}
