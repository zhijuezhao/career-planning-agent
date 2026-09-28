"""B3-1 合并规则：表格值优先 + 空位填充 + 冲突只记不改 + provenance。

规则来自主计划 §4.3。这里最值钱的两组用例是**枚举不误报**：

- 「互联网」vs「互联网/IT」——不规范化就会被记成冲突；
- 「本科」vs「本科及以上」——同理。

如果这两条误报，`stats.link_enrich.conflicts` 会被假警报刷满，真冲突（薪资差一倍
那种）反而被淹没 —— 那这个功能就等于没有。
"""

from __future__ import annotations

from app.core.link_enrich.merge import (
    LINKABLE_FIELDS,
    enum_tokens,
    is_conflict,
    merge_link_fields,
)


class TestFillEmptyOnly:
    def test_fills_empty_fields(self):
        row = {"title": "Java 工程师", "company": None, "city": ""}
        outcome = merge_link_fields(row, {"company": "示例科技", "city": "深圳"}, domain="a.com")
        assert outcome.filled == {"company": "示例科技", "city": "深圳"}

    def test_does_not_touch_row(self):
        # 纯函数：调用方自己决定何时 apply（便于"先统计后落库"）
        row = {"company": None}
        merge_link_fields(row, {"company": "示例科技"}, domain="a.com")
        assert row == {"company": None}

    def test_form_value_wins_and_is_recorded_as_conflict(self):
        row = {"salary": "15-20K"}
        outcome = merge_link_fields(row, {"salary": "30-40K"}, domain="a.com")
        assert outcome.filled == {}          # 绝不覆盖用户填的表格值
        assert outcome.conflicts[0]["field"] == "salary"
        assert outcome.conflicts[0]["form"] == "15-20K"
        assert outcome.conflicts[0]["link"] == "30-40K"

    def test_identical_values_are_not_a_conflict(self):
        row = {"company": "示例科技"}
        outcome = merge_link_fields(row, {"company": " 示例科技 "}, domain="a.com")
        assert outcome.conflicts == []

    def test_title_is_never_filled(self):
        # title 是去重键（title_key 唯一索引）：按链接标题改写会让同一岗位分裂成两条
        assert "title" not in LINKABLE_FIELDS
        outcome = merge_link_fields({"title": ""}, {"title": "链接里的标题"}, domain="a.com")
        assert outcome.filled == {}


class TestEnumNormalisation:
    def test_tokens_split_on_separators(self):
        assert enum_tokens("互联网/IT") == {"互联网", "it"}
        assert enum_tokens(None) == set()

    def test_no_separator_enums_are_caught_by_containment(self):
        # 「本科及以上」里没有任何分隔符 —— 切词切不开，靠包含关系认出来
        assert enum_tokens("本科及以上") == {"本科及以上"}
        assert not is_conflict("education_requirement", "本科", "本科及以上")

    def test_partial_overlap_is_not_a_conflict(self):
        cases = (
            ("industry", "互联网", "互联网/IT"),
            ("education_requirement", "本科", "本科及以上"),
            ("industry", "计算机/互联网", "互联网"),
            ("level", "高级", "高级工程师"),
        )
        for field, form, link in cases:
            assert not is_conflict(field, form, link), (field, form, link)

    def test_disjoint_enum_values_are_a_conflict(self):
        assert is_conflict("level", "初级", "高级")
        assert is_conflict("education_requirement", "大专", "硕士")

    def test_enum_conflict_recorded_but_not_applied(self):
        row = {"level": "初级"}
        outcome = merge_link_fields(row, {"level": "高级"}, domain="a.com")
        assert outcome.filled == {}
        assert [c["field"] for c in outcome.conflicts] == ["level"]


class TestLongTextIsNeverAConflict:
    def test_description_difference_is_not_a_conflict(self):
        row = {"description": "表格里的一段描述"}
        outcome = merge_link_fields(row, {"description": "链接里的另一段描述"}, domain="a.com")
        assert outcome.conflicts == []
        assert outcome.filled == {}   # 表格有值就保留
        assert outcome.provenance["description"] == "form"

    def test_requirements_same(self):
        row = {"requirements": "表格要求"}
        outcome = merge_link_fields(row, {"requirements": "链接要求"}, domain="a.com")
        assert outcome.conflicts == []

    def test_description_filled_when_empty_and_newlines_preserved(self):
        row = {"description": None}
        outcome = merge_link_fields(row, {"description": "第一段\n\n第二段"}, domain="a.com")
        # 不能把正文的换行压成空格 —— 岗位描述的可读性主要靠分段
        assert outcome.filled["description"] == "第一段\n\n第二段"


