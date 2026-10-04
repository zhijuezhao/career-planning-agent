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


class TestIdentityFirstDedup:
    """B2（2026-10-03 用户拍板）：**标识优先**去重（`岗位编码` → `岗位来源地址`）。

    真实事故：用户的 524 行表自带 `岗位编码`（487 个唯一值），旧实现第 1 级按 code
    去重得到 487 行（正确），**紧接着第 2 级又按 `(岗位名, 公司)` 并成 384 行** ——
    被并掉的 103 行编码各不相同、城市/日期也不同（美团把「APP推广」投在 15 个城市）。
    更极端的一次：4366 行、`岗位名称` 只有 9 个类别且无公司列 → 100 行被并成 **1 行**。

    → 有唯一标识的行**不该**再被名称合并。
    """

    @pytest.mark.asyncio
    async def test_distinct_codes_are_not_merged_by_title_company(self):
        rows = [
            {"code": "C1", "title": "APP推广", "company": "美团", "city": "北京"},
            {"code": "C2", "title": "APP推广", "company": "美团", "city": "上海"},
            {"code": "C3", "title": "APP推广", "company": "美团", "city": "广州"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 3  # 全部保留（旧实现会并成 1）
        assert result["exact_dedup_count"] == 0
        assert result["title_company_dedup_count"] == 0
        assert result["identity_count"] == 3

    @pytest.mark.asyncio
    async def test_same_code_is_still_removed(self):
        rows = [
            {"code": "C1", "title": "A", "company": "X"},
            {"code": "C1", "title": "A", "company": "X"},
            {"code": "C1", "title": "B", "company": "Y"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 1
        assert result["exact_dedup_count"] == 2

    @pytest.mark.asyncio
    async def test_source_url_is_second_choice_identity(self):
        """没有 code 时用 `岗位来源地址` 当标识（否则无公司列的表会被名称并成 1 条）。"""
        rows = [
            {"title": "Java", "company": None, "source_url": "https://x.com/j/1.htm"},
            {"title": "Java", "company": None, "source_url": "https://x.com/j/1.htm"},
            {"title": "Java", "company": None, "source_url": "https://x.com/j/2.htm"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 2
        assert result["exact_dedup_count"] == 1
        assert result["title_company_dedup_count"] == 0

    @pytest.mark.asyncio
    async def test_url_query_string_is_ignored(self):
        """导出会话参数（`preactionid`）不能影响标识 —— 否则「同一份表再导一次」失效。"""
        rows = [
            {"title": "Java", "source_url": "https://x.com/j/1.htm?refcode=1&preactionid=AAA"},
            {"title": "Java", "source_url": "https://x.com/j/1.htm?refcode=1&preactionid=BBB"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_rows_without_identity_still_dedup_by_title_company(self):
        """没有标识的行**仍然**走名称去重（老行为与老测试不能丢）。"""
        rows = [
            {"title": "前端工程师", "company": "A", "city": "北京"},
            {"title": "前端工程师", "company": "A", "city": "上海"},
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 1
        assert result["title_company_dedup_count"] == 1
        assert result["identity_count"] == 0

    @pytest.mark.asyncio
    async def test_mixed_identified_and_unidentified(self):
        """混合表：有标识的按标识、无标识的按名称，互不干扰。"""
        rows = [
            {"code": "C1", "title": "Java", "company": "A"},
            {"code": "C2", "title": "Java", "company": "A"},  # 有标识 → 保留
            {"title": "Java", "company": "A"},  # 无标识
            {"title": "Java", "company": "A"},  # 无标识 → 被名称去重
        ]
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 3
        assert result["identity_count"] == 2
        assert result["title_company_dedup_count"] == 1


class TestRemovalAlert:
    """B2 护栏：单级删除比例 >50% 必须显式报警。

    事故当年级联删除 99%（100 行 → 1 行）却报 `completed`，管理员**看不到任何异常**。
    """

    @pytest.mark.asyncio
    async def test_alert_fires_on_mass_removal(self):
        rows = [{"title": "C/C++", "company": None, "city": "北京"} for _ in range(10)]
        rows.append({"title": "Java", "company": None, "city": "上海"})
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 2
        assert result["dedup_alerts"], "删除 9/11 行必须报警"
        assert "(岗位名, 公司)" in result["dedup_alerts"][0]

    @pytest.mark.asyncio
    async def test_no_alert_for_normal_removal(self):
        """真实 524 行文件只删 37/524（7%）→ 不应告警。"""
        rows = [{"code": f"C{i}", "title": f"岗位{i}", "company": "A"} for i in range(20)]
        rows.append({"code": "C0", "title": "岗位0", "company": "A"})
        result = await deduplicate_jobs.ainvoke({"rows": rows})
        assert result["total"] == 20
        assert result["dedup_alerts"] == []
