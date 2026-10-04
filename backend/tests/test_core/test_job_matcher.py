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


class TestKeySkillsInJobText:
    """B5（2026-10-03）：`key_skills` 必须进岗位向量。

    此前岗位向量里只有**抽取器那条招聘**的技能，而综合出来的岗位核心技能
    （`aggregate_card.core_skills`）完全没进去 —— 学生侧的向量本来就含技能，
    两边口径不一致，技能匹配被系统性低估。
    """

    def test_prefers_aggregate_card_core_skills(self):
        job = JobProfile(
            title="Java",
            level="初级",
            hard_skills={"tags": ["Java"]},
            aggregate_card={"core_skills": ["Java", "Spring Boot", "MySQL"]},
            requirement_intensity={"专业技术能力": {"score": 3, "key_skills": ["旧数据"]}},
        )
        text = build_job_text(job)
        assert "核心技能：Java、Spring Boot、MySQL" in text
        assert "旧数据" not in text, "综合卡优先，旧字段不该再出现"

    def test_falls_back_to_requirement_intensity(self):
        """未聚合的旧数据：退回画像六维里的 key_skills。"""
        job = JobProfile(
            title="Java",
            requirement_intensity={"专业技术能力": {"score": 3, "key_skills": ["Redis"]}},
        )
        assert "核心技能：Redis" in build_job_text(job)

    def test_bonus_skills_are_included(self):
        job = JobProfile(
            title="Java",
            hard_skills={"tags": ["Java"], "bonus_tags": ["Go", "Rust"]},
        )
        text = build_job_text(job)
        assert "加分技能：Go、Rust" in text

    def test_skills_are_normalised_on_both_sides(self):
        """归一化后 `Java开发` 与 `Java` 才是同一个词，否则向量里对不上。"""
        job = JobProfile(
            title="Java",
            aggregate_card={"core_skills": ["Java开发", "MySQL数据库", "springboot"]},
        )
        text = build_job_text(job)
        assert "核心技能：Java、MySQL、Spring Boot" in text

    def test_extract_key_skills_helper(self):
        from app.core.matching.job_matcher import extract_key_skills

        assert extract_key_skills(JobProfile(title="x")) == []
        assert extract_key_skills(
            JobProfile(title="x", aggregate_card={"core_skills": ["Java"]})
        ) == ["Java"]


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


class TestSkillDimensionInMatchScore:
    """B5：技能命中率按 `base*(1-w) + hit_ratio*w` **混合**进总分。

    为什么不加第三项再归一化：既有 0.4（向量）/0.6（六维）的比例是历史契约，
    改了会让所有历史快照分数不可比。`w=0` 时必须与改动前**逐字一致**。
    """

    BASE = dict(
        vector_score=0.2,
        user_dimension_scores={"技术": 4.0},
        job_dimension_scores={"技术": 4.0},
        weights={"技术": 1.0},
    )

    def test_weight_zero_keeps_legacy_score(self):
        """权重 0 → 分数与改动前**完全一致**（向后兼容的硬要求）。

        `skill_match` 仍会写进 analysis（那是信息），但要写明"不计分的原因"，
        而不是让它看起来像"岗位没有技能要求"。
        """
        legacy_score, legacy_analysis = compute_match_score(**self.BASE)
        same_score, same_analysis = compute_match_score(
            **self.BASE,
            skill_overlap={"hit_ratio": 0.1, "job_total": 10, "matched": [], "missing": []},
            skill_weight=0.0,
        )
        assert same_score == legacy_score
        assert same_analysis["dimension_score"] == legacy_analysis["dimension_score"]
        assert same_analysis["skill_match"]["weight"] == 0.0
        assert "MATCHING_SKILL_WEIGHT" in same_analysis["skill_match"]["skipped"]

    def test_no_skill_overlap_keeps_analysis_clean(self):
        """完全不传技能信息（旧调用方）→ analysis 里不该凭空多出 `skill_match`。"""
        _score, analysis = compute_match_score(**self.BASE)
        assert "skill_match" not in analysis

    def test_weight_moves_score_towards_hit_ratio(self):
        base_score, _ = compute_match_score(**self.BASE)
        high, high_analysis = compute_match_score(
            **self.BASE,
            skill_overlap={"hit_ratio": 1.0, "job_total": 4, "matched": ["Java"], "missing": []},
            skill_weight=0.15,
        )
        low, _ = compute_match_score(
            **self.BASE,
            skill_overlap={"hit_ratio": 0.0, "job_total": 4, "matched": [], "missing": ["Java"]},
            skill_weight=0.15,
        )
        assert low < base_score < high
        assert high_analysis["base_score"] == round(base_score, 4)
        assert high_analysis["skill_match"]["hit_ratio"] == 1.0

    def test_job_without_skills_does_not_score(self):
        """岗位没提取到核心技能 → 这一维不计分，但要写明原因（别被读成"完全匹配"）。"""
        base_score, _ = compute_match_score(**self.BASE)
        score, analysis = compute_match_score(
            **self.BASE,
            skill_overlap={"hit_ratio": 0.0, "job_total": 0, "matched": [], "missing": []},
            skill_weight=0.15,
        )
        assert score == base_score
        assert analysis["skill_match"]["weight"] == 0.0
        assert "未提取到核心技能" in analysis["skill_match"]["skipped"]


class TestCandidateSkills:
    def test_reads_frozen_snapshot(self):
        """学生技能读**冻结快照**：改完简历后历史匹配分数必须还能复现。"""
        from app.core.matching.job_matcher import _candidate_skills

        snapshot = MagicMock()
        snapshot.five_layers_json = {"hard_skills": {"tags": ["Java开发", "MySQL"]}}
        assert _candidate_skills(snapshot) == ["Java开发", "MySQL"]

    def test_missing_fields(self):
        from app.core.matching.job_matcher import _candidate_skills

        snapshot = MagicMock()
        snapshot.five_layers_json = {}
        assert _candidate_skills(snapshot) == []


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
