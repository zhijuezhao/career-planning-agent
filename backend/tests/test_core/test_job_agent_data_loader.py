from unittest.mock import AsyncMock, patch

import pytest
from app.core.job_agent.tools.data_loader import (
    DEFAULT_COLUMN_MAPPING,
    _build_column_mapping,
    _detect_engine,
    load_excel_data,
    resolve_column,
)
from app.core.job_agent.tools.schema_detect import EXTRA_COLUMN_ALIASES
from langchain_core.tools import BaseTool

SAMPLE_ROWS = [
    {"岗位名称": "前端工程师", "公司名称": "ABC公司", "薪资": "15K-25K"},
    {"岗位名称": "后端工程师", "公司名称": "XYZ公司", "薪资": "20K-30K"},
]


class TestDetectEngine:
    def test_xls_uses_xlrd(self):
        assert _detect_engine("data.xls") == "xlrd"

    def test_xlsx_uses_openpyxl(self):
        assert _detect_engine("data.xlsx") == "openpyxl"

    def test_xlsm_uses_openpyxl(self):
        assert _detect_engine("data.xlsm") == "openpyxl"

    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported file extension"):
            _detect_engine("data.csv")


class TestLoadExcelData:
    @pytest.mark.asyncio
    async def test_loads_excel_successfully(self):
        with patch("app.core.job_agent.tools.data_loader.asyncio.to_thread", AsyncMock(return_value=SAMPLE_ROWS)):
            result = await load_excel_data.ainvoke({"file_path": "test.xlsx"})

        assert result["total"] == 2
        assert len(result["rows"]) == 2
        assert result["rows"][0]["title"] == "前端工程师"
        assert result["rows"][0]["company"] == "ABC公司"
        assert result["rows"][0]["salary"] == "15K-25K"
        assert "columns" in result

    @pytest.mark.asyncio
    async def test_empty_file_returns_empty(self):
        with patch("app.core.job_agent.tools.data_loader.asyncio.to_thread", AsyncMock(return_value=[])):
            result = await load_excel_data.ainvoke({"file_path": "empty.xlsx"})

        assert result["total"] == 0
        assert result["rows"] == []

    @pytest.mark.asyncio
    async def test_custom_column_mapping_overrides_default(self):
        custom_rows = [{"自定义名称": "Java开发", "公司": "TechCo"}]
        with patch("app.core.job_agent.tools.data_loader.asyncio.to_thread", AsyncMock(return_value=custom_rows)):
            result = await load_excel_data.ainvoke(
                {"file_path": "test.xlsx", "column_mapping": {"自定义名称": "title", "公司": "company"}}
            )

        assert result["rows"][0]["title"] == "Java开发"
        assert result["rows"][0]["company"] == "TechCo"

    @pytest.mark.asyncio
    async def test_unknown_columns_preserved_as_is(self):
        custom_rows = [{"奇怪列名": "some value"}]
        with patch("app.core.job_agent.tools.data_loader.asyncio.to_thread", AsyncMock(return_value=custom_rows)):
            result = await load_excel_data.ainvoke({"file_path": "test.xlsx"})

        assert result["rows"][0]["奇怪列名"] == "some value"

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self):
        exc = FileNotFoundError("file not found")
        with patch("app.core.job_agent.tools.data_loader.asyncio.to_thread", AsyncMock(side_effect=exc)):
            result = await load_excel_data.ainvoke({"file_path": "nonexistent.xlsx"})

        assert result["total"] == 0
        assert result["rows"] == []
        assert "error" in result

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(load_excel_data, BaseTool)
        assert load_excel_data.name == "load_excel_data"

    @pytest.mark.asyncio
    async def test_excel_blank_cells_become_none_not_nan(self, tmp_path):
        """回归：空单元格曾是 NaN(float)。

        pandas 把 Excel 空单元格读成 `NaN`，NaN 是 **truthy** → 去重阶段的
        `text.strip()` 抛 `'float' object has no attribute 'strip'`，
        实测让真实 50 行 xlsx 在 33% 处整单失败。这里断言空值一律是 `None`。
        """
        import pandas as pd

        path = tmp_path / "blanks.xlsx"
        pd.DataFrame(
            {"岗位名称": ["前端工程师", None], "公司名称": [None, "B公司"]}
        ).to_excel(path, index=False)

        result = await load_excel_data.ainvoke({"file_path": str(path)})

        assert result["total"] == 2
        for row in result["rows"]:
            for key, value in row.items():
                assert not isinstance(value, float), f"{key} 仍是 float：{value!r}"
        assert result["rows"][0]["company"] is None
        assert result["rows"][1]["title"] is None


