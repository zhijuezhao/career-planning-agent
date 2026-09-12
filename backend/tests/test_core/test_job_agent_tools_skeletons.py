from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.core.job_agent.tools.db_writer import db_writer
from app.core.job_agent.tools.embedder import job_embedder
from app.core.job_agent.tools.job_extractor import job_extractor
from app.core.job_agent.tools.portrait_builder import portrait_builder
from app.core.job_agent.tools.quality_judge import quality_judge
from app.core.job_agent.tools.report_summarizer import report_summarizer
from app.core.job_agent.tools.url_fetcher import url_fetcher
from app.core.job_agent.tools.url_safety import url_safety_check
from app.core.job_agent.tools.web_collector import web_collector
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool


def _mock_gateway(json_response: str) -> MagicMock:
    """Create a mock LLM gateway that returns a given JSON string."""
    mock_gateway = MagicMock()
    mock_gateway.ainvoke = AsyncMock(return_value=AIMessage(content=json_response))
    return mock_gateway


class TestQualityJudge:
    @pytest.mark.asyncio
    async def test_returns_llm_grade(self):
        fake = (
            '{"grade": "A", "score": 92, '
            '"breakdown": {"信息完整性": 95, "描述质量": 90, '
            '"要求明确度": 90, "薪资信息": 93}, '
            '"strengths": ["信息完整"], "weaknesses": [], '
            '"summary": "优秀"}'
        )
        with patch(
            "app.core.job_agent.tools.quality_judge.get_llm_gateway",
            return_value=_mock_gateway(fake),
        ):
            result = await quality_judge.ainvoke({"job_data": '{"title": "test"}'})
        assert result["grade"] == "A"
        assert result["score"] == 92

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        mock_gateway = MagicMock()
        mock_gateway.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        with patch("app.core.job_agent.tools.quality_judge.get_llm_gateway", return_value=mock_gateway):
            result = await quality_judge.ainvoke({"job_data": '{"title": "test"}'})
        assert result["grade"] == "D"
        assert result["score"] == 0

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(quality_judge, BaseTool)
        assert quality_judge.name == "quality_judge"


class TestUrlSafetyCheck:
    @pytest.mark.asyncio
    async def test_whitelisted_domain(self):
        """Known whitelisted domain should be safe."""
        result = await url_safety_check.ainvoke({
            "url": "https://zhaopin.com/jobs/123",
            "check_reachability": False,
        })
        assert result["is_safe"] is True
        assert result["domain"] == "zhaopin.com"

    @pytest.mark.asyncio
    async def test_blacklisted_domain(self):
        result = await url_safety_check.ainvoke({
            "url": "https://malware.com/evil",
            "check_reachability": False,
        })
        assert result["is_safe"] is False
        assert "blacklisted" in result["reason"]

    @pytest.mark.asyncio
    async def test_unknown_domain_allowed(self):
        result = await url_safety_check.ainvoke({
            "url": "https://some-unknown-site.com/jobs",
            "check_reachability": False,
        })
        assert result["is_safe"] is True
        assert "unchecked" in result["reason"]

    @pytest.mark.asyncio
    async def test_parses_domain_without_scheme(self):
        result = await url_safety_check.ainvoke({
            "url": "zhaopin.com/jobs",
            "check_reachability": False,
        })
        assert result["domain"] == "zhaopin.com"

    @pytest.mark.asyncio
    async def test_custom_whitelist_overrides_default(self):
        result = await url_safety_check.ainvoke({
            "url": "https://my-custom-site.com",
            "whitelist": ["my-custom-site.com"],
            "check_reachability": False,
        })
        assert result["is_safe"] is True
        assert "whitelisted" in result["reason"]

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(url_safety_check, BaseTool)
        assert url_safety_check.name == "url_safety_check"


