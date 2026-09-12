from app.core.resume_agent.schemas import ParsedResume
from app.core.resume_agent.tools.five_layer_mapper import (
    five_layer_mapper,
    map_to_five_layers,
)

SAMPLE_PARSED = {
    "basic_info": {"name": "张三", "school": "XX大学", "degree": "本科"},
    "intention": {
        "target_industry": ["互联网"],
        "target_position": ["后端开发"],
        "target_city": ["上海"],
    },
    "traits": {
        "personality_tags": ["责任心强"],
        "strengths": ["逻辑分析"],
        "values": ["技术成长"],
        "evidence": ["学生会部长经历"],
    },
    "practice": {
        "work_experiences": [
            {"company": "XX科技", "position": "后端实习", "period": "2023.07-2023.09"},
        ],
        "projects": [
            {"name": "Demo项目", "role": "核心开发", "tech_stack": ["Java", "Spring"]},
        ],
    },
    "soft_skills": {
        "tags": ["沟通", "团队协作"],
        "scored": {"沟通": 75, "团队协作": 80},
        "evidence": {"沟通": "学生会部长"},
    },
    "hard_skills": {
        "tags": ["Java", "MySQL", "Python"],
        "scored": {"Java": 80, "MySQL": 75},
        "education": {"school": "XX大学", "degree": "本科", "major": "CS"},
        "certificates": ["英语六级"],
        "languages": ["英语CET-6"],
    },
}


def test_map_returns_all_five_keys():
    parsed = ParsedResume.model_validate(SAMPLE_PARSED)
    result = map_to_five_layers(parsed)
    assert set(result.keys()) == {"intention", "traits", "practice", "soft_skills", "hard_skills"}


def test_map_intention_fields():
    parsed = ParsedResume.model_validate(SAMPLE_PARSED)
    result = map_to_five_layers(parsed)
    assert result["intention"]["target_position"] == ["后端开发"]
    assert result["intention"]["target_city"] == ["上海"]


def test_map_hard_skills_preserves_education():
    parsed = ParsedResume.model_validate(SAMPLE_PARSED)
    result = map_to_five_layers(parsed)
    edu = result["hard_skills"]["education"]
    assert edu["school"] == "XX大学"
    assert edu["degree"] == "本科"


def test_map_soft_skills_scored():
    parsed = ParsedResume.model_validate(SAMPLE_PARSED)
    result = map_to_five_layers(parsed)
    assert result["soft_skills"]["scored"]["沟通"] == 75


def test_map_practice_work_and_projects():
    parsed = ParsedResume.model_validate(SAMPLE_PARSED)
    result = map_to_five_layers(parsed)
    assert len(result["practice"]["work_experiences"]) == 1
    assert len(result["practice"]["projects"]) == 1


def test_map_empty_parsed_resume():
    parsed = ParsedResume()
    result = map_to_five_layers(parsed)
    assert result["intention"]["target_position"] == []
    assert result["hard_skills"]["tags"] == []
    assert result["practice"]["projects"] == []


def test_tool_invoke():
    result = five_layer_mapper.invoke({"parsed_resume_dict": SAMPLE_PARSED})
    assert isinstance(result, dict)
    assert "intention" in result
    assert result["hard_skills"]["tags"] == ["Java", "MySQL", "Python"]
