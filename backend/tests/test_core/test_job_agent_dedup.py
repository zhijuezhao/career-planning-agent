import pytest
from app.core.job_agent.tools.dedup import deduplicate_jobs
from langchain_core.tools import BaseTool


class TestDeduplicateJobs:
    @pytest.mark.asyncio
    async def test_exact_dedup_removes_same_code(self):
        rows = [
            {"code": "J001", "title": "前端工程师", "company": "A", "city": "北京"},
            {"code": "J001", "title": "前端工程师", "company": "A", "city": "北京"},
            {"code": "J002", "title": "后端工程师", "company": "B", "city": "上海"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 2
        assert result["exact_dedup_count"] == 1
        assert result["fuzzy_dedup_count"] == 0

    @pytest.mark.asyncio
    async def test_exact_dedup_preserves_no_code_rows(self):
        rows = [
            {"title": "前端工程师", "company": "A", "city": "北京"},
            {"title": "前端工程师", "company": "A", "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        # No code → exact dedup does nothing, but fuzzy dedup catches identical rows
        assert result["total"] == 1
        assert result["exact_dedup_count"] == 0
        assert result["fuzzy_dedup_count"] == 1

    @pytest.mark.asyncio
    async def test_fuzzy_dedup_similar_titles(self):
        rows = [
            {"title": "高级前端开发工程师", "company": "ABC", "city": "北京"},
            {"title": "高级前端开发工程师", "company": "ABC", "city": "北京"},
            {"title": "Java开发工程师", "company": "ABC", "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows, "fuzzy_threshold": 0.85})
        # First two identical → fuzzy deduped, third kept
        assert result["total"] == 2
        assert result["fuzzy_dedup_count"] == 1

    @pytest.mark.asyncio
    async def test_fuzzy_dedup_different_city_kept(self):
        rows = [
            {"title": "前端工程师", "company": "ABC", "city": "北京"},
            {"title": "前端工程师", "company": "ABC", "city": "上海"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 2
        assert result["fuzzy_dedup_count"] == 0

    @pytest.mark.asyncio
    async def test_fuzzy_dedup_different_company_kept(self):
        rows = [
            {"title": "前端工程师", "company": "ABC公司", "city": "北京"},
            {"title": "前端工程师", "company": "XYZ公司", "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 2
        assert result["fuzzy_dedup_count"] == 0

    @pytest.mark.asyncio
    async def test_lower_threshold_removes_more(self):
        rows = [
            {"title": "前端开发工程师", "company": "A", "city": "北京"},
            {"title": "前端工程师", "company": "A", "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows, "fuzzy_threshold": 0.6})
        assert result["total"] == 1
        assert result["fuzzy_dedup_count"] == 1

    @pytest.mark.asyncio
    async def test_handles_empty_rows(self):
        result = await deduplicate_jobs.ainvoke({"rows": []})
        assert result["total"] == 0
        assert result["deduped_rows"] == []
        assert result["exact_dedup_count"] == 0
        assert result["fuzzy_dedup_count"] == 0

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(deduplicate_jobs, BaseTool)
        assert deduplicate_jobs.name == "deduplicate_jobs"

    @pytest.mark.asyncio
    async def test_nan_values_do_not_crash(self):
        """回归：Excel 空单元格是 NaN(float)，NaN 是 truthy → 旧实现 `.strip()` 直接抛异常。"""
        rows = [
            {"title": float("nan"), "company": "A公司", "city": "北京"},
            {"title": "后端工程师", "company": float("nan"), "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_none_and_nan_both_treated_as_empty(self):
        rows = [
            {"title": "前端工程师", "company": None, "city": "北京"},
            {"title": "前端工程师", "company": float("nan"), "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        # 公司为空视为不冲突 → 标题相同 + 城市相同 → 判为重复
        assert result["total"] == 1
        assert result["fuzzy_dedup_count"] == 1
