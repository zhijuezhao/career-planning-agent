"""B4-c（2026-10-03）单元测试：岗位聚合的纯数据层。

覆盖：分组（按 `(岗位名, 终裁等级)`）、组输入拼装（带字符预算）、
薪资统计（用户要求"两者都存"）、综合卡防御性解析（键名漂移兜底）。
"""

from __future__ import annotations

from app.core.job_agent.aggregate import (
    MAX_GROUP_INPUT_CHARS,
    build_group_input,
    build_payload,
    compute_salary_stats,
    group_raw_rows,
    normalise_card,
)


def _raw(title: str, salary: str | None = None, **extra) -> dict:
    return {"title": title, "salary": salary, "description": extra.pop("description", ""), **extra}


class TestBuildPayload:
    def test_extracts_and_source_are_separated(self):
        payload = build_payload(
            {
                "title": "Java",
                "hard_skills": ["Java", "MySQL"],
                "education_requirement": "本科",
                "code": "CC1",
                "district": "杨浦区",
                "company_detail": "公司介绍",
                "description": "很长的详情",  # 有列，不进 payload
            }
        )
        assert payload["extract"]["hard_skills"] == ["Java", "MySQL"]
        assert payload["extract"]["education_requirement"] == "本科"
        assert payload["source"]["code"] == "CC1"
        assert payload["source"]["district"] == "杨浦区"
        assert "description" not in payload["extract"]

    def test_empty_values_are_omitted(self):
        payload = build_payload({"hard_skills": None, "code": ""})
        assert payload == {"extract": {}, "source": {}}


class TestGroupRawRows:
    def test_groups_by_title_and_level(self):
        # 3 条 <6000 → 初级成立（≥3）；1 条 20000 → 高级只有 1 条 → 并入「不限」
        rows = [
            _raw("Java", "5000"),
            _raw("Java", "5200"),
            _raw("Java", "5400"),
            _raw("Java", "20000"),
            _raw("前端开发", "8000"),
        ]
        groups = group_raw_rows(rows)
        keys = set(groups)
        assert ("java", "初级") in keys
        assert ("java", "不限") in keys  # 高级 1 条被终裁并入
        assert ("前端开发", "不限") in keys
        assert len(groups[("java", "初级")]) == 3

    def test_boundary_value_6000_is_intermediate(self):
        """`6000` 不小于 6000 → 中级（阈值是「< 6000 才初级」）。"""
        rows = [_raw("Java", "6000") for _ in range(3)]
        groups = group_raw_rows(rows)
        assert ("java", "中级") in groups

    def test_titles_filter(self):
        rows = [_raw("Java", "5000"), _raw("Java", "5200"), _raw("Java", "5400"), _raw("前端开发", "9000")]
        groups = group_raw_rows(rows, titles={"java"})
        assert all(key[0] == "java" for key in groups)

    def test_reads_fields_from_payload_when_no_column(self):
        """落库后技能/等级在 payload 里（没有列），分组必须能读到。"""
        rows = [
            {
                "title": "Java",
                "salary": "8000",
                "description": "",
                "payload": {"extract": {"hard_skills": ["Java"], "level": "初级"}, "source": {"code": "C1"}},
            }
        ]
        groups = group_raw_rows(rows)
        (key, group_rows), = groups.items()
        assert key[0] == "java"
        assert group_rows[0]["payload"]["extract"]["hard_skills"] == ["Java"]

    def test_rows_without_title_are_skipped(self):
        assert group_raw_rows([_raw(None, "9000")]) == {}

    def test_empty_input(self):
        assert group_raw_rows([]) == {}


class TestBuildGroupInput:
    def test_includes_key_fields(self):
        rows = group_raw_rows([_raw("Java", "8000", description="负责后端开发", company="A公司", city="北京")])
        (group,) = rows.values()
        text = build_group_input(group)
        assert "Java" in text
        assert "A公司" in text
        assert "8000" in text
        assert "负责后端开发" in text

    def test_detail_is_truncated(self):
        rows = group_raw_rows([_raw("Java", "8000", description="x" * 5000)])
        (group,) = rows.values()
        text = build_group_input(group, per_row_detail_chars=50)
        assert "x" * 51 not in text
        assert "…" in text

    def test_respects_total_char_budget(self):
        rows = group_raw_rows([_raw("Java", "8000", description="y" * 400) for _ in range(200)])
        (group,) = rows.values()
        text = build_group_input(group, per_row_detail_chars=400, max_chars=2_000)
        assert len(text) < MAX_GROUP_INPUT_CHARS
        assert "因长度预算省略" in text