class TestLoadCsvData:
    """S7-2（D-S7-2=A）：上传入口允许 .csv，data_loader 必须有 CSV 分支。"""

    @pytest.mark.asyncio
    async def test_csv_chinese_headers_are_mapped(self, tmp_path):
        path = tmp_path / "jobs.csv"
        path.write_text("岗位名称,公司名称,工作城市\n数据分析师,A公司,北京\n", encoding="utf-8")

        result = await load_excel_data.ainvoke({"file_path": str(path)})

        assert result["total"] == 1
        assert result["rows"][0]["title"] == "数据分析师"
        assert result["rows"][0]["company"] == "A公司"
        assert result["rows"][0]["city"] == "北京"

    @pytest.mark.asyncio
    async def test_csv_gbk_is_decoded_via_fallback(self, tmp_path):
        path = tmp_path / "gbk.csv"
        path.write_bytes("岗位名称,公司名称\n后端工程师,B公司\n".encode("gbk"))

        result = await load_excel_data.ainvoke({"file_path": str(path)})

        assert result["total"] == 1
        assert result["rows"][0]["title"] == "后端工程师"

    @pytest.mark.asyncio
    async def test_csv_respects_nrows_limit(self, tmp_path):
        path = tmp_path / "many.csv"
        path.write_text(
            "岗位名称\n" + "\n".join(f"岗位{i}" for i in range(5)) + "\n", encoding="utf-8"
        )

        result = await load_excel_data.ainvoke({"file_path": str(path), "nrows": 2})

        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_header_only_csv_returns_empty(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("岗位名称,公司名称\n", encoding="utf-8")

        result = await load_excel_data.ainvoke({"file_path": str(path)})

        assert result["total"] == 0
        assert result["rows"] == []


class TestResolveColumn:
    """B1（2026-10-03）：三层列名解析（精确 → 包含 → 未命中）。

    背景：真实 524 行《原始比赛数据_清洗后.xlsx》里 `薪资范围` / `岗位详情` /
    `岗位来源地址` / `地址` / `公司类型` / `公司详情` / `更新日期` **7 个非空列一列都没命中**
    → 薪资清洗整段被跳过、岗位详情（435 个不同值）进不了提取阶段、城市被统一填成「未知」。
    补别名 + 包含匹配是这批修复的第一步。
    """

    MAPPING = {**DEFAULT_COLUMN_MAPPING, **EXTRA_COLUMN_ALIASES}

    def test_exact_match(self):
        assert resolve_column("岗位名称", self.MAPPING)[0] == "title"

    def test_containment_salary_variants(self):
        """用户点名的例子：`薪资` 与 `公司薪资` 都该落到 salary。"""
        for col in ("薪资", "公司薪资", "月薪资范围", "薪资待遇"):
            assert resolve_column(col, self.MAPPING)[0] == "salary", col

    def test_containment_longest_alias_wins(self):
        assert resolve_column("企业规模情况", self.MAPPING)[0] == "scale"

    def test_trailing_head_wins_on_same_length(self):
        """同长别名取「出现位置更靠后」的（中文复合词中心语在后）。"""
        assert resolve_column("公司地址", self.MAPPING)[0] == "city"

    def test_address_vs_source_url_not_confused(self):
        """`地址` 与 `岗位来源地址` 是最容易互相误伤的一组，靠精确优先分开。"""
        assert resolve_column("地址", self.MAPPING)[0] == "city"
        assert resolve_column("岗位来源地址", self.MAPPING)[0] == "source_url"

    def test_company_subfields_not_swallowed_by_bare_company(self):
        """裸「公司」被认作 company，但不能把更具体的子字段抢走。"""
        assert resolve_column("公司名称", self.MAPPING)[0] == "company"
        assert resolve_column("公司类型", self.MAPPING)[0] == "company_type"
        assert resolve_column("公司详情", self.MAPPING)[0] == "company_detail"
        assert resolve_column("公司", self.MAPPING)[0] == "company"

    def test_unknown_column_is_unmapped_and_preserved(self):
        field, tier, _via = resolve_column("奇怪列名", self.MAPPING)
        assert field is None
        assert tier == "unmapped"
        assert _build_column_mapping(["奇怪列名"], self.MAPPING) == {"奇怪列名": "奇怪列名"}

    def test_conflicting_alias_definitions_are_rejected(self):
        """别名表自身写冲突（归一化后同名却指向不同字段）→ 拒绝映射，不猜。"""
        conflict = {"AB": "title", "ab": "company"}
        field, tier, _via = resolve_column("xxAB", conflict)
        assert field is None
        assert tier == "ambiguous"

    def test_real_competition_headers_all_mapped(self):
        """真实 12 列必须**全部**命中（其中 7 列以前全是未知列）。"""
        real = [
            "岗位名称", "地址", "薪资范围", "公司名称", "所属行业", "公司规模",
            "公司类型", "岗位编码", "岗位详情", "更新日期", "公司详情", "岗位来源地址",
        ]
        mapping = _build_column_mapping(real, self.MAPPING)
        unmapped = [c for c in real if mapping[c] == c]
        assert unmapped == [], f"未命中：{unmapped}"
        assert mapping["岗位详情"] == "description"
        assert mapping["薪资范围"] == "salary"
        assert mapping["岗位来源地址"] == "source_url"
        assert mapping["地址"] == "city"
