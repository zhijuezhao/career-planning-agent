from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.matching.job_matcher import (
    build_job_text,
    compute_match_score,
    embed_job,
    get_dimension_scores,
    get_dimension_weights,
    search_jobs_by_vector,
)
from app.domain.models.job import JobProfile


class TestBuildJobText:
    def test_builds_text_from_job_profile(self):
        job = JobProfile(
            title="前端工程师",
            industry="互联网",
            level="中级",
            hard_skills={"tags": ["Vue", "React", "TypeScript"]},
            soft_skills={"tags": ["沟通", "团队协作"]},
            salary_range="15000-25000",
            education_requirement="本科",
            experience_requirement="3-5年",
            summary="负责前端开发工作",
        )
        text = build_job_text(job)
        assert "前端工程师" in text
        assert "互联网" in text
        assert "Vue" in text
        assert "15000-25000" in text
        assert "前端开发工作" in text

    def test_handles_empty_fields(self):
        job = JobProfile(title="测试岗位")
        text = build_job_text(job)
        assert "测试岗位" in text

    def test_handles_list_skills(self):
        job = JobProfile(
            title="后端工程师",
            hard_skills=["Python", "Java"],
            soft_skills=["沟通"],
        )
        text = build_job_text(job)
        assert "Python" in text
        assert "Java" in text


class TestComputeMatchScore:
    def test_perfect_match(self):
        score, analysis = compute_match_score(
            vector_score=0.0,  # Perfect vector match
            user_dimension_scores={"技术": 5.0, "经验": 4.0},
            job_dimension_scores={"技术": 5.0, "经验": 4.0},
            weights={"技术": 0.6, "经验": 0.4},
        )
        assert score > 0.9
        assert analysis["vector_similarity"] == 1.0

    def test_partial_match(self):
        score, analysis = compute_match_score(
            vector_score=0.3,
            user_dimension_scores={"技术": 3.0},
            job_dimension_scores={"技术": 5.0},
            weights={"技术": 1.0},
        )
        assert 0.3 < score < 0.8
        assert analysis["dimension_matches"]["技术"]["match_ratio"] == 0.6

    def test_no_requirement_full_match(self):
        score, analysis = compute_match_score(
            vector_score=0.2,
            user_dimension_scores={},
            job_dimension_scores={"技术": 0.0},
            weights={"技术": 1.0},
        )
        assert analysis["dimension_matches"]["技术"]["match_ratio"] == 1.0

    def test_empty_weights(self):
        score, analysis = compute_match_score(
            vector_score=0.5,
            user_dimension_scores={"技术": 3.0},
            job_dimension_scores={"技术": 4.0},
            weights={},
        )
        assert 0.0 <= score <= 1.0


class TestSearchJobsByVector:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        fake_vector = [0.1] * 1024
        mock_session = AsyncMock()

        # Mock the result
        mock_emb = MagicMock()
        mock_emb.job_profile_id = 1
        mock_emb.content = "Job content"
        mock_emb.embedding = fake_vector

        mock_result = MagicMock()
        mock_result.all.return_value = [(mock_emb, 0.15)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        results = await search_jobs_by_vector(fake_vector, top_k=5, session=mock_session)

        assert len(results) == 1
        assert results[0]["job_profile_id"] == 1
        assert results[0]["distance"] == 0.15

    @pytest.mark.asyncio
    async def test_respects_max_distance(self):
        fake_vector = [0.1] * 1024
        mock_session = AsyncMock()

        mock_emb = MagicMock()
        mock_emb.job_profile_id = 1
        mock_emb.content = "Job content"
        mock_emb.embedding = fake_vector

        mock_result = MagicMock()
        mock_result.all.return_value = [(mock_emb, 0.8)]  # High distance
        mock_session.execute = AsyncMock(return_value=mock_result)

        results = await search_jobs_by_vector(fake_vector, top_k=5, max_distance=0.5, session=mock_session)

        assert len(results) == 0  # Filtered out by max_distance


class TestGetDimensionScores:
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

        scores = await get_dimension_scores("candidate", 1, session=mock_session)

        assert "专业技术能力" in scores
        assert scores["专业技术能力"] == 4.5


class TestGetDimensionWeights:
    @pytest.mark.asyncio
    async def test_get_weights(self):
        mock_session = AsyncMock()

        mock_weight = MagicMock()
        mock_weight.top_dimension = "专业技术能力"
        mock_weight.weight = 0.3

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_weight]
        mock_session.execute = AsyncMock(return_value=mock_result)

        weights = await get_dimension_weights("技术研发岗", session=mock_session)

        assert "专业技术能力" in weights
        assert weights["专业技术能力"] == 0.3


class TestEmbedJob:
    @pytest.mark.asyncio
    async def test_embed_job_success(self):
        mock_session = AsyncMock()

        # Mock job profile query
        mock_job = JobProfile(id=1, title="前端工程师", industry="互联网")
        mock_job_result = MagicMock()
        mock_job_result.scalar_one_or_none.return_value = mock_job

        # Mock existing embedding query (none exists)
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        mock_session.execute = AsyncMock(side_effect=[mock_job_result, mock_existing_result])

        with patch("app.core.llm.embeddings.get_embeddings") as mock_get:
            mock_embeddings = AsyncMock()
            mock_embeddings.aembed_query = AsyncMock(return_value=[0.1] * 1024)
            mock_get.return_value = mock_embeddings

            result = await embed_job(1, session=mock_session)

        assert result is not None
        assert result.job_profile_id == 1
        assert mock_session.add.called
