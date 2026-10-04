"""B5（2026-10-03）单元测试：技能归一化。

用户原话与选择::

    技能只提取最重要的部分，如 java开发，java，只要 java
    → 仅形态归约 + 核心 ≤20 / 加分 ≤10

本文件重点锁三件事：
1. **该归约的归约**（`Java开发`→`Java`、`MySQL数据库`→`MySQL`）；
2. **不该归约的不动**（`C/C++` 不能变 `C`、`项目管理工具` 不能变 `项目管理`、
   `Google` 不能变 `Go`、`JavaScript` 不能变 `Java`）；
3. **匹配口径**（两侧都归约后再取交集，否则 `Java开发` 与 `Java` 对不上）。
"""

from __future__ import annotations

import pytest
from app.core.skills import (
    BONUS_SKILL_LIMIT,
    CORE_SKILL_LIMIT,
    TECH_VOCABULARY,
    match_skill_overlap,
    normalise_skill,
    normalise_skills,
    unmapped_skills,
)


class TestFormReduction:
    """① 该归约的必须归约（用户点名的形态）。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Java开发", "Java"),  # 用户原话里的例子
            ("java", "Java"),
            ("JAVA", "Java"),
            ("Java语言", "Java"),
            ("熟悉Java", "Java"),
            ("掌握Java开发", "Java"),
            ("具备Java开发经验", "Java"),  # 前缀 + 连写后缀
            ("MySQL数据库", "MySQL"),
            ("redis缓存", "Redis"),
            ("Spring Boot框架", "Spring Boot"),
            ("springboot", "Spring Boot"),
            ("spring-boot", "Spring Boot"),
            ("熟练使用Docker容器", "Docker"),
            ("Python编程", "Python"),
            ("golang", "Go"),
            ("js", "JavaScript"),
            ("k8s", "Kubernetes"),
        ],
    )
    def test_reduces_to_base_term(self, raw, expected):
        assert normalise_skill(raw) == expected


class TestNoOverReduction:
    """② 不该归约的必须原样保留（机械剥后缀会在这里全错）。"""

    def test_c_slash_c_plus_plus_is_not_c(self):
        """`C/C++` 是独立技能，绝不能被归约成 `C`。"""
        assert normalise_skill("C/C++") == "C/C++"

    def test_c_plus_plus_and_c_sharp_survive(self):
        assert normalise_skill("C++") == "C++"
        assert normalise_skill("C#") == "C#"

    def test_tool_is_not_a_modifier(self):
        """`项目管理工具` 里 `工具` 是实义中心语，归约掉就丢信息了。"""
        assert normalise_skill("项目管理工具") == "项目管理工具"

    def test_latin_word_boundaries(self):
        """拉丁词必须做词边界：否则 `Google`→`Go`、`JavaScript`→`Java`。"""
        assert normalise_skill("Google") == "Google"
        assert normalise_skill("JavaScript") == "JavaScript"

    def test_unknown_skill_preserved(self):
        assert normalise_skill("钣金生产") == "钣金生产"
        assert normalise_skill("地推推广") == "地推推广"

    def test_empty_inputs(self):
        assert normalise_skill(None) == ""
        assert normalise_skill("") == ""
        assert normalise_skill("   ") == ""


class TestNormaliseSkills:
    def test_dedupes_case_insensitively(self):
        assert normalise_skills(["Java开发", "java", "JAVA语言"]) == ["Java"]

    def test_preserves_first_seen_order(self):
        assert normalise_skills(["MySQL数据库", "Java开发", "Redis缓存"]) == ["MySQL", "Java", "Redis"]

    def test_limit_truncates(self):
        skills = ["Java", "Python", "Go", "Rust", "Scala", "Kotlin", "Perl", "Lua"]
        assert normalise_skills(skills, limit=3) == ["Java", "Python", "Go"]

    def test_limits_match_user_decision(self):
        """用户 2026-10-03：核心 ≤20、加分 ≤10。"""
        assert CORE_SKILL_LIMIT == 20
        assert BONUS_SKILL_LIMIT == 10

    def test_accepts_a_single_string(self):
        assert normalise_skills("Java开发") == ["Java"]

    def test_empty(self):
        assert normalise_skills(None) == []
        assert normalise_skills([]) == []


class TestUnmappedSkills:
    def test_reports_terms_missing_from_vocabulary(self):
        assert unmapped_skills(["Java开发", "钣金生产"]) == ["钣金生产"]

    def test_empty_when_all_known(self):
        assert unmapped_skills(["Java", "MySQL"]) == []


class TestMatchSkillOverlap:
    def test_matched_and_missing(self):
        result = match_skill_overlap(
            ["Java开发", "MySQL数据库", "Python"],
            ["Java", "MySQL", "Redis", "Docker"],
        )
        assert result["matched"] == ["Java", "MySQL"]
        assert result["missing"] == ["Redis", "Docker"]
        assert result["student_only"] == ["Python"]
        assert result["job_total"] == 4
        assert result["student_total"] == 3
        assert result["hit_ratio"] == 0.5

    def test_reduction_makes_both_sides_comparable(self):
        """不归约的话 `Java开发` 与 `Java` 是两条技能、永远命中不了。"""
        result = match_skill_overlap(["Java开发"], ["Java"])
        assert result["hit_ratio"] == 1.0

    def test_job_without_skills_is_not_full_match(self):
        """岗位没写技能 ≠ 学生全命中 —— 由调用方决定是否计入这一维。"""
        result = match_skill_overlap(["Java"], [])
        assert result["hit_ratio"] == 0.0
        assert result["job_total"] == 0

    def test_empty_student(self):
        result = match_skill_overlap([], ["Java"])
        assert result["hit_ratio"] == 0.0
        assert result["missing"] == ["Java"]


class TestVocabularySanity:
    def test_vocabulary_is_sorted_longest_first(self):
        """最长匹配的前提：词表按长度降序。"""
        lengths = [len(term) for term in TECH_VOCABULARY]
        assert lengths == sorted(lengths, reverse=True)

    def test_vocabulary_has_no_duplicates(self):
        lowered = [term.lower() for term in TECH_VOCABULARY]
        assert len(lowered) == len(set(lowered))

    def test_vocabulary_covers_really_observed_skills(self):
        """覆盖真实抽取/综合产出过的技能（来自 2026-10-04 的活体验证）。"""
        observed = [
            "Java", "MySQL", "Spring Boot", "Redis", "Python", "Go", "C#", "Oracle",
            "HTML5", "Selenium", "Jira", "Postman", "SQL", "Linux", "PyTorch",
            "TensorFlow", "C/C++", "项目管理", "沟通能力", "团队合作精神",
            "功能测试", "接口测试", "测试用例设计", "缺陷跟踪与管理",
        ]
        unmapped = unmapped_skills(observed)
        assert unmapped == [], f"词表缺这些真实技能：{unmapped}"
