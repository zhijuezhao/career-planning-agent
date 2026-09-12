from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.job_agent.graphs.import_pipeline import (
    JobImportState,
    _row_to_text,
    build_import_pipeline,
    compile_import_pipeline,
    node_clean_data,
    node_dedup,
    node_load_data,
    node_quality_judge,
)
from langgraph.graph import StateGraph


def _mock_tool(return_value: dict) -> MagicMock:
    """Create a mock tool with .ainvoke() returning the given value."""
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value=return_value)
    return tool


def _mock_judge_sequence(return_values: list[dict]) -> MagicMock:
    """Create a mock tool with .ainvoke() returning different values each call."""
    tool = MagicMock()
    tool.ainvoke = AsyncMock(side_effect=return_values)
    return tool


class TestRowToText:
    def test_converts_row_to_text(self):
        row = {"title": "前端", "company": "A", "city": "北京"}
        text = _row_to_text(row)
        assert "title: 前端" in text
        assert "company: A" in text
        assert "city: 北京" in text

    def test_skips_empty_fields(self):
        row = {"title": "前端", "description": None, "requirements": ""}
        text = _row_to_text(row)
        assert "title: 前端" in text
        assert "description" not in text
        assert "requirements" not in text


class TestJobImportState:
    def test_state_has_required_keys(self):
        state: JobImportState = {
            "file_path": "test.xlsx",
            "raw_rows": [],
            "cleaned_rows": [],
            "deduped_rows": [],
            "passed_rows": [],
            "rejected_rows": [],
            "extracted_rows": [],
            "portrait_rows": [],
            "status": "pending",
        }
        assert state["file_path"] == "test.xlsx"
        assert state["status"] == "pending"


class TestBuildGraph:
    def test_build_import_pipeline_returns_stategraph(self):
        graph = build_import_pipeline()
        assert isinstance(graph, StateGraph)

    def test_compile_import_pipeline_returns_runnable(self):
        compiled = compile_import_pipeline()
        assert hasattr(compiled, "ainvoke")

    def test_graph_has_all_nodes(self):
        graph = build_import_pipeline()
        nodes = graph.nodes
        assert "load_data" in nodes
        assert "clean_data" in nodes
        assert "dedup" in nodes
        assert "quality_judge" in nodes
        assert "extract" in nodes
        assert "portrait" in nodes


class TestNodeLoadData:
    @pytest.mark.asyncio
    async def test_loads_data_from_excel(self):
        state: JobImportState = {"file_path": "test.xlsx"}
        fake_rows = [{"title": "前端工程师"}, {"title": "后端工程师"}]
        with patch(
            "app.core.job_agent.tools.data_loader.load_excel_data",
            _mock_tool({"rows": fake_rows, "total": 2}),
        ):
            result = await node_load_data(state)
        assert result["total_input"] == 2
        assert len(result["raw_rows"]) == 2
        assert result["status"] == "loaded"

    @pytest.mark.asyncio
    async def test_handles_empty_data(self):
        state: JobImportState = {"file_path": "empty.xlsx"}
        with patch(
            "app.core.job_agent.tools.data_loader.load_excel_data",
            _mock_tool({"rows": [], "total": 0}),
        ):
            result = await node_load_data(state)
        assert result["total_input"] == 0
        assert result["raw_rows"] == []


class TestNodeCleanData:
    @pytest.mark.asyncio
    async def test_cleans_rows(self):
        state: JobImportState = {"raw_rows": [{"title": "test<br>title", "city": None}]}
        with patch(
            "app.core.job_agent.tools.pre_cleaner.clean_job_data",
            _mock_tool({
                "cleaned_rows": [{"title": "test\ntitle", "city": "未知"}],
                "total": 1,
            }),
        ):
            result = await node_clean_data(state)
        assert result["status"] == "cleaned"
        assert len(result["cleaned_rows"]) == 1


class TestNodeDedup:
    @pytest.mark.asyncio
    async def test_dedup_rows(self):
        state: JobImportState = {
            "cleaned_rows": [
                {"title": "前端工程师", "company": "A", "city": "北京"},
                {"title": "前端工程师", "company": "A", "city": "北京"},
            ],
        }
        with patch(
            "app.core.job_agent.tools.dedup.deduplicate_jobs",
            _mock_tool({
                "deduped_rows": [{"title": "前端工程师", "company": "A", "city": "北京"}],
                "exact_dedup_count": 0,
                "fuzzy_dedup_count": 1,
            }),
        ):
            result = await node_dedup(state)
        assert result["status"] == "deduped"
        assert len(result["deduped_rows"]) == 1


class TestNodeQualityJudge:
    @pytest.mark.asyncio
    async def test_separates_passed_and_rejected(self):
        state: JobImportState = {
            "deduped_rows": [
                {"title": "A级岗位", "description": "详细描述"},
                {"title": "D级岗位", "description": ""},
            ],
        }
        mock_tool = _mock_judge_sequence([
            {"grade": "A", "score": 90, "breakdown": {},
             "strengths": [], "weaknesses": [], "summary": ""},
            {"grade": "D", "score": 30, "breakdown": {},
             "strengths": [], "weaknesses": [], "summary": ""},
        ])
        with patch("app.core.job_agent.tools.quality_judge.quality_judge", mock_tool):
            result = await node_quality_judge(state)
        assert result["total_passed"] == 1
        assert result["total_rejected"] == 1
        assert result["passed_rows"][0]["title"] == "A级岗位"
        assert result["rejected_rows"][0]["title"] == "D级岗位"
        assert result["status"] == "judged"


class TestCompiledPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_invoke(self):
        compiled = compile_import_pipeline()

        row = {"title": "前端工程师", "city": "北京", "company": "A"}
        judge_result = {
            "grade": "A", "score": 90, "breakdown": {},
            "strengths": [], "weaknesses": [], "summary": "",
        }
        extract_result = {
            "title": "前端工程师", "company": "A", "city": "北京",
            "salary": "15000-25000", "description": "", "requirements": "",
            "education_requirement": None, "experience_requirement": None,
            "hard_skills": [], "soft_skills": [],
        }
        portrait_result = {
            "five_dimensions": {}, "career_paths": [],
            "transition_roles": [], "outlook": {}, "summary": "",
        }

        with (
            patch("app.core.job_agent.tools.data_loader.load_excel_data",
                  _mock_tool({"rows": [row], "total": 1})),
            patch("app.core.job_agent.tools.pre_cleaner.clean_job_data",
                  _mock_tool({"cleaned_rows": [row], "total": 1})),
            patch("app.core.job_agent.tools.dedup.deduplicate_jobs",
                  _mock_tool({"deduped_rows": [row],
                              "exact_dedup_count": 0,
                              "fuzzy_dedup_count": 0})),
            patch("app.core.job_agent.tools.quality_judge.quality_judge",
                  _mock_tool(judge_result)),
            patch("app.core.job_agent.tools.job_extractor.job_extractor",
                  _mock_tool(extract_result)),
            patch("app.core.job_agent.tools.portrait_builder.portrait_builder",
                  _mock_tool(portrait_result)),
        ):
            result = await compiled.ainvoke({
                "file_path": "test.xlsx",
                "sheet_name": 0,
            })

        assert result["total_input"] == 1
        assert result["total_passed"] == 1
        assert result["total_rejected"] == 0
        assert result["total_exported"] == 1
        assert result["status"] == "completed"
