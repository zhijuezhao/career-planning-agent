"""B4（2026-10-03）单元测试：岗位等级划分（规则 C + 文本依据 + ≥3 终裁）。

用户决定回顾：
    * 顺序 **S2**：规则先给每条初判等级（带依据）→ 分组综合 → 规则终裁（组太小并入"不限"）；
    * 规则 **C**：绝对阈值 6000/12000，**但**岗位薪资跨度 ≥5× 时改用该岗位 p33/p66；
    * 最小样本量 **≥3**；
    * 面议：**有依据按依据，无依据"不限"**（不自己编）。
"""

from __future__ import annotations

from app.core.job_agent.levels import (
    ABS_JUNIOR_MAX,
    ABS_SENIOR_MIN,
    LEVEL_ADVANCED,
    LEVEL_BASIC,
    LEVEL_INTERMEDIATE,
    LEVEL_UNLIMITED,
    MIN_GROUP_SIZE,
    SalaryReference,
    assign_levels,
    build_salary_reference,
    classify_level,
    finalize_group_level,
    group_counts,
    normalise_level,
    salary_bounds,
)


class TestSalaryBounds:
    def test_range(self):
        assert salary_bounds("12000-13000") == (12000, 13000)

    def test_single_value(self):
        assert salary_bounds("9000") == (9000, 9000)

    def test_unusable(self):
        for value in (None, "", "None", "nan", "面议"):
            assert salary_bounds(value) is None, value


class TestClassifyLevelByText:
    def test_junior_text(self):
        level, basis = classify_level(title="Java", salary_normalized="20000", description="面向应届毕业生")
        assert level == LEVEL_BASIC
        assert basis.startswith("文本:")

    def test_intermediate_text(self):
        level, _ = classify_level(title="Java", salary_normalized="3000", description="要求3-5年经验")
        assert level == LEVEL_INTERMEDIATE

    def test_advanced_text_beats_lower_numbers(self):
        """`10年以上` 不能被 `1年以上` 之类的短模式抢先命中。"""
        level, basis = classify_level(
            title="架构师", salary_normalized=None, description="需10年以上研发经验"
        )
        assert level == LEVEL_ADVANCED
        assert "10年以上" in basis

    def test_text_beats_salary(self):
        """有文本依据时按文本 —— 否则高薪的应届岗会被误判成高级。"""
        level, basis = classify_level(
            title="Java", salary_normalized="25000", description="招聘应届生，经验不限"
        )
        assert level == LEVEL_BASIC
        assert basis.startswith("文本:")


class TestClassifyLevelBySalary:
    def test_absolute_thresholds(self):
        assert classify_level(title="A", salary_normalized="5000")[0] == LEVEL_BASIC
        assert classify_level(title="A", salary_normalized="8000")[0] == LEVEL_INTERMEDIATE
        assert classify_level(title="A", salary_normalized="15000")[0] == LEVEL_ADVANCED

    def test_boundaries_are_inclusive_on_the_upper_side(self):
        assert classify_level(title="A", salary_normalized=str(ABS_JUNIOR_MAX))[0] == LEVEL_INTERMEDIATE
        assert classify_level(title="A", salary_normalized=str(ABS_SENIOR_MIN))[0] == LEVEL_ADVANCED

    def test_basis_is_auditable(self):
        _level, basis = classify_level(title="A", salary_normalized="5200")
        assert basis == "薪资:5200→初级档（绝对阈值6000/12000）"

    def test_negotiable_without_text_is_unlimited(self):
        """用户要求：面议且无文本依据 → 「不限」，**不自己编**。"""
        level, basis = classify_level(title="APP推广", salary_normalized=None, description="负责地推拉新")
        assert level == LEVEL_UNLIMITED
        assert "无依据" in basis

    def test_negotiable_with_text_uses_text(self):
        level, _ = classify_level(title="APP推广", salary_normalized=None, description="欢迎应届生")
        assert level == LEVEL_BASIC


class TestSalaryReferenceSpanCalibration:
    def test_narrow_span_uses_absolute_thresholds(self):
        ref = build_salary_reference([4000, 5000, 6000])  # 1.5×
        assert ref.use_quantiles is False
        assert ref.thresholds() == (ABS_JUNIOR_MAX, ABS_SENIOR_MIN)

    def test_wide_span_switches_to_quantiles(self):
        """`Java 4000-37500`（21×）这类岗位必须用自己的分位点，否则高档位全被压成初级。"""
        ref = build_salary_reference([4000, 5000, 6000, 10000, 20000, 37500])
        assert ref.use_quantiles is True
        junior_max, senior_min = ref.thresholds()
        assert junior_max != ABS_JUNIOR_MAX or senior_min != ABS_SENIOR_MIN
        assert junior_max < senior_min

    def test_empty_reference(self):
        ref = build_salary_reference([])
        assert ref.low_min is None and ref.use_quantiles is False

    def test_calibrated_classification_uses_title_quantiles(self):
        ref = SalaryReference(p33=6000, p66=12000, use_quantiles=True)
        assert classify_level(title="A", salary_normalized="5000", reference=ref)[0] == LEVEL_BASIC
        assert classify_level(title="A", salary_normalized="8000", reference=ref)[0] == LEVEL_INTERMEDIATE
        assert classify_level(title="A", salary_normalized="20000", reference=ref)[0] == LEVEL_ADVANCED
        # 依据里要写明用的是岗位内分位点（可审计）
        _level, basis = classify_level(title="A", salary_normalized="8000", reference=ref)
        assert "岗位内p33" in basis


