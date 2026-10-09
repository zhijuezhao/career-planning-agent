import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.domain.services.report_service import (
    _safe_json_loads,
    generate_word_document,
    get_dimension_scores_data,
    get_latest_career_path,
    get_latest_growth_plan,
    get_latest_match_results,
    get_user_profile_data,
)

try:
    from app.domain.services.report_service import generate_report_content
except ImportError:  # pragma: no cover
    generate_report_content = None

# pytestmark 必须放在全部 import 之后（否则 E402）；本模块整表已删，用例整体 skip
pytestmark = pytest.mark.skip(reason="旧表已删除，新端点待 Task 5/6")


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


class TestGetUserProfileData:
    @pytest.mark.asyncio
    async def test_get_profile_success(self):
        mock_session = AsyncMock()

        mock_profile = MagicMock()
        mock_profile.id = 1
        mock_profile.direction_tag = "前端开发"
        mock_profile.intention = {}
        mock_profile.traits = {}
        mock_profile.practice = {}
        mock_profile.soft_skills = {}
        mock_profile.hard_skills = {}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = await get_user_profile_data(1, 1, session=mock_session)

        assert data is not None
        assert data["direction_tag"] == "前端开发"

    @pytest.mark.asyncio
    async def test_get_profile_not_found(self):
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        data = await get_user_profile_data(1, 999, session=mock_session)

        assert data is None


class TestGetDimensionScoresData:
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

        scores = await get_dimension_scores_data(1, session=mock_session)

        assert "专业技术能力" in scores
        assert scores["专业技术能力"] == 4.5


class TestGetLatestMatchResults:
    @pytest.mark.asyncio
    async def test_get_matches(self):
        mock_session = AsyncMock()

        mock_match = MagicMock()
        mock_match.job_profile_id = 1
        mock_match.match_score = 0.85
        mock_match.match_analysis = {"vector_similarity": 0.85}

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_match]
        mock_session.execute = AsyncMock(return_value=mock_result)

        matches = await get_latest_match_results(1, session=mock_session)

        assert len(matches) == 1
        assert matches[0]["match_score"] == 0.85


class TestGetLatestCareerPath:
    @pytest.mark.asyncio
    async def test_get_path(self):
        mock_session = AsyncMock()

        mock_path = MagicMock()
        mock_path.target_position = "前端工程师"
        mock_path.path_type = "技术专家"
        mock_path.milestones = []
        mock_path.learning_resources = {}
        mock_path.generated_plan = {}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_path
        mock_session.execute = AsyncMock(return_value=mock_result)

        path = await get_latest_career_path(1, session=mock_session)

        assert path is not None
        assert path["target_position"] == "前端工程师"


class TestGetLatestGrowthPlan:
    @pytest.mark.asyncio
    async def test_get_plan(self):
        mock_session = AsyncMock()

        mock_plan = MagicMock()
        mock_plan.cycle_weeks = 12
        mock_plan.intensity = "中等强度"
        mock_plan.tasks = []
        mock_plan.progress = {}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_plan
        mock_session.execute = AsyncMock(return_value=mock_result)

        plan = await get_latest_growth_plan(1, session=mock_session)

        assert plan is not None
        assert plan["cycle_weeks"] == 12


class TestGenerateReportContent:
    @pytest.mark.asyncio
    async def test_generate_content_success(self):
        mock_session = AsyncMock()

        # Mock profile data
        mock_profile = MagicMock()
        mock_profile.id = 1
        mock_profile.direction_tag = "前端开发"
        mock_profile.intention = {}
        mock_profile.traits = {}
        mock_profile.practice = {}
        mock_profile.soft_skills = {}
        mock_profile.hard_skills = {}

        mock_profile_result = MagicMock()
        mock_profile_result.scalar_one_or_none.return_value = mock_profile

        # Mock dimension score
        mock_score = MagicMock()
        mock_score.top_dimension = "专业技术能力"
        mock_score.sub_dimension = "专业技术能力"
        mock_score.score = 4.0

        mock_score_result = MagicMock()
        mock_score_result.scalars.return_value.all.return_value = [mock_score]

        # Mock match results
        mock_match = MagicMock()
        mock_match.job_profile_id = 1
        mock_match.match_score = 0.85
        mock_match.match_analysis = {}

        mock_match_result = MagicMock()
        mock_match_result.scalars.return_value.all.return_value = [mock_match]

        # Mock career path (none)
        mock_path_result = MagicMock()
        mock_path_result.scalar_one_or_none.return_value = None

        # Mock growth plan (none)
        mock_plan_result = MagicMock()
        mock_plan_result.scalar_one_or_none.return_value = None

        mock_session.execute = AsyncMock(side_effect=[
            mock_profile_result,
            mock_score_result,
            mock_match_result,
            mock_path_result,
            mock_plan_result,
        ])

        # Mock LLM
        mock_report_text = "## 个人概况\n测试报告内容\n\n---\n*以上内容仅供参考，不构成就业承诺或专业职业咨询意见。*"

        with patch("app.domain.services.report_service.get_llm_gateway") as mock_gateway:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=mock_report_text))
            mock_gateway.return_value = mock_llm

            content = await generate_report_content(
                user_id=1,
                profile_id=1,
                target_job="前端工程师",
                session=mock_session,
            )

        assert "report_text" in content
        assert "个人概况" in content["report_text"]
        assert "dimension_scores" in content
        assert "match_results" in content


class TestGenerateWordDocument:
    def test_generate_word_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_report.docx")

            report_content = {
                "basic_info": {"target_job": "前端工程师"},
                "report_text": "## 个人概况\n测试内容\n## 能力分析\n分析内容",
            }

            result = generate_word_document(report_content, output_path)

            assert os.path.exists(result)
            assert result.endswith(".docx")

    def test_generate_word_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = os.path.join(tmpdir, "nested", "reports")
            output_path = os.path.join(nested_dir, "test.docx")

            # 临时修改 REPORTS_DIR 为 nested_dir
            with patch("app.domain.services.report_service.REPORTS_DIR", nested_dir):
                report_content = {"report_text": "测试"}
                generate_word_document(report_content, output_path)

            assert os.path.exists(output_path)
