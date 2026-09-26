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
        # 没 code → 编码精确去重不动它；但 (岗位名, 公司) 完全相同 → 第二级精确去重命中
        assert result["total"] == 1
        assert result["exact_dedup_count"] == 0
        assert result["title_company_dedup_count"] == 1
        assert result["fuzzy_dedup_count"] == 0

    @pytest.mark.asyncio
    async def test_fuzzy_dedup_similar_titles(self):
        rows = [
            {"title": "高级前端开发工程师", "company": "ABC", "city": "北京"},
            {"title": "高级前端开发工程师", "company": "ABC", "city": "北京"},
            {"title": "Java开发工程师", "company": "ABC", "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows, "fuzzy_threshold": 0.85})
        # 前两条完全相同 → 被 (岗位名,公司) 精确去重拦下；第三条相似度不够 → 保留
        assert result["total"] == 2
        assert result["title_company_dedup_count"] == 1
        assert result["fuzzy_dedup_count"] == 0

    @pytest.mark.asyncio
    async def test_same_title_and_company_ignores_city(self):
        """P2：城市**不在**去重键里 —— 同公司同岗位名、城市不同 → 同一条岗位。

        这是用户选定的粒度 `(岗位名, 公司)` 的直接推论（城市不是身份的一部分）。
        如果以后要"同岗多城市各算一条"，得把城市加进键里（并同步改唯一索引）。
        """
        rows = [
            {"title": "前端工程师", "company": "ABC", "city": "北京"},
            {"title": "前端工程师", "company": "ABC", "city": "上海"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 1
        assert result["title_company_dedup_count"] == 1

    @pytest.mark.asyncio
    async def test_fuzzy_dedup_one_sided_city_is_not_a_veto(self):
        """P2：只有一边写了城市时不应判成两个岗位（旧实现要求城市严格相等）。"""
        rows = [
            {"title": "前端工程师", "company": "ABC", "city": "北京"},
            {"title": "前端工程师", "company": "ABC", "city": None},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_title_company_dedup_normalises_case_and_whitespace(self):
        """P2：归一化后相同即重复（忽略大小写 + 折叠空白）。"""
        rows = [
            {"title": "Java  开发工程师", "company": "  ABC 科技 ", "city": "北京"},
            {"title": "java 开发工程师", "company": "ABC 科技", "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 1
        assert result["title_company_dedup_count"] == 1

    @pytest.mark.asyncio
    async def test_fuzzy_dedup_different_company_kept(self):
        rows = [
            {"title": "前端工程师", "company": "ABC公司", "city": "北京"},
            {"title": "前端工程师", "company": "XYZ公司", "city": "北京"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        # P2：同岗不同公司 = 两条画像 → 必须都保留
        assert result["total"] == 2
        assert result["title_company_dedup_count"] == 0
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
        assert result["title_company_dedup_count"] == 0
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
        # 公司为空视为"未知"（不冲突）→ 标题相同 → (岗位名, 公司) 精确去重命中
        assert result["total"] == 1
        assert result["title_company_dedup_count"] == 1
