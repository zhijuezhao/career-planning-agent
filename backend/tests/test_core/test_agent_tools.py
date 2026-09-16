from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.agent.tools.knowledge import career_knowledge_search
from app.core.agent.tools.safety import content_safety_check
from app.core.agent.tools.search import web_search
from langchain_core.tools import BaseTool

pytestmark = pytest.mark.skip(reason="profile_tool 已删（Task 0 admin 清理）")

try:
    from app.core.agent.tools.profile_tool import get_user_profile
except ImportError:
    get_user_profile = None

# ── knowledge.py tests ──────────────────────────────────────────────────────


class TestCareerKnowledgeSearch:
    @pytest.mark.asyncio
    async def test_returns_hits(self):
        fake_hits = [
            {
                "id": 1,
                "title": "前端开发技能",
                "content": "HTML/CSS/JS",
                "category": "career",
                "distance": 0.15,
                "metadata": None,
            }
        ]
        with patch("app.core.agent.tools.knowledge.search_knowledge", AsyncMock(return_value=fake_hits)):
            result = await career_knowledge_search.ainvoke({"query": "前端开发", "top_k": 3})

        assert result["hits"] == fake_hits

    @pytest.mark.asyncio
    async def test_clamps_top_k(self):
        with patch("app.core.agent.tools.knowledge.search_knowledge", AsyncMock(return_value=[])):
            result = await career_knowledge_search.ainvoke({"query": "test", "top_k": 100})

        assert len(result["hits"]) == 0

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(career_knowledge_search, BaseTool)
        assert career_knowledge_search.name == "career_knowledge_search"


# ── profile_tool.py tests ───────────────────────────────────────────────────


class TestGetUserProfile:
    @pytest.mark.asyncio
    async def test_returns_profile_when_found(self):
        mock_profile = MagicMock()
        mock_profile.id = 42
        mock_profile.user_id = 1
        mock_profile.direction_tag = "default"
        mock_profile.version = 3
        mock_profile.intention = {"target_position": "前端工程师"}
        mock_profile.traits = {}
        mock_profile.practice = {}
        mock_profile.soft_skills = {}
        mock_profile.hard_skills = {}
        mock_profile.created_at = None
        mock_profile.updated_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session

        with patch("app.infrastructure.database.async_session_factory", return_value=mock_cm):
            result = await get_user_profile.ainvoke({"user_id": 1})

        assert result["profile"] is not None
        assert result["profile"]["id"] == 42
        assert result["profile"]["version"] == 3
        assert result["profile"]["intention"] == {"target_position": "前端工程师"}

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session

        with patch("app.infrastructure.database.async_session_factory", return_value=mock_cm):
            result = await get_user_profile.ainvoke({"user_id": 999})

        assert result["profile"] is None
        assert "未找到" in result["message"]

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(get_user_profile, BaseTool)
        assert get_user_profile.name == "get_user_profile"


# ── safety.py tests ─────────────────────────────────────────────────────────


class TestContentSafetyCheck:
    @pytest.mark.asyncio
    async def test_safe_text(self):
        with (
            patch("app.core.agent.tools.safety.check_content") as mock_check,
            patch("app.core.agent.tools.safety.append_disclaimer", return_value="safe text\n\n---\n*免责声明*"),
        ):
            mock_check.return_value.is_safe = True
            mock_check.return_value.violation_type = None
            mock_check.return_value.reason = None

            result = await content_safety_check.ainvoke({"text": "safe text"})

        assert result["is_safe"] is True
        assert result["violation_type"] is None
        assert "免责声明" in result["sanitized_text"]

    @pytest.mark.asyncio
    async def test_unsafe_text(self):
        with (
            patch("app.core.agent.tools.safety.check_content") as mock_check,
            patch("app.core.agent.tools.safety.append_disclaimer", return_value="bad text\n\n---\n*免责声明*"),
        ):
            mock_check.return_value.is_safe = False
            mock_check.return_value.violation_type = MagicMock(value="discrimination")
            mock_check.return_value.reason = "涉及性别歧视表述"

            result = await content_safety_check.ainvoke({"text": "bad text"})

        assert result["is_safe"] is False
        assert result["violation_type"] == "discrimination"
        assert result["reason"] == "涉及性别歧视表述"

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(content_safety_check, BaseTool)
        assert content_safety_check.name == "content_safety_check"


# ── search.py tests ─────────────────────────────────────────────────────────


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_returns_results_from_knowledge(self):
        fake_hits = [
            {
                "id": 1,
                "title": "Python开发",
                "content": "Python是一种编程语言，广泛用于后端开发和数据分析。",
                "category": "skill",
                "distance": 0.2,
                "metadata": None,
            }
        ]
        with patch("app.core.agent.tools.search.search_knowledge", AsyncMock(return_value=fake_hits)):
            result = await web_search.ainvoke({"query": "Python"})

        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Python开发"
        assert "Python" in result["results"][0]["snippet"]
        assert "note" in result

    @pytest.mark.asyncio
    async def test_returns_empty_results(self):
        with patch("app.core.agent.tools.search.search_knowledge", AsyncMock(return_value=[])):
            result = await web_search.ainvoke({"query": "不存在的内容"})

        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_clamps_max_results(self):
        with patch("app.core.agent.tools.search.search_knowledge", AsyncMock(return_value=[])):
            result = await web_search.ainvoke({"query": "test", "max_results": 50})

        assert len(result["results"]) == 0

    @pytest.mark.asyncio
    async def test_is_tool_instance(self):
        assert isinstance(web_search, BaseTool)
        assert web_search.name == "web_search"