class TestGroupFinalization:
    def test_small_level_group_merges_into_unlimited(self):
        assert finalize_group_level(2, LEVEL_BASIC) == LEVEL_UNLIMITED
        assert finalize_group_level(MIN_GROUP_SIZE, LEVEL_BASIC) == LEVEL_BASIC

    def test_unlimited_is_never_merged(self):
        assert finalize_group_level(1, LEVEL_UNLIMITED) == LEVEL_UNLIMITED

    def test_group_counts(self):
        assert group_counts([("java", LEVEL_BASIC), ("java", LEVEL_BASIC), ("java", LEVEL_ADVANCED)]) == {
            ("java", LEVEL_BASIC): 2,
            ("java", LEVEL_ADVANCED): 1,
        }


class TestAssignLevels:
    def test_two_row_level_collapses_but_keeps_initial_level(self):
        rows = [
            {"title": "Java", "salary": "5000", "description": ""},
            {"title": "Java", "salary": "5500", "description": ""},
            {"title": "Java", "salary": "20000", "description": ""},
        ]
        results = assign_levels(rows)

        # 初级只有 2 条 (<3) → 终裁并入「不限」；高级 1 条也并入
        assert [r["group_level"] for r in results] == [LEVEL_UNLIMITED] * 3
        # 但初判结果必须保留，便于审计
        assert results[0]["level"] == LEVEL_BASIC
        assert "并入「不限」" in results[0]["level_basis"]

    def test_enough_rows_keep_their_level(self):
        rows = [{"title": "Java", "salary": "5000", "description": ""} for _ in range(3)]
        results = assign_levels(rows)
        assert {r["group_level"] for r in results} == {LEVEL_BASIC}

    def test_per_title_reference_is_used(self):
        """同一批里两个岗位各自算参照：跨度大的那个走分位点。"""
        java = [{"title": "Java", "salary": s, "description": ""} for s in
                ("4000", "5000", "6000", "10000", "20000", "37500")]
        narrow = [{"title": "档案管理", "salary": s, "description": ""} for s in
                  ("3000", "3500", "4000", "4500", "5000", "5500")]
        results = assign_levels([*java, *narrow])

        java_ref = results[0]["reference"]
        narrow_ref = results[-1]["reference"]
        assert java_ref.use_quantiles is True
        assert narrow_ref.use_quantiles is False

    def test_missing_title_is_unlimited(self):
        results = assign_levels([{"title": None, "salary": "20000"}])
        assert results[0]["group_level"] == LEVEL_UNLIMITED

    def test_every_row_gets_a_basis(self):
        """每条都必须留下依据字符串（可审计），不许有空依据。"""
        rows = [
            {"title": "A", "salary": "5000", "description": ""},
            {"title": "B", "salary": None, "description": "面议岗"},
            {"title": "C", "salary": "9000", "description": "3-5年"},
            {"title": None, "salary": "1"},
        ]
        for result in assign_levels(rows):
            assert result["level_basis"], "依据不能为空"
            assert result["level"] in (LEVEL_BASIC, LEVEL_INTERMEDIATE, LEVEL_ADVANCED, LEVEL_UNLIMITED)


class TestNormaliseLevel:
    """`normalise_level` 是唯一键的一部分 —— 不收敛的话每种写法都会各建一条画像。"""

    def test_known_levels_pass_through(self):
        for level in (LEVEL_BASIC, LEVEL_INTERMEDIATE, LEVEL_ADVANCED, LEVEL_UNLIMITED):
            assert normalise_level(level) == level

    def test_free_text_falls_back_to_unlimited(self):
        for value in ("3-5年经验", "高级工程师级别", "P7", None, "", "  ", "nan", "-"):
            assert normalise_level(value) == LEVEL_UNLIMITED, value

    def test_common_aliases(self):
        assert normalise_level("实习") == LEVEL_BASIC
        assert normalise_level("应届") == LEVEL_BASIC
        assert normalise_level("senior") == LEVEL_ADVANCED


class TestLevelDdlContract:
    """B4 的 5 项 DDL 在 ORM 层的体现（不需要 DB）。"""

    def test_level_is_not_null_with_default(self):
        """唯一键含 level，而 PG 唯一索引里 NULL 互不相等 —— 必须 NOT NULL + 默认值。"""
        from app.domain.models.job import JobProfile

        column = JobProfile.__table__.c.level
        assert column.nullable is False
        assert column.server_default is not None
        assert column.server_default.arg == LEVEL_UNLIMITED

    def test_new_columns_exist_on_models(self):
        """5 项 DDL 里的 3 个新列必须在 ORM 上有映射，否则写不进也读不出。"""
        from app.domain.models.job import JobProfile, JobRawData

        assert "salary_stats" in JobProfile.__table__.c
        assert "aggregate_card" in JobProfile.__table__.c
        assert "payload" in JobRawData.__table__.c