class TestUrlFetcher:
    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        fake_html = (
            "<html><head><title>Test Page</title></head>"
            "<body><article>Job content here</article></body></html>"
        )
        mock_response = MagicMock()
        mock_response.text = fake_html
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.core.job_agent.tools.url_fetcher.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await url_fetcher.ainvoke({"url": "https://example.com/job"})

        assert result["success"] is True
        assert result["title"] == "Test Page"
        assert "Job content" in result["content"]
        assert result["is_ai_enriched"] is False

    @pytest.mark.asyncio
    async def test_http_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=mock_response)
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.core.job_agent.tools.url_fetcher.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await url_fetcher.ainvoke({"url": "https://example.com/404"})

        assert result["success"] is False
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("app.core.job_agent.tools.url_fetcher.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await url_fetcher.ainvoke({"url": "https://example.com"})

        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(url_fetcher, BaseTool)
        assert url_fetcher.name == "url_fetcher"


class TestJobExtractor:
    @pytest.mark.asyncio
    async def test_returns_llm_extracted_fields(self):
        fake = (
            '{"title": "前端工程师", "company": "ABC公司", '
            '"city": "北京", "salary": "15000-25000", '
            '"description": "负责前端开发", "requirements": "本科", '
            '"education_requirement": "本科", '
            '"experience_requirement": "1-3年", '
            '"hard_skills": ["Vue", "React"], '
            '"soft_skills": ["沟通"]}'
        )
        with patch(
            "app.core.job_agent.tools.job_extractor.get_llm_gateway",
            return_value=_mock_gateway(fake),
        ):
            result = await job_extractor.ainvoke({"job_text": "招聘前端工程师"})
        assert result["title"] == "前端工程师"
        assert result["company"] == "ABC公司"
        assert result["city"] == "北京"
        assert result["hard_skills"] == ["Vue", "React"]

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        mock_gateway = MagicMock()
        mock_gateway.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        with patch("app.core.job_agent.tools.job_extractor.get_llm_gateway", return_value=mock_gateway):
            result = await job_extractor.ainvoke({"job_text": "招聘"})
        assert result["title"] is None
        assert result["hard_skills"] == []

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(job_extractor, BaseTool)
        assert job_extractor.name == "job_extractor"


class TestPortraitBuilder:
    @pytest.mark.asyncio
    async def test_returns_llm_portrait(self):
        fake = (
            '{"five_dimensions": {"technical": {"score": 4, "key_skills": ["Vue"]}, '
            '"experience": {"score": 3, "key_skills": []}, '
            '"soft_skills": {"score": 3, "key_skills": []}, '
            '"education": {"score": 3, "key_skills": []}, '
            '"responsibility": {"score": 3, "key_skills": []}}, '
            '"career_paths": ["初级-中级-高级"], '
            '"transition_roles": ["产品经理"], '
            '"outlook": {"outlook": "朝阳", "trend": "需求稳定", '
            '"risk_factors": []}, '
            '"summary": "前端岗位总结"}'
        )
        with patch(
            "app.core.job_agent.tools.portrait_builder.get_llm_gateway",
            return_value=_mock_gateway(fake),
        ):
            result = await portrait_builder.ainvoke({"job_data": '{"title": "test"}'})
        assert result["five_dimensions"]["technical"]["score"] == 4
        assert result["career_paths"] == ["初级-中级-高级"]
        assert result["outlook"]["outlook"] == "朝阳"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        mock_gateway = MagicMock()
        mock_gateway.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        with patch("app.core.job_agent.tools.portrait_builder.get_llm_gateway", return_value=mock_gateway):
            result = await portrait_builder.ainvoke({"job_data": '{"title": "test"}'})
        assert result["five_dimensions"]["technical"]["score"] == 3
        assert result["summary"] == ""

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(portrait_builder, BaseTool)
        assert portrait_builder.name == "portrait_builder"


class TestJobEmbedder:
    @pytest.mark.asyncio
    async def test_returns_embedding(self):
        fake_vector = [0.1, 0.2, 0.3]
        with patch("app.core.job_agent.tools.embedder.get_embeddings") as mock_get:
            mock_embeddings = AsyncMock()
            mock_embeddings.aembed_query = AsyncMock(return_value=fake_vector)
            mock_get.return_value = mock_embeddings

            result = await job_embedder.ainvoke({"text": "前端开发工程师"})

        assert result["embedding"] == fake_vector
        assert result["dimensions"] == 3

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(self):
        result = await job_embedder.ainvoke({"text": ""})
        assert result["embedding"] is None
        assert result["dimensions"] == 0

    @pytest.mark.asyncio
    async def test_embedding_failure_graceful(self):
        with patch("app.core.job_agent.tools.embedder.get_embeddings", side_effect=RuntimeError("API error")):
            result = await job_embedder.ainvoke({"text": "前端开发工程师"})

        assert result["embedding"] is None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(job_embedder, BaseTool)
        assert job_embedder.name == "job_embedder"


class TestDbWriter:
    @pytest.mark.asyncio
    async def test_writes_raw_data(self):
        mock_session = AsyncMock()

        async def _refresh_side_effect(row):
            row.id = 42

        mock_session.refresh = AsyncMock(side_effect=_refresh_side_effect)
        mock_session.__aenter__.return_value = mock_session

        with patch(
            "app.core.job_agent.tools.db_writer.async_session_factory",
            return_value=mock_session,
        ):
            result = await db_writer.ainvoke({
                "table": "job_raw_data",
                "data": {"title": "前端工程师", "company": "ABC"},
            })

        assert result["success"] is True
        assert result["table"] == "job_raw_data"
        assert result["record_id"] == 42

    @pytest.mark.asyncio
    async def test_rejects_unknown_table(self):
        result = await db_writer.ainvoke({
            "table": "nonexistent",
            "data": {"title": "test"},
        })
        assert result["success"] is False
        assert "Unknown table" in result["error"]

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(db_writer, BaseTool)
        assert db_writer.name == "db_writer"


class TestWebCollector:
    @pytest.mark.asyncio
    async def test_falls_back_to_duckduckgo(self):
        ddg_result = [{"title": "T", "url": "https://x.com",
                       "snippet": "s", "source": "duckduckgo"}]
        with patch(
            "app.core.job_agent.tools.web_collector._search_tavily",
            AsyncMock(return_value=[]),
        ):
            with patch(
                "app.core.job_agent.tools.web_collector._search_duckduckgo",
                AsyncMock(return_value=ddg_result),
            ):
                result = await web_collector.ainvoke({"keywords": "前端开发"})

        assert result["total"] == 1
        assert result["source"] == "duckduckgo"

    @pytest.mark.asyncio
    async def test_uses_tavily_when_available(self):
        fake_results = [{"title": "T", "url": "https://zhaopin.com/1", "snippet": "s", "source": "tavily"}]
        with patch(
            "app.core.job_agent.tools.web_collector._search_tavily",
            AsyncMock(return_value=fake_results),
        ):
            result = await web_collector.ainvoke({"keywords": "前端开发"})

        assert result["total"] == 1
        assert result["source"] == "tavily"

    @pytest.mark.asyncio
    async def test_clamps_max_results(self):
        fake_list = [
            {"title": f"R{i}", "url": f"https://x.com/{i}",
             "snippet": "s", "source": "tavily"}
            for i in range(5)
        ]
        with patch(
            "app.core.job_agent.tools.web_collector._search_tavily",
            AsyncMock(return_value=fake_list),
        ):
            result = await web_collector.ainvoke({"keywords": "test", "max_results": 100})

        assert result["total"] == 5  # Only 5 results available

    @pytest.mark.asyncio
    async def test_both_fail_return_empty(self):
        with patch(
            "app.core.job_agent.tools.web_collector._search_tavily",
            AsyncMock(return_value=[]),
        ):
            with patch(
                "app.core.job_agent.tools.web_collector._search_duckduckgo",
                AsyncMock(return_value=[]),
            ):
                result = await web_collector.ainvoke({"keywords": "测试"})

        assert result["total"] == 0
        assert result["source"] == "none"

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(web_collector, BaseTool)
        assert web_collector.name == "web_collector"


class TestReportSummarizer:
    @pytest.mark.asyncio
    async def test_returns_llm_report(self):
        fake_report = "## 行业概览\n内容\n\n### 2. 热门岗位趋势\n趋势内容"
        mock_gateway = MagicMock()
        mock_gateway.ainvoke = AsyncMock(return_value=AIMessage(content=fake_report))
        with patch(
            "app.core.job_agent.tools.report_summarizer.get_llm_gateway",
            return_value=mock_gateway,
        ):
            with patch(
                "app.core.job_agent.tools.report_summarizer.append_disclaimer",
                return_value=fake_report,
            ):
                result = await report_summarizer.ainvoke({"data": "collected data"})

        assert "行业概览" in result["summary"]
        assert result["is_ai_enriched"] is True
        assert result["source"] == "llm"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        mock_gateway = MagicMock()
        mock_gateway.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        with patch(
            "app.core.job_agent.tools.report_summarizer.get_llm_gateway",
            return_value=mock_gateway,
        ):
            result = await report_summarizer.ainvoke({"data": "test"})

        assert result["is_ai_enriched"] is False
        assert result["summary"] == ""

    @pytest.mark.asyncio
    async def test_parse_sections(self):
        from app.core.job_agent.tools.report_summarizer import _parse_sections

        markdown = """### 行业概览
IT行业内容

### 热门岗位趋势
前端需求大

其他内容
"""
        sections = _parse_sections(markdown)
        assert "行业概览" in sections
        assert "热门岗位趋势" in sections
        assert "IT行业内容" in sections["行业概览"]

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(report_summarizer, BaseTool)
        assert report_summarizer.name == "report_summarizer"
