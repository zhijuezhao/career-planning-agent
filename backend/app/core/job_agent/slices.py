"""导入切片：把一份大表切成**有序、互斥、穷尽**的小片，逐片处理、片间人工确认。

为什么需要（用户 2026-10-03 拍板，原话）::

    这个文档有 500 多行，一次无法处理，就做好切分机制，将该文档切成好几份进行传输，
    序列号按 1、2、3、4 后缀等等依次标识，切好后进行传输，每一个传输完成后就暂停，
    等待人工确认后，再进行下一个切片的处理，这样就可以保持数据的完整性不被丢失，
    还能兼顾性能与安全，做好切分机制是关键。

本模块只做**纯数据工作**（切分 + 清单 + 完整性校验），不碰数据库、不调 LLM：

1. `plan_slice_ranges()`：按行数切出 `[start, end)` 区间（互斥且穷尽）；
2. `write_slices()`：按**原始列名**写出 `<batch>_slice_01of11.xlsx` 这样的小片，
   并生成 `manifest.json`（每片的行区间 / 文件 sha256 / 行指纹多重集摘要）；
3. `verify_manifest()`：**从磁盘重算**并逐项核对 —— 文件在不在、有没有被改过、
   行数对不对、行指纹多重集是否与原表一致（证明"不丢、不重、不增"）。

⚠️ 为什么切片必须发生在**列名映射之前**：每片都要是一张能被人直接打开看的自解释表
（原始中文列名 + 表头），处理时再走 `data_loader` 的同一套映射/清洗/去重。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from loguru import logger

__all__ = [
    "MANIFEST_SUFFIX",
    "SLICE_SUBDIR",
    "build_manifest",
    "plan_slice_ranges",
    "row_fingerprint",
    "rows_digest",
    "sha256_file",
    "slice_file_name",
    "verify_manifest",
    "write_slices",
]

#: 切片文件放在上传目录下的**子目录**里。
#: `import_module._find_upload_file()` 用 `<job_id>_*` 匹配原文件，子目录不会被它误匹配。
SLICE_SUBDIR = "slices"

#: 清单文件名后缀
MANIFEST_SUFFIX = "_manifest.json"

#: 行指纹里用来分隔「列名 / 列值 / 行内列」的分隔符（取不可打印字符，避免与内容撞车）
_FIELD_SEP = "\x1f"
_ROW_SEP = "\x1e"


def plan_slice_ranges(total_rows: int, slice_size: int) -> list[tuple[int, int]]:
    """把 `total_rows` 行按 `slice_size` 切成互斥且穷尽的 `[start, end)` 区间。

    >>> plan_slice_ranges(524, 50)
    [(0, 50), (50, 100), (100, 150), (150, 200), (200, 250), (250, 300), (300, 350),
     (350, 400), (400, 450), (450, 500), (500, 524)]
    """
    if slice_size <= 0:
        raise ValueError("slice_size 必须为正整数")
    if total_rows <= 0:
        return []
    return [
        (start, min(start + slice_size, total_rows))
        for start in range(0, total_rows, slice_size)
    ]


def slice_file_name(batch_id: str, k: int, total: int) -> str:
    """切片文件名：序列号 1、2、3… 依次标识（用户要求），并带上总片数便于人工核对。"""
    return f"{batch_id}_slice_{k:02d}of{total:02d}.xlsx"


def manifest_file_name(batch_id: str) -> str:
    return f"{batch_id}{MANIFEST_SUFFIX}"


def _cell_text(value: Any) -> str:
    """单元格归一成文本（`None` / `NaN` 都当空串）。"""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def row_fingerprint(row: dict[str, Any]) -> str:
    """一行的内容指纹：与**列顺序无关**，`None` 与空串视为同一件事。"""
    parts = [
        f"{key}{_FIELD_SEP}{_cell_text(row[key])}"
        for key in sorted(row, key=str)
    ]
    return hashlib.sha256(_ROW_SEP.join(parts).encode("utf-8")).hexdigest()


def rows_digest(fingerprints: Iterable[str]) -> str:
    """一组行指纹的**多重集**摘要（先排序再拼接再哈希）。

    排序让它与行序无关，但**保留重复**（多重集）—— 所以既能证明"没丢行"，
    也能证明"没凭空多出行"。这是三层完整性校验的第 2 层。
    """
    return hashlib.sha256("\n".join(sorted(fingerprints)).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_slices(
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    out_dir: Path,
    batch_id: str,
    slice_size: int,
    source_name: str | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """把 `rows` 切成小片写到 `out_dir`，并生成 manifest。

    Returns:
        manifest dict（同时已写入 `out_dir/<batch_id>_manifest.json`）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ranges = plan_slice_ranges(len(rows), slice_size)
    all_fingerprints: list[str] = []
    slices: list[dict[str, Any]] = []

    for index, (start, end) in enumerate(ranges, start=1):
        chunk = rows[start:end]
        fingerprints = [row_fingerprint(r) for r in chunk]
        all_fingerprints.extend(fingerprints)

        name = slice_file_name(batch_id, index, len(ranges))
        path = out_dir / name
        pd.DataFrame(chunk, columns=columns).to_excel(path, index=False)

        slices.append(
            {
                "k": index,
                "row_start": start,
                "row_end": end,
                "rows": len(chunk),
                "file": name,
                "sha256": sha256_file(path),
                "rows_hash": rows_digest(fingerprints),
            }
        )

    manifest: dict[str, Any] = {
        "batch_id": batch_id,
        "source_file": source_name,
        "source_sha256": source_sha256,
        "columns": list(columns),
        "total_rows": len(rows),
        "slice_size": slice_size,
        "slice_count": len(slices),
        "rows_hash": rows_digest(all_fingerprints),
        "slices": slices,
        "integrity": {
            "rows_sum": sum(s["rows"] for s in slices),
            "equals_total": sum(s["rows"] for s in slices) == len(rows),
        },
    }
    (out_dir / manifest_file_name(batch_id)).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(
        "Import: 切片完成 | batch={} | total_rows={} | slice_size={} | slices={}",
        batch_id,
        len(rows),
        slice_size,
        len(slices),
    )
    return manifest


