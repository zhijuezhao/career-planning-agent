"""B3（2026-10-03）单元测试：导入切片 + 清单 + 三层完整性校验。

需求原话（用户 2026-10-03）::

    将该文档切成好几份进行传输，序列号按 1、2、3、4 后缀等等依次标识……
    每一个传输完成后就暂停，等待人工确认后，再进行下一个切片的处理，
    这样可以保持数据的完整性不被丢失。

所以本文件重点锁两件事：**切得正确**（互斥且穷尽）与**校验能抓到损坏**
（丢片 / 改片 / 少行）。
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from app.core.job_agent.slices import (
    build_manifest,
    plan_slice_ranges,
    row_fingerprint,
    rows_digest,
    sha256_file,
    slice_file_name,
    verify_manifest,
    write_slices,
)

COLUMNS = ["岗位名称", "公司名称", "岗位编码"]


@pytest.fixture()
def work_dir() -> Iterator[Path]:
    """测试用工作目录（**在工作区内**，用完即删）。

    为什么不用 pytest 的 `tmp_path`：本机 DSH 沙箱把 `%TEMP%` 判为工作区外，
    `tmp_path` 会直接 `PermissionError: [WinError 5]`（仓库里另有 5 个用例同样因它报错）。
    切片测试必然要落盘，所以这里改为在工作区内建目录并在用例结束后清理。
    """
    base = Path(__file__).resolve().parents[1] / "_artifacts" / uuid4().hex[:8]
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _rows(n: int) -> list[dict]:
    return [
        {"岗位名称": f"岗位{i}", "公司名称": f"公司{i % 3}", "岗位编码": f"C{i:04d}"}
        for i in range(n)
    ]


class TestPlanSliceRanges:
    def test_524_rows_into_11_slices_of_50(self):
        ranges = plan_slice_ranges(524, 50)
        assert len(ranges) == 11
        assert ranges[0] == (0, 50)
        assert ranges[-1] == (500, 524)  # 尾片不满

    def test_ranges_are_mutually_exclusive_and_exhaustive(self):
        rows = 524
        ranges = plan_slice_ranges(rows, 50)
        assert sum(e - s for s, e in ranges) == rows  # 穷尽
        for (s1, e1), (s2, e2) in zip(ranges, ranges[1:]):
            assert e1 == s2  # 无缝、不重叠
        assert ranges[0][0] == 0 and ranges[-1][1] == rows

    def test_exact_multiple(self):
        assert plan_slice_ranges(100, 50) == [(0, 50), (50, 100)]

    def test_empty_table(self):
        assert plan_slice_ranges(0, 50) == []

    def test_invalid_slice_size(self):
        with pytest.raises(ValueError):
            plan_slice_ranges(10, 0)


class TestFingerprint:
    def test_column_order_does_not_matter(self):
        a = {"岗位名称": "Java", "公司名称": "A"}
        b = {"公司名称": "A", "岗位名称": "Java"}
        assert row_fingerprint(a) == row_fingerprint(b)

    def test_none_and_empty_are_the_same(self):
        assert row_fingerprint({"a": None}) == row_fingerprint({"a": ""})

    def test_different_content_differs(self):
        assert row_fingerprint({"a": "1"}) != row_fingerprint({"a": "2"})

    def test_digest_keeps_duplicates(self):
        """多重集语义：少一行重复也必须改变摘要（否则"少了一行"查不出来）。"""
        d1 = rows_digest(["x", "y", "x"])
        d2 = rows_digest(["x", "y"])
        assert d1 != d2

    def test_digest_ignores_order(self):
        assert rows_digest(["b", "a"]) == rows_digest(["a", "b"])


class TestWriteSlicesAndVerify:
    def test_writes_files_and_manifest_then_verifies_clean(self, work_dir):
        rows = _rows(8)
        manifest = write_slices(
            rows, COLUMNS, out_dir=work_dir, batch_id="job999", slice_size=3,
            source_name="原始.xlsx", source_sha256="deadbeef",
        )

        assert manifest["total_rows"] == 8
        assert manifest["slice_count"] == 3
        assert manifest["integrity"] == {"rows_sum": 8, "equals_total": True}
        assert manifest["slices"][-1]["rows"] == 2  # 3 + 3 + 2

        for item in manifest["slices"]:
            assert (work_dir / item["file"]).exists()
            assert item["sha256"] and item["rows_hash"]

        # 清单文件也要落盘（人工可查、可复核）
        saved = json.loads((work_dir / "job999_manifest.json").read_text(encoding="utf-8"))
        assert saved["slice_count"] == 3

        assert verify_manifest(manifest, work_dir) == []

    def test_slice_file_names_have_numeric_suffix(self):
        assert slice_file_name("job9", 1, 11) == "job9_slice_01of11.xlsx"
        assert slice_file_name("job9", 11, 11) == "job9_slice_11of11.xlsx"

    def test_verify_detects_missing_slice(self, work_dir):
        manifest = write_slices(_rows(6), COLUMNS, out_dir=work_dir, batch_id="j1", slice_size=3)
        (work_dir / manifest["slices"][1]["file"]).unlink()

        problems = verify_manifest(manifest, work_dir)
        assert any("缺失" in p for p in problems), problems

    def test_verify_detects_tampered_slice(self, work_dir):
        """改了内容必须被抓到（sha256 + 行指纹双重校验）。"""
        manifest = write_slices(_rows(6), COLUMNS, out_dir=work_dir, batch_id="j2", slice_size=3)
        target = work_dir / manifest["slices"][0]["file"]
        frame = pd.read_excel(target, dtype=str)
        frame.loc[0, "公司名称"] = "被篡改公司"
        frame.to_excel(target, index=False)

        problems = verify_manifest(manifest, work_dir)
        assert any("被改动" in p for p in problems), problems

    def test_verify_detects_removed_row(self, work_dir):
        manifest = write_slices(_rows(6), COLUMNS, out_dir=work_dir, batch_id="j3", slice_size=3)
        target = work_dir / manifest["slices"][0]["file"]
        frame = pd.read_excel(target, dtype=str)
        frame.iloc[:-1].to_excel(target, index=False)  # 少一行

        problems = verify_manifest(manifest, work_dir)
        assert any("行数不符" in p for p in problems), problems
        assert any("丢行" in p or "行指纹摘要" in p for p in problems), problems

    def test_verify_reports_empty_manifest(self, work_dir):
        assert verify_manifest({"slices": []}, work_dir) == ["清单里没有任何切片（表可能是空的）"]

    def test_sha256_file_matches_manifest(self, work_dir):
        manifest = write_slices(_rows(4), COLUMNS, out_dir=work_dir, batch_id="j4", slice_size=2)
        item = manifest["slices"][0]
        assert sha256_file(work_dir / item["file"]) == item["sha256"]


class TestBuildManifestWithoutWriting:
    def test_preflight_manifest(self):
        """导入预检：不写文件也能知道"切几片、共多少行"。"""
        rows = _rows(524)
        manifest = build_manifest(rows, batch_id="pre", slice_size=50)

        assert manifest["total_rows"] == 524
        assert manifest["slice_count"] == 11
        assert manifest["integrity"]["equals_total"] is True
        assert manifest["slices"][0]["file"] is None  # 未落盘

    def test_columns_inferred_from_rows(self):
        manifest = build_manifest(_rows(2), batch_id="pre", slice_size=50)
        assert set(manifest["columns"]) == set(COLUMNS)
