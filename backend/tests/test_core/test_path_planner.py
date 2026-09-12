import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.matching.path_planner import (
    _safe_json_loads,
    generate_career_path,
    generate_growth_plan,
    get_career_paths,
    get_dimension_scores_map,
    get_growth_plans,
    get_target_job,
)
from app.domain.models.job import JobProfile
from app.domain.models.report import GrowthPath, GrowthPlan


class TestSafeJsonLoads:
    def test_parses_valid_json(self):
        result = _safe_json_loads('{"key": "value"}')
        assert result == {"key": "value"}

    def test_strips_code_fences(self):
        text = '```json\n{"key": "value"}\n```'
        result = _safe_json_loads(text)
        assert result == {"key": "value"}

    def test_returns_empty_on_invalid(self):
        result = _safe_json_loads("not json")
        assert result == {}


class TestGetDimensionScoresMap:
    @pytest.mark.asyncio
    async def test_get_scores(self):
        mock_session = AsyncMock()

        mock_score = MagicMock()
        mock_score.top_dimension = "专业技术能力"
        mock_score.sub_dimension = "专业技术能力"
        mock_score.score = 4.5

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_score]
        mock_session.execute = AsyncMock(return_value=mock_result)

        scores = await get_dimension_scores_map("candidate", 1, session=mock_session)

        assert "专业技术能力" in scores
        assert scores["专业技术能力"] == 4.5


class TestGetTargetJob:
    @pytest.mark.asyncio
    async def test_get_job_success(self):
        mock_session = AsyncMock()

        mock_job = JobProfile(
            id=1,
            title="前端工程师",
            industry="互联网",
            level="中级",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        mock_session.execute = AsyncMock(return_value=mock_result)

        job = await get_target_job(1, session=mock_session)

        assert job is not None
        assert job.title == "前端工程师"

    @pytest.mark.asyncio
    async def test_get_job_not_found(self):
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        job = await get_target_job(999, session=mock_session)

        assert job is None


class TestGenerateCareerPath:
    @pytest.mark.asyncio
    async def test_generate_path_success(self):
        mock_session = AsyncMock()

        # Mock ability profile
        mock_profile = MagicMock()
        mock_profile.id = 1
        mock_profile.direction_tag = "前端开发"
        mock_profile.intention = {"target": "前端工程师"}
        mock_profile.traits = {}
        mock_profile.practice = {}
        mock_profile.soft_skills = {}
        mock_profile.hard_skills = {"tags": ["Vue", "React"]}

        mock_profile_result = MagicMock()
        mock_profile_result.scalar_one_or_none.return_value = mock_profile

        # Mock dimension score
        mock_score = MagicMock()
        mock_score.top_dimension = "专业技术能力"
        mock_score.sub_dimension = "专业技术能力"
        mock_score.score = 4.0

        mock_score_result = MagicMock()
        mock_score_result.scalars.return_value.all.return_value = [mock_score]

        # Mock target job
        mock_job = JobProfile(
            id=1,
            title="高级前端工程师",
            industry="互联网",
            level="高级",
        )
        mock_job_result = MagicMock()
        mock_job_result.scalar_one_or_none.return_value = mock_job

        mock_session.execute = AsyncMock(side_effect=[
            mock_profile_result,
            mock_score_result,
            mock_job_result,
        ])

        # Mock LLM response
        path_data = {
            "target_position": "高级前端工程师",
            "path_type": "技术专家",
            "current_abilities": {"专业技术能力": 4.0},
            "target_abilities": {"专业技术能力": 5.0},
            "milestones": [{"stage": "短期", "duration_months": 6, "goals": []}],
            "learning_resources": {"courses": ["Vue3深度实战"]},
        }

        with patch("app.core.matching.path_planner.get_llm_gateway") as mock_gateway:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=json.dumps(path_data)))
            mock_gateway.return_value = mock_llm

            result = await generate_career_path(
                user_id=1,
                profile_id=1,
                target_job_id=1,
                current_stage="在校学生",
                session=mock_session,
            )

        assert result is not None
        assert result.target_position == "高级前端工程师"
        assert result.path_type == "技术专家"
        assert mock_session.add.called
        assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_generate_path_profile_not_found(self):
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await generate_career_path(
            user_id=1,
            profile_id=999,
            target_job_id=1,
            session=mock_session,
        )

        assert result is None


class TestGenerateGrowthPlan:
    @pytest.mark.asyncio
    async def test_generate_plan_success(self):
        mock_session = AsyncMock()

        # Mock growth path
        mock_path = GrowthPath(
            id=1,
            user_id=1,
            target_position="前端工程师",
            path_type="技术专家",
            current_abilities={"技术": 3.0},
            target_abilities={"技术": 5.0},
            generated_plan={"milestones": []},
        )
        mock_path_result = MagicMock()
        mock_path_result.scalar_one_or_none.return_value = mock_path
        mock_session.execute = AsyncMock(return_value=mock_path_result)

        # Mock LLM response
        plan_data = {
            "cycle_weeks": 12,
            "intensity": "中等强度",
            "tasks": [{"week": "第1-2周", "title": "学习Vue3"}],
            "progress_tracking": {"checkpoints": []},
            "weekly_review_template": {},
        }

        with patch("app.core.matching.path_planner.get_llm_gateway") as mock_gateway:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=json.dumps(plan_data)))
            mock_gateway.return_value = mock_llm

            result = await generate_growth_plan(
                user_id=1,
                growth_path_id=1,
                weekly_hours=10,
                cycle_weeks=12,
                session=mock_session,
            )

        assert result is not None
        assert result.cycle_weeks == 12
        assert result.intensity == "中等强度"
        assert mock_session.add.called

    @pytest.mark.asyncio
    async def test_generate_plan_path_not_found(self):
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await generate_growth_plan(
            user_id=1,
            growth_path_id=999,
            session=mock_session,
        )

        assert result is None


class TestGetCareerPaths:
    @pytest.mark.asyncio
    async def test_get_paths(self):
        mock_session = AsyncMock()

        mock_path = GrowthPath(
            id=1,
            user_id=1,
            target_position="前端工程师",
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_path]
        mock_session.execute = AsyncMock(return_value=mock_result)

        paths = await get_career_paths(1, session=mock_session)

        assert len(paths) == 1
        assert paths[0].target_position == "前端工程师"


class TestGetGrowthPlans:
    @pytest.mark.asyncio
    async def test_get_plans(self):
        mock_session = AsyncMock()

        mock_plan = GrowthPlan(
            id=1,
            user_id=1,
            growth_path_id=1,
            cycle_weeks=12,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_plan]
        mock_session.execute = AsyncMock(return_value=mock_result)

        plans = await get_growth_plans(1, session=mock_session)

        assert len(plans) == 1
        assert plans[0].cycle_weeks == 12
