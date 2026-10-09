from unittest.mock import AsyncMock, patch

import pytest
from app.core.resume_agent.parse_graph import build_parse_graph
from app.core.resume_agent.schemas import ParsedResume


def test_build_parse_graph_has_three_nodes():
    g = build_parse_graph()
    assert {"extract_pdf", "parse_resume", "map_layers"} <= set(g.nodes)
    assert "generate_report" not in g.nodes
    assert "persist" not in g.nodes
    assert "embed_profile" not in g.nodes
    assert "write_scores" not in g.nodes  # 六维分数落库挪到快照生成（Task 4）


@pytest.mark.asyncio
async def test_parse_dry_run_returns_layers_and_scores():
    from app.core.resume_agent.parse_graph import parse_resume_only

    empty_dim = {"score": 4.2, "sub_dimensions": {}}
    fake_scores = {
        dim: empty_dim
        for dim in (
            "专业技术能力",
            "实践经验背景",
            "通用软素质",
            "职业匹配度",
            "成长潜力",
            "基础资质条件",
        )
    }
    fake_parsed = {
        "basic_info": {"name": "张三"},
        "intention": {"target_position": ["后端开发"]},
        "traits": {},
        "practice": {},
        "soft_skills": {},
        "hard_skills": {},
        "dimension_scoring": {
            "profile_type": "candidate",
            "total_dim_score": 4.2,
            "dimensions": fake_scores,
        },
    }
    ParsedResume.model_validate(fake_parsed)  # 契约：node_map_layers 会对该 dict 做 model_validate
    with patch("app.core.resume_agent.tools.resume_parser._parse_resume",
               new_callable=AsyncMock, return_value=fake_parsed), \
         patch("app.core.resume_agent.tools.pdf_text_extractor._extract_pdf_text",
               return_value={"raw_text": "x", "page_count": 1, "truncated": False}):
        out = await parse_resume_only("resume.pdf", resume_id=1)
    assert "five_layers" in out and "dimension_scoring" in out
    assert out["dimension_scoring"] == fake_parsed["dimension_scoring"]
