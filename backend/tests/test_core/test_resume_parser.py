import json
from unittest.mock import AsyncMock, patch

import pytest
from app.core.resume_agent.schemas import SUB_DIMENSIONS, ParsedResume
from app.core.resume_agent.tools.resume_parser import (
    _parse_resume,
    _strip_json_fences,
    parse_resume_json,
)
from langchain_core.messages import AIMessage

VALID_RESUME_JSON = {
    "basic_info": {"name": "张三", "gender": "男", "age": 22, "school": "XX大学", "degree": "本科"},
    "intention": {"target_position": ["后端开发"], "target_city": ["上海"]},
    "traits": {"personality_tags": ["责任心强"], "strengths": [], "values": [], "evidence": []},
    "practice": {"campus_experiences": [], "work_experiences": [], "projects": [], "competitions": []},
    "soft_skills": {"tags": ["沟通"], "scored": {"沟通": 75}, "evidence": {}},
    "hard_skills": {
        "tags": ["Java", "MySQL"],
        "scored": {"Java": 80},
        "education": {"school": "XX大学", "degree": "本科"},
        "certificates": [],
        "languages": [],
    },
    "dimension_scoring": {
        "profile_type": "candidate",
        "total_dim_score": 3.4,
        "dimensions": {
            dim: {"score": 3.0, "sub_dimensions": {sub: 3.0 for sub in subs}}
            for dim, subs in SUB_DIMENSIONS.items()
        },
    },
}


def test_strip_json_fences_plain():
    raw = '{"name": "test"}'
    assert _strip_json_fences(raw) == '{"name": "test"}'


def test_strip_json_fences_with_markdown():
    raw = '```json\n{"name": "test"}\n```'
    assert _strip_json_fences(raw) == '{"name": "test"}'


def test_strip_json_fences_without_lang():
    raw = '```\n{"name": "test"}\n```'
    assert _strip_json_fences(raw) == '{"name": "test"}'


def test_parse_resume_json_valid():
    raw = json.dumps(VALID_RESUME_JSON)
    parsed = parse_resume_json(raw)
    assert isinstance(parsed, ParsedResume)
    assert parsed.basic_info.name == "张三"
    assert "Java" in parsed.hard_skills.tags


def test_parse_resume_json_with_fences():
    raw = f"```json\n{json.dumps(VALID_RESUME_JSON)}\n```"
    parsed = parse_resume_json(raw)
    assert parsed.basic_info.name == "张三"


def test_parse_resume_json_invalid_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_resume_json("not valid json at all")


@pytest.mark.asyncio
async def test_parse_resume_with_mock_gateway():
    mock_response = AIMessage(content=json.dumps(VALID_RESUME_JSON))
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.resume_parser.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await _parse_resume("简历文本内容")

    assert result["basic_info"]["name"] == "张三"
    assert "Java" in result["hard_skills"]["tags"]


@pytest.mark.asyncio
async def test_parse_resume_fallback_on_bad_json():
    mock_response = AIMessage(content="这不是有效的JSON内容")
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.resume_parser.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await _parse_resume("简历文本内容")

    parsed = ParsedResume.model_validate(result)
    assert parsed.basic_info.name is None
    assert parsed.hard_skills.tags == []


@pytest.mark.asyncio
async def test_tool_ainvoke_with_mock():
    from app.core.resume_agent.tools.resume_parser import resume_parser

    mock_response = AIMessage(content=json.dumps(VALID_RESUME_JSON))
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.resume_parser.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await resume_parser.ainvoke({"resume_text": "测试简历"})

    assert isinstance(result, dict)
    assert result["basic_info"]["name"] == "张三"


@pytest.mark.asyncio
async def test_parse_resume_with_dimension_scoring():
    mock_response = AIMessage(content=json.dumps(VALID_RESUME_JSON))
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.resume_parser.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await _parse_resume("简历文本内容")

    assert result["dimension_scoring"] is not None
    assert result["dimension_scoring"]["total_dim_score"] == 3.4
    assert len(result["dimension_scoring"]["dimensions"]) == 6


@pytest.mark.asyncio
async def test_parse_resume_without_dimension_scoring():
    data_no_scoring = {k: v for k, v in VALID_RESUME_JSON.items() if k != "dimension_scoring"}
    mock_response = AIMessage(content=json.dumps(data_no_scoring))
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.resume_parser.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await _parse_resume("简历文本内容")

    assert result["dimension_scoring"] is None
    assert result["basic_info"]["name"] == "张三"
