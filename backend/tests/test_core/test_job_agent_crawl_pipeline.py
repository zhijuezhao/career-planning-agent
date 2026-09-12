from unittest.mock import AsyncMock, patch

import pytest
from app.core.job_agent.graphs.crawl_pipeline import (
    CrawlState,
    build_crawl_pipeline,
    compile_crawl_pipeline,
    node_enrich,
    node_report,
    node_search,
)
from langgraph.graph import StateGraph


def _mock_tool(return_value: dict) -> AsyncMock:
    tool = AsyncMock()
    tool.ainvoke = AsyncMock(return_value=return_value)
    return tool


class TestCrawlState:
    def test_state_has_required_keys(self):
        state: CrawlState = {
            "keywords": "前端开发",
            "search_results": [],
            "status": "pending",
        }
        assert state["keywords"] == "前端开发"
        assert state["status"] == "pending"


class TestBuildGraph:
    def test_build_crawl_pipeline_returns_stategraph(self):
        graph = build_crawl_pipeline()
        assert isinstance(graph, StateGraph)

    def test_compile_crawl_pipeline_returns_runnable(self):
        compiled = compile_crawl_pipeline()
        assert hasattr(compiled, "ainvoke")

    def test_graph_has_all_nodes(self):
        graph = build_crawl_pipeline()
        nodes = graph.nodes
        assert "search" in nodes
        assert "enrich" in nodes
        assert "report" in nodes


class TestNodeSearch:
    @pytest.mark.asyncio
    async def test_searches_web(self):
        state: CrawlState = {"keywords": "前端开发", "max_results": 5}
        fake_results = [{"title": "R1", "url": "https://x.com/1", "snippet": "s", "source": "tavily"}]
        with patch(
            "app.core.job_agent.tools.web_collector.web_collector",
            _mock_tool({"results": fake_results, "total": 1, "source": "tavily"}),
        ):
            result = await node_search(state)
        assert result["status"] == "searched"
        assert len(result["search_results"]) == 1
        assert result["search_source"] == "tavily"


class TestNodeEnrich:
    @pytest.mark.asyncio
    async def test_enriches_results(self):
        state: CrawlState = {
            "search_results": [
                {"title": "R1", "url": "https://example.com/1", "snippet": "s", "source": "tavily"},
            ],
        }
        with (
            patch("app.core.job_agent.tools.url_safety.url_safety_check",
                  _mock_tool({"is_safe": True, "domain": "example.com"})),
            patch("app.core.job_agent.tools.url_fetcher.url_fetcher",
                  _mock_tool({
                      "success": True, "content": "Full content here",
                      "title": "Page Title", "is_ai_enriched": False,
                  })),
        ):
            result = await node_enrich(state)
        assert result["status"] == "enriched"
        assert result["search_results"][0]["full_content"] == "Full content here"

    @pytest.mark.asyncio
    async def test_skips_unsafe_urls(self):
        state: CrawlState = {
            "search_results": [
                {"title": "R1", "url": "https://malware.com/1", "snippet": "s", "source": "tavily"},
            ],
        }
        with patch(
            "app.core.job_agent.tools.url_safety.url_safety_check",
            _mock_tool({"is_safe": False}),
        ):
            result = await node_enrich(state)
        assert result["status"] == "enriched"
        assert "full_content" not in result["search_results"][0]


class TestNodeReport:
    @pytest.mark.asyncio
    async def test_generates_report(self):
        state: CrawlState = {
            "search_results": [{"title": "R1", "url": "https://x.com/1", "snippet": "s"}],
            "industry": "互联网/IT",
        }
        with patch(
            "app.core.job_agent.tools.report_summarizer.report_summarizer",
            _mock_tool({
                "summary": "# 行业报告\n内容",
                "sections": {"行业概览": "内容"},
                "source": "llm",
            }),
        ):
            result = await node_report(state)
        assert result["status"] == "completed"
        assert "行业报告" in result["report_text"]


class TestCompiledCrawlPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_invoke(self):
        compiled = compile_crawl_pipeline()

        with (
            patch("app.core.job_agent.tools.web_collector.web_collector",
                  _mock_tool({"results": [{"title": "R1", "url": "https://x.com/1",
                                           "snippet": "s", "source": "tavily"}],
                              "total": 1, "source": "tavily"})),
            patch("app.core.job_agent.tools.url_safety.url_safety_check",
                  _mock_tool({"is_safe": True})),
            patch("app.core.job_agent.tools.url_fetcher.url_fetcher",
                  _mock_tool({"success": True, "content": "Full content",
                              "title": "Title"})),
            patch("app.core.job_agent.tools.report_summarizer.report_summarizer",
                  _mock_tool({"summary": "# 行业报告\n趋势分析",
                              "sections": {"行业概览": "内容"}, "source": "llm"})),
        ):
            result = await compiled.ainvoke({
                "keywords": "前端开发 行业趋势",
                "industry": "互联网/IT",
                "max_results": 5,
            })

        assert result["status"] == "completed"
        assert result["search_source"] == "tavily"
        assert "行业报告" in result["report_text"]
