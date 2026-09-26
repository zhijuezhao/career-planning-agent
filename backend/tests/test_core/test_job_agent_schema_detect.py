"""A/B 层（列与体裁自适应）单测：让导入管线既能吃「招聘海报」，也能吃「职业发展路线表」。

背景（2026-09-26 实测）：用户的 `job_infor.xlsx` 是职业发展路线表
（`岗位名称 / 岗位晋升 / 换岗 / 所需证书 / 核心技能`），而管线只认招聘体裁的列名
（公司/城市/薪资/职位描述/任职要求）→ 84 条里 **81 条被质检按"缺公司/城市/薪资"判 D 丢弃**。
本文件锁住"能识别这类表、并把它的列归一化成管线看得懂的字段"的行为。
"""

from app.core.job_agent.tools.schema_detect import (
    EXTRA_COLUMN_ALIASES,
    detect_schema,
    merge_extra_columns,
    normalize_rows,
)

#: 用户表的一行（列名经 `EXTRA_COLUMN_ALIASES` 映射后的形态）
CAREER_ROW = {
    "title": "Java",
    "skills_detail": "Java 8+/Spring Boot/Redis",
    "certificates": "软考、OCP",
    "career_advancement": "全栈工程师 / 技术经理",
    "role_transition": "测试开发 / Python / 数据工程师",
}

#: 招聘体裁的一行
JOB_ROW = {
    "title": "前端开发工程师",
    "company": "某科技有限公司",
    "city": "北京",
    "salary": "20000-30000",
}


class TestMergeExtraColumns:
    def test_merges_with_chinese_labels(self):
        merged = merge_extra_columns(CAREER_ROW)

        assert merged["requirements"] == "核心技能：Java 8+/Spring Boot/Redis\n所需证书：软考、OCP"
        assert merged["description"] == (
            "岗位晋升：全栈工程师 / 技术经理\n换岗方向：测试开发 / Python / 数据工程师"
        )
        # 中间键已被消费，不再残留在行里
        assert "skills_detail" not in merged
        assert "certificates" not in merged
        assert "career_advancement" not in merged
        assert "role_transition" not in merged

    def test_appends_to_existing_description(self):
        """混列表（既有职位描述、又有晋升列）——两份信息都要保留，不能互相覆盖。"""
        merged = merge_extra_columns({**CAREER_ROW, "description": "原职位描述"})
        assert merged["description"].startswith("原职位描述")
        assert "岗位晋升：" in merged["description"]

    def test_job_posting_row_is_untouched(self):
        assert merge_extra_columns(JOB_ROW) == JOB_ROW

    def test_empty_values_are_ignored(self):
        merged = merge_extra_columns({"title": "x", "skills_detail": "   ", "certificates": None})
        assert "requirements" not in merged


class TestDetectSchema:
    def test_career_roadmap(self):
        _rows, profile = normalize_rows([CAREER_ROW])
        assert profile.genre == "career_roadmap"
        assert profile.has_career_markers is True
        assert profile.has_recruiting_fields is False
        assert profile.is_job_posting is False

    def test_job_posting(self):
        _rows, profile = normalize_rows([JOB_ROW])
        assert profile.genre == "job_posting"
        assert profile.is_job_posting is True

    def test_mixed_table(self):
        """同一张表既给了公司/薪资、又给了技能/晋升列 → mixed，并**走自适应口径**。"""
        _rows, profile = normalize_rows([{**JOB_ROW, **CAREER_ROW}])
        assert profile.genre == "mixed"
        assert profile.has_recruiting_fields is True
        assert profile.has_career_markers is True
        assert profile.is_job_posting is False

    def test_unknown_table(self):
        _rows, profile = normalize_rows([{"title": "x", "summary": "y"}])
        assert profile.genre == "unknown"
        assert profile.is_job_posting is False

    def test_detect_schema_on_unmerged_rows(self):
        assert detect_schema([CAREER_ROW]).genre == "career_roadmap"

    def test_blank_recruiting_values_do_not_count(self):
        """空串/纯空白/None 不算"有公司/城市/薪资"字段。"""
        _rows, profile = normalize_rows(
            [{"title": "x", "company": "", "city": None, "salary": "   "}]
        )
        assert profile.has_recruiting_fields is False

    def test_as_dict_is_serialisable(self):
        _rows, profile = normalize_rows([CAREER_ROW])
        payload = profile.as_dict()
        assert payload["genre"] == "career_roadmap"
        assert "requirements" in payload["fields"]  # 合并后的规范字段
        assert isinstance(payload["fields"], list)

    def test_alias_table_covers_user_columns(self):
        """用户表的四类列必须都在别名表里，否则会作为未知列被丢弃。"""
        for column in ("核心技能", "所需证书", "岗位晋升", "换岗"):
            assert column in EXTRA_COLUMN_ALIASES
