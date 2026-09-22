from unittest.mock import AsyncMock, patch

import pytest
from app.core.job_agent.tools.data_loader import _detect_engine, load_excel_data
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