class TestGeoNormalisation:
    def test_city_and_region_become_short_names(self):
        # 写库与下拉共用一套短名规则，否则"导入写广东省、下拉给广东"永远筛不上
        row = {"city": None, "region": None}
        outcome = merge_link_fields(row, {"city": "深圳市", "region": "广东省"}, domain="a.com")
        assert outcome.filled == {"city": "深圳", "region": "广东"}

    def test_placeholder_geo_values_are_dropped(self):
        row = {"city": None}
        outcome = merge_link_fields(row, {"city": "未知"}, domain="a.com")
        assert outcome.filled == {}

    def test_placeholder_in_the_form_does_not_block_the_link(self):
        """清洗阶段给缺失城市补的「未知」不能当成"表格已填"。

        2026-09-27 真机验收抓到的缺陷：`pre_cleaner.py:281` 会给**每一行**缺失城市
        填「未知」，于是 `row["city"]` 永远非空 → 链接里的真实城市**永远补不进来**，
        还会在 stats 里记一条假冲突（form="未知" vs link="Arlington, TX"）。
        """
        row = {"city": "未知"}
        outcome = merge_link_fields(row, {"city": "深圳市"}, domain="a.com")
        assert outcome.filled == {"city": "深圳"}
        assert outcome.conflicts == []

    def test_full_name_in_form_is_not_a_false_conflict(self):
        # 表格写「广东省」、链接写「广东」是同一个地方 —— 归一化后必须不冲突
        row = {"city": "深圳市", "region": "广东省"}
        outcome = merge_link_fields(row, {"city": "深圳", "region": "广东"}, domain="a.com")
        assert outcome.conflicts == []
        assert outcome.provenance["city"] == "form"

    def test_genuinely_different_cities_still_conflict(self):
        row = {"city": "北京"}
        outcome = merge_link_fields(row, {"city": "深圳"}, domain="a.com")
        assert outcome.filled == {}
        assert [c["field"] for c in outcome.conflicts] == ["city"]


class TestProvenance:
    def test_records_source_per_field(self):
        row = {"company": None, "salary": "15K", "city": "深圳"}
        outcome = merge_link_fields(row, {"company": "示例科技", "salary": "30K"}, domain="jobs.example.com")
        # 链接补的 → link:<domain>；两边都有且保留了表格值 → form
        assert outcome.provenance["company"] == "link:jobs.example.com"
        assert outcome.provenance["salary"] == "form"

    def test_fields_the_link_never_mentioned_are_absent(self):
        # provenance 只记"做过判断"的字段。链接根本没提 city 时记一条 "form"
        # 只是噪音 —— 没有决策就没有来源可记。
        row = {"company": None, "city": "深圳", "industry": "互联网"}
        outcome = merge_link_fields(row, {"company": "示例科技"}, domain="a.com")
        assert "company" in outcome.provenance
        assert "city" not in outcome.provenance
        assert "industry" not in outcome.provenance

    def test_provenance_without_domain(self):
        outcome = merge_link_fields({}, {"company": "示例科技"})
        assert outcome.provenance["company"] == "link"

    def test_tier_is_carried_into_conflicts(self):
        row = {"salary": "15K"}
        outcome = merge_link_fields(
            row, {"salary": "30K"}, domain="a.com", tier_of={"salary": "jsonld"}
        )
        assert outcome.conflicts[0]["tier"] == "jsonld"


class TestRobustness:
    def test_empty_link_fields(self):
        outcome = merge_link_fields({"company": None}, {}, domain="a.com")
        assert outcome.filled == {} and outcome.conflicts == []

    def test_blank_link_values_are_ignored(self):
        outcome = merge_link_fields({"company": None}, {"company": "   "}, domain="a.com")
        assert outcome.filled == {}

    def test_non_dict_inputs_are_safe(self):
        assert merge_link_fields(None, {"company": "x"}).filled == {}
        assert merge_link_fields({"company": None}, None).filled == {}

    def test_short_fields_collapse_whitespace(self):
        row = {"company": None}
        outcome = merge_link_fields(row, {"company": "示例　科技  有限公司"}, domain="a.com")
        # 全角空格与连续空格都要压掉，否则同一个公司会因空白差异被当成两家
        assert outcome.filled["company"] == "示例 科技 有限公司"
