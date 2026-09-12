from unittest.mock import AsyncMock, patch

import pytest
from app.core.resume_agent.tools.report_builder import (
    _build_report,
    report_builder,
)
from langchain_core.messages import AIMessage

SAMPLE_FIVE_LAYERS = {
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
}

SAMPLE_DIMENSION_SCORING = {
    "profile_type": "candidate",
    "total_dim_score": 3.5,
    "dimensions": {
        "专业技术能力": {"score": 4.0, "sub_dimensions": {"核心专业技能": 4.0, "工具与技术栈": 4.0}},
        "实践经验背景": {"score": 3.0, "sub_dimensions": {"相关经历匹配度": 3.0, "实践深度与产出": 3.0}},
        "通用软素质": {
            "score": 3.5,
            "sub_dimensions": {"沟通协作能力": 4.0, "问题解决能力": 3.0, "责任心与执行力": 3.5},
        },
        "职业匹配度": {"score": 3.5, "sub_dimensions": {"方向与行业匹配": 4.0, "地域与薪资匹配": 3.0}},
        "成长潜力": {"score": 4.0, "sub_dimensions": {"学习能力": 4.0, "进取心与可塑性": 4.0}},
        "基础资质条件": {"score": 3.0, "sub_dimensions": {"学历与专业对口": 3.0, "资质认证": 3.0}},
    },
}

SAMPLE_BASIC_INFO = {"name": "张三", "school": "XX大学", "degree": "本科"}

MOCK_REPORT_TEXT = """\
## 个人概况
张三，XX大学本科毕业，求职意向为后端开发，目标城市上海。

## 能力优势分析
你在专业技术能力和成长潜力方面表现突出。

## 待提升领域
建议加强实践经验积累和相关证书考取。

## 职业匹配建议
推荐互联网/软件行业的后端开发岗位。

## 成长路径建议
短期：深入学习Spring Boot框架；中期：参与开源项目积累经验。
"""


@pytest.mark.asyncio
async def test_build_report_success():
    mock_response = AIMessage(content=MOCK_REPORT_TEXT)
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.report_builder.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await _build_report(
            five_layers=SAMPLE_FIVE_LAYERS,
            dimension_scoring=SAMPLE_DIMENSION_SCORING,
            basic_info=SAMPLE_BASIC_INFO,
        )

    assert "## 个人概况" in result
    assert "张三" in result
    assert "以上内容仅供参考" in result


@pytest.mark.asyncio
async def test_build_report_appends_disclaimer():
    mock_response = AIMessage(content="简短报告内容")
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.report_builder.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await _build_report(
            five_layers=SAMPLE_FIVE_LAYERS,
            dimension_scoring=None,
            basic_info={},
        )

    assert result.endswith("不构成就业承诺或专业职业咨询意见。*")


@pytest.mark.asyncio
async def test_build_report_disclaimer_idempotent():
    text_with_disclaimer = MOCK_REPORT_TEXT + "\n\n---\n*以上内容仅供参考，不构成就业承诺或专业职业咨询意见。*"
    mock_response = AIMessage(content=text_with_disclaimer)
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.report_builder.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await _build_report(
            five_layers=SAMPLE_FIVE_LAYERS,
            dimension_scoring=SAMPLE_DIMENSION_SCORING,
            basic_info=SAMPLE_BASIC_INFO,
        )

    assert result.count("以上内容仅供参考") == 1


@pytest.mark.asyncio
async def test_tool_ainvoke_returns_dict():
    mock_response = AIMessage(content=MOCK_REPORT_TEXT)
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.report_builder.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await report_builder.ainvoke({
            "five_layers": SAMPLE_FIVE_LAYERS,
            "dimension_scoring": SAMPLE_DIMENSION_SCORING,
            "basic_info": SAMPLE_BASIC_INFO,
        })

    assert isinstance(result, dict)
    assert "report_text" in result
    assert "## 个人概况" in result["report_text"]


@pytest.mark.asyncio
async def test_tool_ainvoke_without_optional_args():
    mock_response = AIMessage(content="基础报告")
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.report_builder.get_llm_gateway",
        return_value=mock_gateway,
    ):
        result = await report_builder.ainvoke({
            "five_layers": SAMPLE_FIVE_LAYERS,
        })

    assert isinstance(result, dict)
    assert "report_text" in result


@pytest.mark.asyncio
async def test_build_report_passes_correct_messages():
    mock_response = AIMessage(content="报告")
    mock_gateway = AsyncMock()
    mock_gateway.ainvoke = AsyncMock(return_value=mock_response)

    with patch(
        "app.core.resume_agent.tools.report_builder.get_llm_gateway",
        return_value=mock_gateway,
    ):
        await _build_report(
            five_layers=SAMPLE_FIVE_LAYERS,
            dimension_scoring=SAMPLE_DIMENSION_SCORING,
            basic_info=SAMPLE_BASIC_INFO,
        )

    call_args = mock_gateway.ainvoke.call_args[0][0]
    assert len(call_args) == 2
    assert call_args[0]["role"] == "system"
    assert call_args[1]["role"] == "user"
    user_content = call_args[1]["content"]
    assert "五层能力画像" in user_content
    assert "维度评分" in user_content
    assert "张三" in user_content
    assert "XX大学" in user_content
