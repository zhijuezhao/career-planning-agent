import json

import pytest
from app.core.llm.prompts.resume_parsing import (
    RESUME_PARSING_SYSTEM_PROMPT,
    build_resume_parsing_messages,
)
from app.core.resume_agent.schemas import (
    ALL_SUB_DIM_KEYS,
    SUB_DIMENSIONS,
    TOP_DIMENSIONS,
    DimensionScoring,
    ParsedResume,
    SubDimensionScores,
)


def test_prompt_contains_key_instructions():
    assert "JSON" in RESUME_PARSING_SYSTEM_PROMPT
    assert "basic_info" in RESUME_PARSING_SYSTEM_PROMPT
    assert "dimension_scoring" in RESUME_PARSING_SYSTEM_PROMPT
    assert "1-5" in RESUME_PARSING_SYSTEM_PROMPT
    assert "专业技术能力" in RESUME_PARSING_SYSTEM_PROMPT


def test_build_messages_structure():
    msgs = build_resume_parsing_messages("测试简历文本")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "测试简历文本" in msgs[1]["content"]


def test_parsed_resume_from_full_json():
    data = {
        "basic_info": {"name": "张三", "gender": "男", "age": 22, "school": "XX大学", "degree": "本科"},
        "intention": {"target_position": ["后端开发"], "target_city": ["上海"]},
        "traits": {"personality_tags": ["责任心强"], "strengths": ["逻辑分析"]},
        "practice": {
            "work_experiences": [{"company": "XX", "position": "实习", "period": "2023.07-2023.09"}],
            "projects": [{"name": "Demo", "role": "开发", "tech_stack": ["Java"]}],
        },
        "soft_skills": {"tags": ["沟通"], "scored": {"沟通": 75}},
        "hard_skills": {
            "tags": ["Java", "MySQL"],
            "scored": {"Java": 80},
            "education": {"school": "XX大学", "degree": "本科", "major": "CS"},
        },
    }
    parsed = ParsedResume.model_validate(data)
    assert parsed.basic_info.name == "张三"
    assert parsed.intention.target_position == ["后端开发"]
    assert parsed.hard_skills.tags == ["Java", "MySQL"]
    assert parsed.soft_skills.scored["沟通"] == 75


def test_parsed_resume_from_empty_json():
    parsed = ParsedResume.model_validate({})
    assert parsed.basic_info.name is None
    assert parsed.intention.target_position == []
    assert parsed.hard_skills.tags == []
    assert parsed.practice.projects == []
    assert parsed.dimension_scoring is None


def test_parsed_resume_roundtrip():
    original = ParsedResume(
        basic_info={"name": "李四", "school": "YY大学"},
        hard_skills={"tags": ["Python"], "scored": {"Python": 85}},
    )
    dumped = original.model_dump()
    restored = ParsedResume.model_validate(dumped)
    assert restored.basic_info.name == "李四"
    assert restored.hard_skills.scored["Python"] == 85


def test_top_dimensions_count():
    assert len(TOP_DIMENSIONS) == 6


def test_sub_dimensions_count():
    assert len(ALL_SUB_DIM_KEYS) == 13


def test_sub_dimension_scores_valid():
    s = SubDimensionScores(score=3.5, sub_dimensions={"核心专业技能": 3.0, "工具与技术栈": 4.0})
    assert s.score == 3.5
    assert s.sub_dimensions["核心专业技能"] == 3.0


def test_sub_dimension_scores_out_of_range():
    with pytest.raises(ValueError):
        SubDimensionScores(score=6.0, sub_dimensions={"核心专业技能": 3.0})


def test_sub_dimension_scores_sub_out_of_range():
    with pytest.raises(ValueError):
        SubDimensionScores(score=3.0, sub_dimensions={"核心专业技能": 0.5})


def _make_full_dimensions() -> dict:
    return {
        dim: {"score": 3.0, "sub_dimensions": {sub: 3.0 for sub in subs}}
        for dim, subs in SUB_DIMENSIONS.items()
    }


def test_dimension_scoring_valid():
    ds = DimensionScoring(
        total_dim_score=3.0,
        dimensions=_make_full_dimensions(),
    )
    assert ds.profile_type == "candidate"
    assert len(ds.dimensions) == 6


def test_dimension_scoring_missing_dimension_raises():
    partial = {"专业技术能力": {"score": 3.0, "sub_dimensions": {"核心专业技能": 3.0, "工具与技术栈": 3.0}}}
    with pytest.raises(ValueError, match="Missing top dimensions"):
        DimensionScoring(total_dim_score=3.0, dimensions=partial)


def test_parsed_resume_with_dimension_scoring():
    data = {
        "basic_info": {"name": "张三"},
        "dimension_scoring": {
            "profile_type": "candidate",
            "total_dim_score": 3.4,
            "dimensions": _make_full_dimensions(),
        },
    }
    parsed = ParsedResume.model_validate(data)
    assert parsed.dimension_scoring is not None
    assert parsed.dimension_scoring.total_dim_score == 3.4
    assert len(parsed.dimension_scoring.dimensions) == 6


def test_parsed_resume_without_dimension_scoring():
    parsed = ParsedResume.model_validate({"basic_info": {"name": "test"}})
    assert parsed.dimension_scoring is None


def test_parsed_resume_validates_sample_llm_output():
    raw_json = """{
        "basic_info": {"name": "王五", "email": "wang@example.com"},
        "intention": {"target_position": ["前端开发"], "target_industry": ["互联网"]},
        "traits": {"personality_tags": [], "strengths": [], "values": [], "evidence": []},
        "practice": {"campus_experiences": [], "work_experiences": [], "projects": [], "competitions": []},
        "soft_skills": {"tags": ["团队协作"], "scored": {"团队协作": 80}, "evidence": {}},
        "hard_skills": {
            "tags": ["Vue", "TypeScript"], "scored": {"Vue": 75},
            "certificates": [], "languages": ["英语CET-4"]
        }
    }"""
    data = json.loads(raw_json)
    parsed = ParsedResume.model_validate(data)
    assert parsed.basic_info.name == "王五"
    assert "Vue" in parsed.hard_skills.tags
    assert parsed.dimension_scoring is None
