from app.core.job_agent.report import generate_quality_report


class TestGenerateQualityReport:
    def test_returns_markdown_with_basic_stats(self):
        report = generate_quality_report(
            total_input=1000,
            total_passed=850,
            total_rejected=150,
            source="test.xlsx",
        )
        assert "数据质量报告" in report
        assert "1000" in report
        assert "850" in report
        assert "150" in report
        assert "test.xlsx" in report

    def test_includes_grade_distribution(self):
        report = generate_quality_report(
            total_input=1000,
            total_passed=850,
            total_rejected=150,
            grade_distribution={"A": 200, "B": 400, "C": 250, "D": 150},
        )
        assert "## 2. 等级分布" in report
        assert "200" in report
        assert "400" in report
        assert "250" in report
        assert "150" in report

    def test_includes_dedup_stats(self):
        report = generate_quality_report(
            total_input=1000,
            total_passed=850,
            total_rejected=150,
            dedup_stats={"exact": 30, "fuzzy": 15},
        )
        assert "## 3. 去重统计" in report
        assert "30" in report
        assert "15" in report

    def test_includes_field_completeness(self):
        report = generate_quality_report(
            total_input=100,
            total_passed=90,
            total_rejected=10,
            field_completeness={"title": 1.0, "salary": 0.85},
        )
        assert "## 4. 字段完整度" in report
        assert "title" in report
        assert "salary" in report
        assert "100.0%" in report
        assert "85.0%" in report

    def test_includes_extra_notes(self):
        report = generate_quality_report(
            total_input=100,
            total_passed=90,
            total_rejected=10,
            extra_notes=["薪资字段缺失较多", "行业名称存在脏值"],
        )
        assert "## 5. 质量备注" in report
        assert "薪资字段缺失较多" in report
        assert "行业名称存在脏值" in report

    def test_handles_zero_input(self):
        report = generate_quality_report(
            total_input=0,
            total_passed=0,
            total_rejected=0,
        )
        assert "0" in report
        assert "0.0%" in report
