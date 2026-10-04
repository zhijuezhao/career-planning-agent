from unittest.mock import AsyncMock, patch

import pytest
from app.core.resume_agent.embedding_text import build_portrait_text
from app.core.resume_agent.tools.profile_embedder import profile_embedder

SAMPLE_FIVE_LAYERS = {
    "intention": {
        "target_position": ["后端开发"],
        "target_industry": ["互联网"],
        "target_city": ["上海"],
    },
    "traits": {"strengths": ["逻辑分析", "学习能力"]},
    "practice": {
        "work_experiences": [
            {"company": "XX科技", "position": "后端实习"},
        ],
        "projects": [{"name": "电商系统"}],
    },
    "soft_skills": {"tags": ["沟通", "团队协作"]},
    "hard_skills": {
        "tags": ["Java", "MySQL", "Redis"],
        "education": {"school": "XX大学", "degree": "本科", "major": "计算机"},
        "certificates": ["英语六级"],
    },
}


def test_build_portrait_text_contains_key_fields():
    text = build_portrait_text(SAMPLE_FIVE_LAYERS)
    assert "后端开发" in text
    assert "Java" in text
    assert "XX大学" in text
    assert "沟通" in text
    assert "XX科技" in text
    assert "电商系统" in text
    assert "英语六级" in text


def test_build_portrait_text_empty_layers():
    text = build_portrait_text({})
    assert text == ""


def test_build_portrait_text_partial_layers():
    text = build_portrait_text({"hard_skills": {"tags": ["Python"]}})
    assert "Python" in text
    assert "目标岗位" not in text


def test_build_portrait_text_normalises_skills():
    """B5（2026-10-03）：学生技能要过归一化 —— 岗位侧用同一套。

    两边不一致的话，学生写的 `Java开发` 与岗位写的 `Java` 在向量空间里是两个词，
    "技能匹配"会被系统性低估。
    """
    text = build_portrait_text({"hard_skills": {"tags": ["Java开发", "MySQL数据库", "springboot"]}})
    assert "技术栈：Java、MySQL、Spring Boot" in text


@pytest.mark.asyncio
async def test_profile_embedder_success():
    mock_vector = [0.1] * 1024
    mock_embeddings = AsyncMock()
    mock_embeddings.aembed_query = AsyncMock(return_value=mock_vector)

    with patch(
        "app.core.llm.embeddings.get_embeddings",
        return_value=mock_embeddings,
    ):
        result = await profile_embedder.ainvoke({"five_layers": SAMPLE_FIVE_LAYERS})

    assert result["embedding"] is not None
    assert len(result["embedding"]) == 1024
    assert "后端开发" in result["content"]


@pytest.mark.asyncio
async def test_profile_embedder_failure_returns_none():
    with patch(
        "app.core.llm.embeddings.get_embeddings",
        side_effect=RuntimeError("API error"),
    ):
        result = await profile_embedder.ainvoke({"five_layers": SAMPLE_FIVE_LAYERS})

    assert result["embedding"] is None
    assert len(result["content"]) > 0


@pytest.mark.asyncio
async def test_profile_embedder_empty_layers():
    result = await profile_embedder.ainvoke({"five_layers": {}})
    assert result["embedding"] is None
    assert result["content"] == ""