def build_manifest(
    rows: list[dict[str, Any]],
    *,
    batch_id: str,
    slice_size: int,
    source_name: str | None = None,
    source_sha256: str | None = None,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """只算 manifest（**不写文件**）—— 用于导入预检：先看"要切几片、共多少行"。"""
    ranges = plan_slice_ranges(len(rows), slice_size)
    fingerprints = [row_fingerprint(r) for r in rows]
    slices = [
        {"k": i, "row_start": s, "row_end": e, "rows": e - s, "file": None, "sha256": None, "rows_hash": None}
        for i, (s, e) in enumerate(ranges, start=1)
    ]
    return {
        "batch_id": batch_id,
        "source_file": source_name,
        "source_sha256": source_sha256,
        "columns": list(columns or (list(rows[0].keys()) if rows else [])),
        "total_rows": len(rows),
        "slice_size": slice_size,
        "slice_count": len(slices),
        "rows_hash": rows_digest(fingerprints),
        "slices": slices,
        "integrity": {
            "rows_sum": sum(s["rows"] for s in slices),
            "equals_total": sum(s["rows"] for s in slices) == len(rows),
        },
    }


def verify_manifest(manifest: dict[str, Any], out_dir: Path) -> list[str]:
    """**从磁盘重算**并核对清单；返回问题列表（空列表 = 通过）。

    校验四件事（缺一不可）：

    1. 每片文件都在；
    2. 每片文件 sha256 与清单一致（**没被改过**）；
    3. 每片实际行数与清单一致；
    4. 所有片的行指纹多重集摘要 == 清单里原表的摘要（**不丢、不重、不增**）。
    """
    out_dir = Path(out_dir)
    problems: list[str] = []

    slices = manifest.get("slices") or []
    if not slices:
        return ["清单里没有任何切片（表可能是空的）"]

    rows_sum = 0
    combined: list[str] = []

    for item in slices:
        k = item.get("k")
        name = item.get("file")
        if not name:
            problems.append(f"第 {k} 片没有文件名")
            continue
        path = out_dir / name
        if not path.exists():
            problems.append(f"第 {k} 片文件缺失：{name}")
            continue

        actual_sha = sha256_file(path)
        if item.get("sha256") and actual_sha != item["sha256"]:
            problems.append(f"第 {k} 片文件被改动（sha256 不一致）：{name}")

        try:
            frame = pd.read_excel(path, dtype=str)
        except Exception as exc:  # noqa: BLE001 - 读不动就是要报出来
            problems.append(f"第 {k} 片读取失败：{name} | {type(exc).__name__}: {exc}")
            continue

        frame = frame.astype(object).where(frame.notna(), None)
        records = frame.to_dict(orient="records")
        rows_sum += len(records)

        if item.get("rows") is not None and len(records) != item["rows"]:
            problems.append(
                f"第 {k} 片行数不符：清单 {item['rows']}，实际 {len(records)}"
            )

        fingerprints = [row_fingerprint(r) for r in records]
        if item.get("rows_hash") and rows_digest(fingerprints) != item["rows_hash"]:
            problems.append(f"第 {k} 片内容与清单不符（行指纹摘要不一致）：{name}")
        combined.extend(fingerprints)

    if rows_sum != manifest.get("total_rows"):
        problems.append(f"切片行数之和 {rows_sum} != 原表行数 {manifest.get('total_rows')}")

    if manifest.get("rows_hash") and rows_digest(combined) != manifest["rows_hash"]:
        problems.append("所有切片合并后的行指纹摘要 != 原表摘要（可能丢行/多行/被改）")

    return problems