class TestComputeSalaryStats:
    def test_both_envelope_and_median(self):
        """用户明确要求「两者都存」。"""
        rows = [
            _raw("Java", "4000-6000", salary_raw="4000-6000元"),
            _raw("Java", "8000-10000", salary_raw="8000-10000元"),
            _raw("Java", "20000-37500", salary_raw="2-3.75万"),
        ]
        stats = compute_salary_stats(rows)
        assert stats["envelope"] == "4000-37500"
        assert stats["median"] == "8000-10000"
        assert stats["n"] == 3
        assert "4000-6000元" in stats["raw"]

    def test_negotiable_counted_separately(self):
        rows = [_raw("Java", None, salary_raw="面议"), _raw("Java", "8000-10000", salary_raw="8-10K")]
        stats = compute_salary_stats(rows)
        assert stats["n"] == 1
        assert stats["negotiable"] == 1
        assert stats["envelope"] == "8000-10000"

    def test_single_value_rows_collapse_median(self):
        """组内全是单值薪资时，中位数会退化成同一个数 —— 渲染成单值而不是 `5200-5200`。"""
        rows = [_raw("Java", "5000"), _raw("Java", "5200"), _raw("Java", "5400")]
        stats = compute_salary_stats(rows)
        assert stats["envelope"] == "5000-5400"
        assert stats["median"] == "5200"

    def test_no_parseable_salary(self):
        stats = compute_salary_stats([_raw("Java", None, salary_raw="面议")])
        assert stats["envelope"] is None and stats["median"] is None and stats["n"] == 0

    def test_raw_texts_are_deduped_and_bounded(self):
        rows = [_raw("Java", "8000", salary_raw=f"写法{i}") for i in range(10)]
        stats = compute_salary_stats(rows)
        assert len(stats["raw"]) <= 5


class TestNormaliseCard:
    def test_identity_fields_come_from_caller(self):
        """模型改了 role/level/posting_count 也不采纳，但要记进问题列表。"""
        card, problems = normalise_card(
            {"role": "模型乱写", "level": "高级", "posting_count": 999},
            role="Java",
            level="初级",
            posting_count=7,
        )
        assert card["role"] == "Java"
        assert card["level"] == "初级"
        assert card["posting_count"] == 7
        assert any("不一致" in p for p in problems)

    def test_string_is_coerced_to_list(self):
        card, _ = normalise_card(
            {"core_skills": "Java", "excluded_noise": None}, role="Java", level="初级", posting_count=3
        )
        assert card["core_skills"] == ["Java"]
        assert card["excluded_noise"] == []

    def test_missing_keys_are_reported(self):
        card, problems = normalise_card({"core_skills": ["Java"]}, role="Java", level="初级", posting_count=3)
        assert card["core_skills"] == ["Java"]
        assert any("缺少键" in p for p in problems)
        assert any("excluded_noise" in p for p in problems)

    def test_non_dict_is_rejected(self):
        card, problems = normalise_card(["not", "a", "dict"], role="Java", level="初级", posting_count=3)
        assert card == {}
        assert problems

    def test_full_card_passes_clean(self):
        payload = {
            "role": "Java",
            "level": "初级",
            "posting_count": 3,
            "consensus_duties": ["后端开发"],
            "consensus_requirements": ["本科"],
            "core_skills": ["Java"],
            "bonus_skills": [],
            "salary_range": {"envelope": "4000-15000", "median": "6000-9000"},
            "education_range": "大专~本科",
            "experience_range": "应届~3年",
            "city_distribution": ["北京"],
            "top_companies": ["A公司"],
            "differentiators": [],
            "excluded_noise": [],
            "level_objections": [],
        }
        card, problems = normalise_card(payload, role="Java", level="初级", posting_count=3)
        assert problems == []
        assert card["salary_range"]["envelope"] == "4000-15000"
