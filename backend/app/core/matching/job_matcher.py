from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select

from app.domain.models.dimension_score import DimensionScore
from app.domain.models.dimension_weight import DimensionWeight
from app.domain.models.job import JobProfile
from app.domain.models.report import JobMatch
from app.domain.models.vector import JobMatchEmbedding
from app.infrastructure.database import async_session_factory


def build_job_text(job: JobProfile) -> str:
    """Build a text representation of a job profile for embedding."""
    parts: list[str] = []

    if job.title:
        parts.append(f"岗位：{job.title}")
    if job.industry:
        parts.append(f"行业：{job.industry}")
    if job.level:
        parts.append(f"级别：{job.level}")

    if job.hard_skills:
        if isinstance(job.hard_skills, dict):
            tags = job.hard_skills.get("tags", [])
            if tags:
                parts.append(f"技能要求：{'、'.join(tags)}")
        elif isinstance(job.hard_skills, list):
            parts.append(f"技能要求：{'、'.join(job.hard_skills)}")

    if job.soft_skills:
        if isinstance(job.soft_skills, dict):
            tags = job.soft_skills.get("tags", [])
            if tags:
                parts.append(f"软技能：{'、'.join(tags)}")
        elif isinstance(job.soft_skills, list):
            parts.append(f"软技能：{'、'.join(job.soft_skills)}")

    if job.salary_range:
        parts.append(f"薪资：{job.salary_range}")
    if job.education_requirement:
        parts.append(f"学历要求：{job.education_requirement}")
    if job.experience_requirement:
        parts.append(f"经验要求：{job.experience_requirement}")

    if job.requirement_intensity:
        if isinstance(job.requirement_intensity, dict):
            dims = []
            for key, val in job.requirement_intensity.items():
                if isinstance(val, dict):
                    score = val.get("score", 0)
                    dims.append(f"{key}({score})")
                else:
                    dims.append(f"{key}({val})")
            if dims:
                parts.append(f"能力要求：{'、'.join(dims)}")

    if job.summary:
        parts.append(f"岗位描述：{job.summary}")

    return "\n".join(parts)


async def embed_job(
    job_profile_id: int,
    session=None,
) -> JobMatchEmbedding | None:
    """Generate and store embedding for a job profile.

    Args:
        job_profile_id: ID of the job profile to embed.
        session: Optional injected session (for testing).

    Returns:
        The created JobMatchEmbedding or None on failure.
    """

    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _do_embed_job(job_profile_id, session)
        return await _do_embed_job(job_profile_id, session)
    except Exception as exc:
        logger.warning("Job embedding failed | job_profile_id={} | error={}", job_profile_id, exc)
        return None


