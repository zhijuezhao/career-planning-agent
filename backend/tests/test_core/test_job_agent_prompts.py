from app.core.llm.prompts.industry_report import (
    INDUSTRY_REPORT_SYSTEM_PROMPT,
    INDUSTRY_REPORT_USER_TEMPLATE,
    build_industry_report_messages,
)
from app.core.llm.prompts.job_extract import (
    JOB_EXTRACT_SYSTEM_PROMPT,
    JOB_EXTRACT_USER_TEMPLATE,
    build_extract_messages,
)
from app.core.llm.prompts.job_portrait import (
    JOB_PORTRAIT_SYSTEM_PROMPT,
    JOB_PORTRAIT_USER_TEMPLATE,
    build_portrait_messages,
)
from app.core.llm.prompts.job_quality import (
    JOB_QUALITY_SYSTEM_PROMPT,
    JOB_QUALITY_USER_TEMPLATE,
    build_quality_messages,
)


class TestJobQualityPrompt:
    def test_constants_exist(self):
        assert isinstance(JOB_QUALITY_SYSTEM_PROMPT, str)
        assert len(JOB_QUALITY_SYSTEM_PROMPT) > 100
        assert isinstance(JOB_QUALITY_USER_TEMPLATE, str)
        assert "{job_data}" in JOB_QUALITY_USER_TEMPLATE

    def test_build_messages_structure(self):
        messages = build_quality_messages('{"title": "前端工程师"}')
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "前端工程师" in messages[1]["content"]

    def test_genre_selects_scoring_prompt(self):
        """B 层：非招聘体裁（career_roadmap / mixed / unknown）必须换用自适应口径。

        否则职业发展路线表会因为"没有公司/城市/薪资"被结构性判 D
        ——2026-09-26 实测 84 条丢 81 条。
        """
        from app.core.llm.prompts.job_quality import (
            JOB_QUALITY_ADAPTIVE_SYSTEM_PROMPT,
        )

        assert build_quality_messages('{"title": "x"}')[0]["content"] == JOB_QUALITY_SYSTEM_PROMPT
        assert (
            build_quality_messages('{"title": "x"}', genre="job_posting")[0]["content"]
            == JOB_QUALITY_SYSTEM_PROMPT
        )
        for genre in ("career_roadmap", "mixed", "unknown"):
            system = build_quality_messages('{"title": "x"}', genre=genre)[0]["content"]
            assert system == JOB_QUALITY_ADAPTIVE_SYSTEM_PROMPT
            assert "不计入分母" in system  # 关键约束：本表没有的字段不扣分


class TestJobExtractPrompt:
    def test_constants_exist(self):
        assert isinstance(JOB_EXTRACT_SYSTEM_PROMPT, str)
        assert len(JOB_EXTRACT_SYSTEM_PROMPT) > 100
        assert isinstance(JOB_EXTRACT_USER_TEMPLATE, str)
        assert "{job_text}" in JOB_EXTRACT_USER_TEMPLATE

    def test_build_messages_structure(self):
        messages = build_extract_messages("招聘Java开发工程师")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Java" in messages[1]["content"]


class TestJobPortraitPrompt:
    def test_constants_exist(self):
        assert isinstance(JOB_PORTRAIT_SYSTEM_PROMPT, str)
        assert len(JOB_PORTRAIT_SYSTEM_PROMPT) > 100
        assert isinstance(JOB_PORTRAIT_USER_TEMPLATE, str)
        assert "{job_data}" in JOB_PORTRAIT_USER_TEMPLATE

    def test_build_messages_structure(self):
        messages = build_portrait_messages('{"title": "后端工程师"}')
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "后端工程师" in messages[1]["content"]


class TestIndustryReportPrompt:
    def test_constants_exist(self):
        assert isinstance(INDUSTRY_REPORT_SYSTEM_PROMPT, str)
        assert len(INDUSTRY_REPORT_SYSTEM_PROMPT) > 100
        assert isinstance(INDUSTRY_REPORT_USER_TEMPLATE, str)
        assert "{collected_data}" in INDUSTRY_REPORT_USER_TEMPLATE

    def test_build_messages_structure(self):
        messages = build_industry_report_messages("行业数据")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "行业数据" in messages[1]["content"]

    def test_all_dimensions_mentioned(self):
        """Industry report prompt should mention all five sections."""
        assert "### 1. 行业概览" in INDUSTRY_REPORT_SYSTEM_PROMPT
        assert "### 2. 热门岗位趋势" in INDUSTRY_REPORT_SYSTEM_PROMPT
        assert "### 3. 薪资水平分析" in INDUSTRY_REPORT_SYSTEM_PROMPT
        assert "### 4. 技能需求变化" in INDUSTRY_REPORT_SYSTEM_PROMPT
        assert "### 5. 行业前景展望" in INDUSTRY_REPORT_SYSTEM_PROMPT
