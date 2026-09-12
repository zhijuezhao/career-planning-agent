from unittest.mock import AsyncMock, patch

import pytest
from app.core.resume_agent.graph import (
    build_resume_graph,
    compile_resume_graph,
    node_extract_pdf,
    node_map_layers,
    node_parse_resume,
)


def test_build_graph_has_all_nodes():
    graph = build_resume_graph()
    assert "extract_pdf" in graph.nodes
    assert "parse_resume" in graph.nodes
    assert "map_layers" in graph.nodes
    assert "write_scores" in graph.nodes
    assert "embed_profile" in graph.nodes
    assert "generate_report" in graph.nodes
    assert "persist" in graph.nodes


def test_compile_graph_returns_runnable():
    compiled = compile_resume_graph()
    assert hasattr(compiled, "ainvoke")


@pytest.mark.asyncio
async def test_node_extract_pdf():
    mock_result = {"raw_text": "简历内容", "page_count": 2, "truncated": False}

    with patch(
        "app.core.resume_agent.tools.pdf_text_extractor._extract_pdf_text",
        return_value=mock_result,
    ):
        state = {"resume_id": 1, "file_path": "/tmp/test.pdf"}
        result = await node_extract_pdf(state)

    assert result["raw_text"] == "简历内容"
    assert result["page_count"] == 2
    assert result["status"] == "parsing"


@pytest.mark.asyncio
async def test_node_parse_resume():
    mock_parsed = {
        "basic_info": {"name": "张三"},
        "intention": {"target_position": ["后端开发"]},
        "traits": {"personality_tags": []},
        "practice": {"campus_experiences": []},
        "soft_skills": {"tags": [], "scored": {}, "evidence": {}},
        "hard_skills": {"tags": [], "scored": {}, "education": {}, "certificates": [], "languages": []},
        "dimension_scoring": None,
    }
    with patch(
        "app.core.resume_agent.tools.resume_parser._parse_resume",
        new_callable=AsyncMock,
        return_value=mock_parsed,
    ):
        state = {"resume_id": 1, "raw_text": "简历文本"}
        result = await node_parse_resume(state)

    assert result["parsed_resume"]["basic_info"]["name"] == "张三"
    assert result["status"] == "parsed"


@pytest.mark.asyncio
async def test_node_map_layers():
    parsed_resume = {
        "basic_info": {"name": "张三"},
        "intention": {"target_position": ["后端开发"], "target_city": ["上海"]},
        "traits": {"personality_tags": ["责任心强"], "strengths": [], "values": [], "evidence": []},
        "practice": {"campus_experiences": [], "work_experiences": [], "projects": [], "competitions": []},
        "soft_skills": {"tags": ["沟通"], "scored": {"沟通": 75}, "evidence": {}},
        "hard_skills": {
            "tags": ["Java"],
            "scored": {"Java": 80},
            "education": {"school": "XX大学", "degree": "本科"},
            "certificates": [],
            "languages": [],
        },
        "dimension_scoring": None,
    }
    state = {"resume_id": 1, "parsed_resume": parsed_resume}
    result = await node_map_layers(state)

    assert "five_layers" in result
    assert "intention" in result["five_layers"]
    assert "hard_skills" in result["five_layers"]