async def _do_embed_job(job_profile_id: int, session) -> JobMatchEmbedding | None:
    from app.core.llm.embeddings import get_embeddings

    result = await session.execute(
        select(JobProfile).where(JobProfile.id == job_profile_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        return None

    content = build_job_text(job)
    if not content.strip():
        return None

    embeddings = get_embeddings()
    vector = await embeddings.aembed_query(content)

    # Check for existing embedding
    existing = await session.execute(
        select(JobMatchEmbedding).where(JobMatchEmbedding.job_profile_id == job_profile_id)
    )
    emb_record = existing.scalar_one_or_none()

    if emb_record:
        emb_record.content = content
        emb_record.embedding = vector
    else:
        emb_record = JobMatchEmbedding(
            job_profile_id=job_profile_id,
            content=content,
            embedding=vector,
        )
        session.add(emb_record)

    await session.commit()
    await session.refresh(emb_record)
    logger.info("Job embedding saved | job_profile_id={} | dims={}", job_profile_id, len(vector))
    return emb_record


async def search_jobs_by_vector(
    user_vector: list[float],
    top_k: int = 10,
    max_distance: float | None = None,
    session=None,
) -> list[dict[str, Any]]:
    """Search jobs by user profile vector using cosine distance.

    Args:
        user_vector: 1024-dim user profile embedding.
        top_k: Maximum number of results.
        max_distance: Optional distance cutoff (lower = more similar).
        session: Optional injected session.

    Returns:
        List of dicts with job_profile_id, distance, content.
    """
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _do_search(user_vector, top_k, max_distance, session)
        return await _do_search(user_vector, top_k, max_distance, session)
    except Exception as exc:
        logger.warning("Job search failed | error={}", exc)
        return []


async def _do_search(
    user_vector: list[float],
    top_k: int,
    max_distance: float | None,
    session,
) -> list[dict[str, Any]]:
    distance_expr = JobMatchEmbedding.embedding.cosine_distance(user_vector)

    stmt = (
        select(JobMatchEmbedding, distance_expr.label("distance"))
        .order_by(distance_expr)
        .limit(top_k)
    )

    result = await session.execute(stmt)
    rows = result.all()

    hits: list[dict[str, Any]] = []
    for emb, distance in rows:
        dist_float = float(distance)
        if max_distance is not None and dist_float > max_distance:
            continue
        hits.append({
            "job_profile_id": emb.job_profile_id,
            "distance": dist_float,
            "content": emb.content,
        })

    return hits


async def get_dimension_scores(
    profile_type: str,
    profile_id: int,
    session=None,
) -> dict[str, float]:
    """Get dimension scores for a profile.

    Returns dict of {top_dimension: score}.
    """
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _get_scores(profile_type, profile_id, session)
        return await _get_scores(profile_type, profile_id, session)
    except Exception as exc:
        logger.warning("Failed to get dimension scores | error={}", exc)
        return {}


async def _get_scores(profile_type: str, profile_id: int, session) -> dict[str, float]:
    result = await session.execute(
        select(DimensionScore).where(
            DimensionScore.profile_type == profile_type,
            DimensionScore.profile_id == profile_id,
        )
    )
    scores = result.scalars().all()

    dimension_scores: dict[str, float] = {}
    for s in scores:
        if s.sub_dimension == s.top_dimension or not s.sub_dimension:
            dimension_scores[s.top_dimension] = s.score
        else:
            # Aggregate sub-dimensions into top dimension
            if s.top_dimension not in dimension_scores:
                dimension_scores[s.top_dimension] = []
            dimension_scores[s.top_dimension].append(s.score)

    # Average sub-dimensions
    for key, val in dimension_scores.items():
        if isinstance(val, list):
            dimension_scores[key] = sum(val) / len(val) if val else 0.0

    return dimension_scores


async def get_dimension_weights(
    job_category: str,
    session=None,
) -> dict[str, float]:
    """Get dimension weights for a job category.

    Returns dict of {top_dimension: weight}.
    """
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _get_weights(job_category, session)
        return await _get_weights(job_category, session)
    except Exception as exc:
        logger.warning("Failed to get dimension weights | error={}", exc)
        return {}


async def _get_weights(job_category: str, session) -> dict[str, float]:
    result = await session.execute(
        select(DimensionWeight).where(DimensionWeight.job_category == job_category)
    )
    weights = result.scalars().all()
    return {w.top_dimension: w.weight for w in weights}


def compute_match_score(
    vector_score: float,
    user_dimension_scores: dict[str, float],
    job_dimension_scores: dict[str, float],
    weights: dict[str, float],
) -> tuple[float, dict[str, Any]]:
    """Compute comprehensive match score combining vector similarity and dimension scores.

    Args:
        vector_score: Cosine distance from vector search (lower = better).
        user_dimension_scores: User's dimension scores {dimension: score}.
        job_dimension_scores: Job's dimension scores {dimension: score}.
        weights: Dimension weights {dimension: weight}.

    Returns:
        Tuple of (final_score, analysis_dict).
    """
    # Convert distance to similarity (0-1 range, higher = better)
    vector_similarity = max(0.0, 1.0 - vector_score)

    # Compute dimension match score
    dimension_matches: dict[str, dict[str, float]] = {}
    weighted_sum = 0.0
    total_weight = 0.0

    all_dims = set(user_dimension_scores.keys()) | set(job_dimension_scores.keys())
    for dim in all_dims:
        user_score = user_dimension_scores.get(dim, 0.0)
        job_score = job_dimension_scores.get(dim, 0.0)
        weight = weights.get(dim, 1.0)

        # Match score: how well user meets job requirement
        if job_score > 0:
            match_ratio = min(user_score / job_score, 1.0) if job_score > 0 else 0.0
        else:
            match_ratio = 1.0  # No requirement = full match

        dimension_matches[dim] = {
            "user_score": user_score,
            "job_score": job_score,
            "weight": weight,
            "match_ratio": round(match_ratio, 3),
        }

        weighted_sum += match_ratio * weight
        total_weight += weight

    dimension_score = weighted_sum / total_weight if total_weight > 0 else 0.0

    # Final score: weighted combination
    vector_weight = 0.4
    dimension_weight = 0.6
    final_score = vector_similarity * vector_weight + dimension_score * dimension_weight

    analysis = {
        "vector_similarity": round(vector_similarity, 4),
        "dimension_score": round(dimension_score, 4),
        "dimension_matches": dimension_matches,
        "weights_used": weights,
    }

    return round(final_score, 4), analysis


async def save_match_result(
    user_id: int,
    profile_id: int,
    job_profile_id: int,
    match_score: float,
    match_analysis: dict[str, Any],
    session=None,
) -> JobMatch | None:
    """Save a match result to the database."""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _save_match(user_id, profile_id, job_profile_id, match_score, match_analysis, session)
        return await _save_match(user_id, profile_id, job_profile_id, match_score, match_analysis, session)
    except Exception as exc:
        logger.warning("Failed to save match result | error={}", exc)
        return None


async def _save_match(
    user_id: int,
    profile_id: int,
    job_profile_id: int,
    match_score: float,
    match_analysis: dict[str, Any],
    session,
) -> JobMatch:
    match = JobMatch(
        user_id=user_id,
        profile_id=profile_id,
        job_profile_id=job_profile_id,
        match_score=match_score,
        match_analysis=match_analysis,
    )
    session.add(match)
    await session.commit()
    await session.refresh(match)
    return match


async def match_user_to_jobs(
    user_id: int,
    profile_id: int,
    user_vector: list[float],
    top_k: int = 10,
    max_distance: float = 0.5,
    session=None,
) -> list[dict[str, Any]]:
    """Full matching pipeline: search → score → rank → persist.

    Args:
        user_id: User ID.
        profile_id: AbilityProfile ID.
        user_vector: User profile embedding (1024-dim).
        top_k: Number of top matches to return.
        max_distance: Maximum cosine distance threshold.
        session: Optional injected session.

    Returns:
        List of match results sorted by score (descending).
    """
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _match_pipeline(user_id, profile_id, user_vector, top_k, max_distance, session)
        return await _match_pipeline(user_id, profile_id, user_vector, top_k, max_distance, session)
    except Exception as exc:
        logger.warning("Match pipeline failed | user_id={} | error={}", user_id, exc)
        return []


async def _match_pipeline(
    user_id: int,
    profile_id: int,
    user_vector: list[float],
    top_k: int,
    max_distance: float,
    session,
) -> list[dict[str, Any]]:
    # Step 1: Vector search
    hits = await _do_search(user_vector, top_k * 2, max_distance, session)
    if not hits:
        return []

    # Step 2: Get user dimension scores
    user_dim_scores = await _get_scores("candidate", profile_id, session)

    # Step 3: Score each hit
    results: list[dict[str, Any]] = []
    for hit in hits:
        job_profile_id = hit["job_profile_id"]
        distance = hit["distance"]

        # Get job dimension scores
        job_dim_scores = await _get_scores("job", job_profile_id, session)

        # Get job category for weights
        job_result = await session.execute(
            select(JobProfile.industry).where(JobProfile.id == job_profile_id)
        )
        job_industry = job_result.scalar_one_or_none() or "技术研发岗"

        # Get weights
        weights = await _get_weights(job_industry, session)
        if not weights:
            weights = {dim: 1.0 for dim in user_dim_scores}

        # Compute score
        score, analysis = compute_match_score(distance, user_dim_scores, job_dim_scores, weights)

        results.append({
            "job_profile_id": job_profile_id,
            "match_score": score,
            "distance": distance,
            "analysis": analysis,
        })

    # Sort by score descending
    results.sort(key=lambda x: x["match_score"], reverse=True)

    # Persist top matches
    for r in results[:top_k]:
        await _save_match(user_id, profile_id, r["job_profile_id"], r["match_score"], r["analysis"], session)

    return results[:top_k]
