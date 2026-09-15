from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.skip(reason="旧表已删除，新端点待 Task 5/6")


class TestMatchJobsTool:
    @pytest.mark.asyncio
    async def test_match_jobs_no_embedding(self):
        from app.core.agent.tools.match_jobs_tool import match_jobs

        with patch("app.infrastructure.database.async_session_factory") as mock_factory:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await match_jobs.ainvoke({"user_id": 1, "profile_id": 1})

        assert "error" in result
        assert "embedding not found" in result["error"]

    @pytest.mark.asyncio
    async def test_match_jobs_success(self):
        from app.core.agent.tools.match_jobs_tool import match_jobs

        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 1024

        with patch("app.infrastructure.database.async_session_factory") as mock_factory, \
             patch("app.core.matching.match_user_to_jobs") as mock_match:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_embedding
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_match.return_value = [
                {"job_profile_id": 1, "match_score": 0.85, "analysis": {}},
            ]
            result = await match_jobs.ainvoke({"user_id": 1, "profile_id": 1, "top_k": 5})

        assert result["success"] is True
        assert result["total"] == 1


class TestCreateCareerPathTool:
    @pytest.mark.asyncio
    async def test_create_career_path_success(self):
        from app.core.agent.tools.career_path_tool import create_career_path

        mock_path = MagicMock()
        mock_path.id = 1
        mock_path.target_position = "前端工程师"
        mock_path.path_type = "技术专家"
        mock_path.milestones = []
        mock_path.learning_resources = {}

        with patch("app.infrastructure.database.async_session_factory") as mock_factory, \
             patch("app.core.matching.path_planner.generate_career_path") as mock_gen:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_gen.return_value = mock_path

            result = await create_career_path.ainvoke({
                "user_id": 1, "profile_id": 1, "target_job_id": 1
            })

        assert result["success"] is True
        assert result["target_position"] == "前端工程师"

    @pytest.mark.asyncio
    async def test_create_career_path_failure(self):
        from app.core.agent.tools.career_path_tool import create_career_path

        with patch("app.infrastructure.database.async_session_factory") as mock_factory, \
             patch("app.core.matching.path_planner.generate_career_path") as mock_gen:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_gen.return_value = None

            result = await create_career_path.ainvoke({
                "user_id": 1, "profile_id": 1, "target_job_id": 1
            })

        assert "error" in result


class TestCreateGrowthPlanTool:
    @pytest.mark.asyncio
    async def test_create_growth_plan_success(self):
        from app.core.agent.tools.career_path_tool import create_growth_plan

        mock_plan = MagicMock()
        mock_plan.id = 1
        mock_plan.cycle_weeks = 12
        mock_plan.intensity = "中等强度"
        mock_plan.tasks = []

        with patch("app.infrastructure.database.async_session_factory") as mock_factory, \
             patch("app.core.matching.path_planner.generate_growth_plan") as mock_gen:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_gen.return_value = mock_plan

            result = await create_growth_plan.ainvoke({
                "user_id": 1, "growth_path_id": 1
            })

        assert result["success"] is True
        assert result["cycle_weeks"] == 12


class TestGenerateCareerReportTool:
    @pytest.mark.asyncio
    async def test_generate_report_success(self):
        from app.core.agent.tools.report_tool import generate_career_report

        mock_report = MagicMock()
        mock_report.id = 1
        mock_report.version = 1
        mock_report.target_job = "前端工程师"
        mock_report.word_file_path = "/tmp/report.docx"
        mock_report.report_content = {"report_text": "测试报告内容"}

        with patch("app.infrastructure.database.async_session_factory") as mock_factory, \
             patch("app.domain.services.report_service.create_report") as mock_gen:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_gen.return_value = mock_report

            result = await generate_career_report.ainvoke({
                "user_id": 1, "profile_id": 1, "target_job": "前端工程师"
            })

        assert result["success"] is True
        assert result["version"] == 1

    @pytest.mark.asyncio
    async def test_generate_report_failure(self):
        from app.core.agent.tools.report_tool import generate_career_report

        with patch("app.infrastructure.database.async_session_factory") as mock_factory, \
             patch("app.domain.services.report_service.create_report") as mock_gen:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_gen.side_effect = ValueError("用户能力画像不存在")

            result = await generate_career_report.ainvoke({
                "user_id": 1, "profile_id": 1
            })

        assert "error" in result
