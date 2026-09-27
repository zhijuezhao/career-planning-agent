from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select

from app.domain.models.dimension_score import DimensionScore
from app.domain.models.dimension_weight import DimensionWeight
from app.domain.models.job import JobProfile
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.vector import JobMatchEmbedding
from app.domain.services.job_query_service import job_dimension_scores
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

    ⚠️ **岗位侧已不再用它**（2026-09-27 P5 起）：岗位的六维读**画像**
    （`job_query_service.job_dimension_scores` ← `job_profiles.requirement_intensity`）。
    原因：`dimension_scores` 里 `profile_type='job'` 的行**全仓没有任何写入者**
    （唯一真实调用点写的是 `candidate`），所以这里对 job 永远返回 `{}` ——
    而 `compute_match_score` 会把"取不到分"当成"无要求=满匹配"，等于六维对比完全没参与。
    本函数保留给 `candidate`（以及历史读取），别再拿它读岗位。
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


def _candidate_scores(snapshot: ProfileSnapshot) -> dict[str, float]:
    """候选方六维分数：读快照冻结 JSON（不再查 DimensionScore candidate 行）"""
    return dict(snapshot.six_dim_scores_json or {})


async def _match_snapshot(
    snapshot: ProfileSnapshot,
    top_k: int,
    max_distance: float | None,
    session,
) -> list[dict[str, Any]]:
    results, _failures = await _match_snapshot_detailed(snapshot, top_k, max_distance, session)
    return results


async def _match_snapshot_detailed(
    snapshot: ProfileSnapshot,
    top_k: int,
    max_distance: float | None,
    session,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """打分主流程，返回 `(成功结果, 单岗位失败列表)`。

    B2-3 起**单个岗位打分失败不再拖垮整轮**：原先循环里任何异常都会冒泡到
    `match_user_to_jobs` 的兜底 try → 整轮返回 `[]`（学生端看到"0 个匹配"却不知为何）。
    现在失败岗位单独收集，落库时记成 `status='failed'` 供管理端排查。
    """
    # Step 1: Vector search against job embeddings (R-5.3: pass through top_k)
    hits = await search_jobs_by_vector(
        list(snapshot.embedding), top_k=top_k, max_distance=max_distance, session=session
    )
    if not hits:
        return [], []

    # Step 2: User dimension scores come from the snapshot's frozen JSON
    user_dims = _candidate_scores(snapshot)

    # Step 3: Score each hit
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for hit in hits:
        job_profile_id = hit["job_profile_id"]
        distance = hit["distance"]

        try:
            # 岗位侧六维：**读画像**（2026-09-27 P5 起）——`requirement_intensity` 里的
            # 中文六维，与学生侧同名（`core/dimensions/rubrics.py`）。
            # 此前读的是 `dimension_scores` 表 `profile_type='job'` 的行，而**全仓没人写那种行**
            # → 岗位侧恒为 `{}` → `compute_match_score` 里 `job_score=0` 被当"无要求=满匹配"，
            # 六维对比实际完全没参与。缺画像时仍是 `{}`（行为与切换前一致，不会更差）。
            job_dims = await job_dimension_scores(session, job_profile_id)

            # Per-hit job-industry weights (R-5.1)
            job_result = await session.execute(
                select(JobProfile.industry).where(JobProfile.id == job_profile_id)
            )
            job_industry = job_result.scalar_one_or_none() or "技术研发岗"
            weights = await get_dimension_weights(job_industry, session=session)
            if not weights:
                weights = {dim: 1.0 for dim in user_dims}

            # Compute score
            score, analysis = compute_match_score(distance, user_dims, job_dims, weights)
        except Exception as exc:  # noqa: BLE001 - 行级容错，失败岗位单独报告
            logger.warning(
                "单岗位打分失败 | job_profile_id={} | error={}", job_profile_id, exc
            )
            failures.append(
                {"job_profile_id": job_profile_id, "error": f"{type(exc).__name__}: {exc}"[:200]}
            )
            continue

        results.append({
            "job_profile_id": job_profile_id,
            "match_score": score,
            "distance": distance,
            "analysis": analysis,
        })

    # Sort by score descending
    results.sort(key=lambda x: x["match_score"], reverse=True)

    return results[:top_k], failures


async def match_user_to_jobs(
    user_id: int,
    snapshot: ProfileSnapshot,
    top_k: int = 10,
    max_distance: float = 0.5,
    session=None,
) -> list[dict[str, Any]]:
    """Read-only matching pipeline: search → score → rank.

    Args:
        user_id: User ID.
        snapshot: ProfileSnapshot with frozen embedding + six-dim scores.
        top_k: Number of top matches to return.
        max_distance: Maximum cosine distance threshold.
        session: Optional injected session.

    Returns:
        List of match results sorted by score (descending). No DB writes.
    """
    user_vector = snapshot.embedding
    if not user_vector or all(v == 0.0 for v in user_vector):
        # R-5.6: all-zero vector (embedding fallback) is treated as no-match;
        # a null vector would otherwise rank NaN on the populated embedding table.
        return []

    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _match_snapshot(snapshot, top_k, max_distance, session)
        return await _match_snapshot(snapshot, top_k, max_distance, session)
    except Exception as exc:
        logger.warning("Match pipeline failed | user_id={} | error={}", user_id, exc)
        return []


async def match_user_to_jobs_detailed(
    user_id: int,
    snapshot: ProfileSnapshot,
    top_k: int = 10,
    max_distance: float = 0.5,
    session=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """同 `match_user_to_jobs`，但额外返回单岗位失败列表（B2-3 落明细用）。

    保留 `match_user_to_jobs` 的旧签名与返回值不变，避免影响既有调用点与测试。
    """
    user_vector = snapshot.embedding
    if not user_vector or all(v == 0.0 for v in user_vector):
        return [], []

    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _match_snapshot_detailed(snapshot, top_k, max_distance, session)
        return await _match_snapshot_detailed(snapshot, top_k, max_distance, session)
    except Exception as exc:  # noqa: BLE001 - 整轮失败仍然兜底为「无结果」
        logger.warning("Match pipeline failed | user_id={} | error={}", user_id, exc)
        return [], []
