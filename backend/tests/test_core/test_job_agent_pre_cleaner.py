import pytest
from app.core.job_agent.tools.pre_cleaner import (
    _clean_industry,
    _fix_none_address,
    _normalize_salary,
    _remove_html_tags,
    _split_address,
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


class TestSalaryBareWanIsMonthly:
    """B1（2026-10-03 用户拍板）：**裸 `X-Y万` 按月薪**（×10000，**不 ÷12**）。

    旧实现（13 条正则）把带 `万` 的范围一律当年薪 ÷12 —— 实测让真实 524 行表里
    **70 行薪资错 12 倍**（`1.2-1.3万` → `1000-1083`，真实应为 `12000-13000`）。
    更糟的是质检模型会自己发现这个矛盾（实测「薪资信息」只给 10~40 分）并把整行
    从 B 压成 C —— 所以这不只是数据准确性问题，而是画像质量问题。
    """

    def test_bare_wan_is_monthly(self):
        assert _normalize_salary("1.2-1.3万") == "12000-13000"
        assert _normalize_salary("1-2万") == "10000-20000"
        assert _normalize_salary("1-1.5万") == "10000-15000"
        assert _normalize_salary("1.6-2.4万") == "16000-24000"

    def test_wan_on_both_sides_of_separator(self):
        """`20万-30万/年` 两侧都带「万」——旧实现必须专门写一条正则，漏一条就整类失配。"""
        assert _normalize_salary("20万-30万/年") == "16667-25000"

    def test_explicit_yearly_still_divides_by_12(self):
        assert _normalize_salary("24万/年") == "20000"
        assert _normalize_salary("20-30万/年") == "16667-25000"

    def test_n_months_factor(self):
        """`·N薪` 按 N/12 折算（用户 2026-10-03 拍板）。"""
        assert _normalize_salary("2-4万·14薪") == "23333-46667"
        assert _normalize_salary("4000-5000元·13薪") == "4333-5417"

    def test_plain_yuan_monthly_unchanged(self):
        assert _normalize_salary("9000-15000元") == "9000-15000"
        assert _normalize_salary("15000-25000元/月") == "15000-25000"

    def test_daily_yuan_times_22(self):
        assert _normalize_salary("100-150元/天") == "2200-3300"


class TestSplitAddress:
    """B1（2026-10-03）：`地址` 是「城市-区县」，且区县可能是字面 `None`。

    实测真实表里 **17 行**形如 `常德-None`：`None` 是导出工具留下的字面字符串，不是区县。
    原样保留会让城市变成 `常德-None`，与地域下拉选项永远对不上。
    """

    def test_splits_city_and_district(self):
        assert _split_address("上海-杨浦区") == ("上海", "杨浦区")
        assert _split_address("南京-鼓楼区") == ("南京", "鼓楼区")

    def test_drops_literal_none_district(self):
        assert _split_address("常德-None") == ("常德", None)
        assert _split_address("杭州-None") == ("杭州", None)
        assert _split_address("北京-None") == ("北京", None)

    def test_drops_placeholder_district(self):
        assert _split_address("上海-未知") == ("上海", None)

    def test_bare_city_unchanged(self):
        assert _split_address("北京") == ("北京", None)

    def test_none_and_placeholder_inputs(self):
        assert _split_address(None) == (None, None)
        assert _split_address("") == (None, None)
        assert _split_address("None") == (None, None)
        assert _split_address("nan") == (None, None)


class TestCleanJobDataAddressAndSalaryRaw:
    """B1：地址规范化 + **薪资原文保留**在 `clean_job_data` 里的端到端行为。"""

    @pytest.mark.asyncio
    async def test_address_cleaned_and_salary_raw_kept(self):
        rows = [{"title": "Java", "city": "常德-None", "salary": "1.2-1.3万"}]
        result = await clean_job_data.ainvoke({"rows": rows})
        row = result["cleaned_rows"][0]

        assert row["city"] == "常德"  # 纯城市名，不含 `-None`
        assert row["salary"] == "12000-13000"  # 主值 = 折算后月薪
        assert row["salary_raw"] == "1.2-1.3万"  # 原文保留（用户要求）
        assert result["stats"]["city_cleaned"] == 1
        assert result["stats"]["city_fixed"] == 0

    @pytest.mark.asyncio
    async def test_district_extracted_separately(self):
        rows = [{"title": "Java", "city": "上海-杨浦区"}]
        result = await clean_job_data.ainvoke({"rows": rows})
        row = result["cleaned_rows"][0]

        assert row["city"] == "上海"
        assert row["district"] == "杨浦区"
        assert result["stats"]["district_extracted"] == 1

    @pytest.mark.asyncio
    async def test_missing_city_still_becomes_unknown(self):
        rows = [{"title": "Java", "city": None}]
        result = await clean_job_data.ainvoke({"rows": rows})

        assert result["cleaned_rows"][0]["city"] == "未知"
        assert result["stats"]["city_fixed"] == 1
