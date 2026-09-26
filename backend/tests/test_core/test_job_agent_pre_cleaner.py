import pytest
from app.core.job_agent.tools.pre_cleaner import (
    _clean_industry,
    _fix_none_address,
    _normalize_salary,
    _remove_html_tags,
    clean_job_data,
)
from langchain_core.tools import BaseTool


class TestRemoveHtmlTags:
    def test_removes_br_tags(self):
        assert _remove_html_tags("技能要求<br>Python<br>Java") == "技能要求\nPython\nJava"

    def test_removes_br_with_slash(self):
        assert _remove_html_tags("描述<br/>内容") == "描述\n内容"

    def test_removes_br_with_space(self):
        assert _remove_html_tags("A<br />B") == "A\nB"

    def test_removes_other_tags(self):
        assert _remove_html_tags("<p>段落</p>内容") == "段落 内容"

    def test_returns_none_for_none(self):
        assert _remove_html_tags(None) is None

    def test_collapses_excessive_newlines(self):
        assert _remove_html_tags("a<br><br><br>b") == "a\n\nb"


class TestFixNoneAddress:
    def test_fills_none_city(self):
        result = _fix_none_address({"city": None})
        assert result["city"] == "未知"

    def test_fills_empty_city(self):
        result = _fix_none_address({"city": ""})
        assert result["city"] == "未知"

    def test_fills_nan_string_city(self):
        result = _fix_none_address({"city": "nan"})
        assert result["city"] == "未知"

    def test_preserves_valid_city(self):
        result = _fix_none_address({"city": "北京"})
        assert result["city"] == "北京"


class TestCleanIndustry:
    def test_exact_match(self):
        assert _clean_industry("互联网") == "互联网/IT"

    def test_substring_match_longest_key(self):
        assert _clean_industry("移动互联网游戏") == "互联网/IT"

    def test_unknown_industry_preserved(self):
        assert _clean_industry("航天航空") == "航天航空"

    def test_none_returns_none(self):
        assert _clean_industry(None) is None

    def test_nan_returns_none(self):
        assert _clean_industry("nan") is None

    def test_custom_map_overrides(self):
        result = _clean_industry("航天航空", {"航天航空": "航天/航空"})
        assert result == "航天/航空"


class TestNormalizeSalary:
    def test_yearly_range(self):
        assert _normalize_salary("20万-30万/年") == "16667-25000"

    def test_yearly_single(self):
        result = _normalize_salary("24万/年")
        assert result == "20000"

    def test_monthly_k_range(self):
        assert _normalize_salary("10K-15K") == "10000-15000"

    def test_monthly_k_lowercase(self):
        assert _normalize_salary("8k-12k") == "8000-12000"

    def test_monthly_range(self):
        assert _normalize_salary("15000-25000元/月") == "15000-25000"

    def test_monthly_single(self):
        assert _normalize_salary("20000/月") == "20000"

    def test_daily_range(self):
        result = _normalize_salary("500-800元/天")
        assert result == "11000-17600"  # 500*22=11000, 800*22=17600

    def test_hourly_range(self):
        result = _normalize_salary("50-80元/时")
        assert result == "8800-14080"  # 50*176=8800, 80*176=14080

    def test_negotiable_returns_none(self):
        assert _normalize_salary("薪资面议") is None

    def test_none_returns_none(self):
        assert _normalize_salary(None) is None

    def test_empty_returns_none(self):
        assert _normalize_salary("") is None

    def test_swapped_range(self):
        """Test that larger value comes first gets swapped."""
        result = _normalize_salary("10K-8K")
        assert result == "8000-10000"

    def test_tilde_separator(self):
        assert _normalize_salary("10K~15K") == "10000-15000"


class TestCleanJobData:
    @pytest.mark.asyncio
    async def test_cleans_multiple_rows(self):
        rows = [
            {"title": "前端<br>工程师", "city": None, "industry": "互联网", "salary": "20K-30K"},
            {"title": "Java开发", "city": "上海", "industry": "航天航空", "salary": "薪资面议"},
        ]
        result = await clean_job_data.ainvoke({"rows": rows})

        assert result["total"] == 2
        assert result["cleaned_rows"][0]["title"] == "前端\n工程师"
        assert result["cleaned_rows"][0]["city"] == "未知"
        assert result["cleaned_rows"][0]["industry"] == "互联网/IT"
        assert result["cleaned_rows"][0]["salary"] == "20000-30000"
        assert result["cleaned_rows"][1]["salary"] is None

    @pytest.mark.asyncio
    async def test_stats_counts(self):
        rows = [
            {"title": "a<br>b", "city": None, "industry": "互联网", "salary": "20K-30K"},
            {"title": "normal", "city": "北京", "industry": "航天航空", "salary": "面议"},
        ]
        result = await clean_job_data.ainvoke({"rows": rows})

        assert result["stats"]["html_tags_removed"] >= 1
        assert result["stats"]["city_fixed"] == 1
        assert result["stats"]["industry_normalised"] == 1
        assert result["stats"]["salary_normalised"] == 1
        assert result["stats"]["salary_cleared"] == 1

    @pytest.mark.asyncio
    async def test_handles_empty_rows(self):
        result = await clean_job_data.ainvoke({"rows": []})
        assert result["total"] == 0
        assert result["cleaned_rows"] == []

    @pytest.mark.asyncio
    async def test_skips_rows_without_title(self):
        """分组标题行（岗位名为空）必须被丢弃，不能进入后续 3 次 LLM（2026-09-26）。

        用户表格用「测试类」「人工智能/算法类」这类标题行给岗位分区，这类行只有序号、
        岗位名称为空；当成岗数据既白烧 token 又会生成垃圾画像。
        实测 `job_infor.xlsx` 有 2 行这种标题行。
        """
        rows = [
            {"title": "Java", "city": "北京"},
            {"title": None, "序号": "20", "city": None},  # 分类标题行
            {"title": "   ", "序号": "21"},  # 纯空白
            {"title": "nan", "序号": "22"},  # 清洗前残留的 NaN 字符串
            {"title": "Python", "city": None},
        ]
        result = await clean_job_data.ainvoke({"rows": rows})

        assert result["total"] == 2
        assert [r["title"] for r in result["cleaned_rows"]] == ["Java", "Python"]
        assert result["stats"]["skipped_no_title"] == 3

    @pytest.mark.asyncio
    async def test_all_rows_without_title_yields_empty(self):
        result = await clean_job_data.ainvoke({"rows": [{"title": ""}, {"title": "nan"}]})
        assert result["total"] == 0
        assert result["cleaned_rows"] == []
        assert result["stats"]["skipped_no_title"] == 2

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(clean_job_data, BaseTool)
        assert clean_job_data.name == "clean_job_data"
