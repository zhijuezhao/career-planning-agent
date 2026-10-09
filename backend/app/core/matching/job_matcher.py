from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select

from app.config import get_settings
from app.core.skills import match_skill_overlap
from app.domain.models.dimension_score import DimensionScore
from app.domain.models.dimension_weight import DimensionWeight
from app.domain.models.job import JobProfile
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.vector import JobMatchEmbedding
from app.domain.services.job_query_service import job_dimension_scores
from app.infrastructure.database import async_session_factory


def extract_key_skills(job: JobProfile) -> list[str]:
    """岗位的**关键技能**（画像里「专业技术能力」维度下的 `key_skills`）。

    B5（2026-10-03）用户要求「要 key_skills 参与人岗匹配」。为什么不能只靠
    `hard_skills`：抽取器的 `hard_skills` 是**逐条招聘**的产物，
    而 `key_skills` 是**综合画像**里精提过的核心技能清单（B4 的综合卡），
    粒度与"这个岗位到底要什么"更对得上。

    读取优先级：综合卡 `aggregate_card.core_skills`（B4 产物）→
    画像六维里的 `key_skills`（旧数据/未聚合时）。
    """
    card = job.aggregate_card if isinstance(job.aggregate_card, dict) else None
    if card:
        core = card.get("core_skills")
        if isinstance(core, list) and core:
            return [str(item) for item in core]

    intensity = job.requirement_intensity
    if isinstance(intensity, dict):
        technical = intensity.get("专业技术能力")
        if isinstance(technical, dict):
            skills = technical.get("key_skills")
            if isinstance(skills, list) and skills:
                return [str(item) for item in skills]
    return []


def build_job_text(job: JobProfile) -> str:
    """Build a text representation of a job profile for embedding.

    ⚠️ B5（2026-10-03）：**必须把 `key_skills` 也拼进来**。
    学生侧的向量文本本来就含 `hard_skills.tags`（见 `resume_agent/embedding_text.py`），
    而岗位侧此前只有抽取器那条招聘的技能 —— 两边口径不一致，
    综合出来的岗位核心技能（`key_skills`）**完全没进向量**，
    等于"技能匹配"只覆盖了 1 条招聘的技能。现在两边都过
    `core.skills.normalise_skills()`，同一件事不会再因为
    `Java开发` vs `Java` 而算成两个。
    """
    from app.core.skills import normalise_skills

    parts: list[str] = []

    if job.title:
        parts.append(f"岗位：{job.title}")
    if job.industry:
        parts.append(f"行业：{job.industry}")
    if job.level:
        parts.append(f"级别：{job.level}")

    # 综合卡的核心技能优先（已归约）；没有再回落到 hard_skills
    key_skills = normalise_skills(extract_key_skills(job))
    if key_skills:
        parts.append(f"核心技能：{'、'.join(key_skills)}")

    if job.hard_skills:
        if isinstance(job.hard_skills, dict):
            tags = normalise_skills(job.hard_skills.get("tags", []))
            bonus = normalise_skills(job.hard_skills.get("bonus_tags", []))
            if tags:
                parts.append(f"技能要求：{'、'.join(tags)}")
            if bonus:
                parts.append(f"加分技能：{'、'.join(bonus)}")
        elif isinstance(job.hard_skills, list):
            tags = normalise_skills(job.hard_skills)
            if tags:
                parts.append(f"技能要求：{'、'.join(tags)}")

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
    *,
    skill_overlap: dict[str, Any] | None = None,
    skill_weight: float = 0.0,
) -> tuple[float, dict[str, Any]]:
    """Compute comprehensive match score combining vector similarity and dimension scores.

    Args:
        vector_score: Cosine distance from vector search (lower = better).
        user_dimension_scores: User's dimension scores {dimension: score}.
        job_dimension_scores: Job's dimension scores {dimension: score}.
        weights: Dimension weights {dimension: weight}.
        skill_overlap: B5 的技能命中情况（`core.skills.match_skill_overlap` 的产物）。
            为 None 时行为与改动前**逐字一致**。
        skill_weight: 技能维度的权重（0 = 不计入总分，只写进 analysis）。
            默认 0 保证既有调用方（含测试与历史快照）不受影响。

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
    base_score = vector_similarity * vector_weight + dimension_score * dimension_weight

    analysis: dict[str, Any] = {
        "vector_similarity": round(vector_similarity, 4),
        "dimension_score": round(dimension_score, 4),
        "dimension_matches": dimension_matches,
        "weights_used": weights,
    }

    # ── B5（2026-10-03）：显式技能命中率 ────────────────────────────────────────
    # 用户要求「要 key_skills 参与人岗匹配」且「方案 A+B」：
    #   A 把 key_skills 拼进岗位向量（`build_job_text`）→ 负责**召回**；
    #   B 在这里额外算一项"技能命中率" → 负责**可解释**（学生端能看到差在哪）。
    #
    # 为什么按 `(1 - w)` 混合而不是加第三项权重再归一化：
    # 原公式里 vector 0.4 / dimension 0.6 的比例是既有契约（有历史快照与测试），
    # 直接改会让所有历史分数不可比。`w=0` 时与改动前**逐字一致**。
    final_score = base_score
    if skill_overlap:
        hit_ratio = float(skill_overlap.get("hit_ratio") or 0.0)
        if skill_weight > 0 and skill_overlap.get("job_total"):
            final_score = base_score * (1 - skill_weight) + hit_ratio * skill_weight
            analysis["skill_match"] = {**skill_overlap, "weight": skill_weight}
            analysis["base_score"] = round(base_score, 4)
        else:
            # 这一维不计分 —— 但**必须写明是哪种原因**，否则学生端会看到
            # "岗位未提取到核心技能" 却其实是权重配成了 0（两种情况的处置完全不同）。
            reason = (
                "技能维度权重为 0（MATCHING_SKILL_WEIGHT），只记录命中情况不计分"
                if skill_weight <= 0
                else "岗位未提取到核心技能，本维不计分"
            )
            analysis["skill_match"] = {**skill_overlap, "weight": 0.0, "skipped": reason}

    return round(final_score, 4), analysis


def _candidate_scores(snapshot: ProfileSnapshot) -> dict[str, float]:
    """候选方六维分数：读快照冻结 JSON（不再查 DimensionScore candidate 行）"""
    return dict(snapshot.six_dim_scores_json or {})


def _candidate_skills(snapshot: ProfileSnapshot) -> list[str]:
    """候选方**技能清单**：读快照冻结的五层画像（`hard_skills.tags`）。

    为什么读快照而不是实时查学生档案：匹配必须与"冻结那一刻的画像"一致，
    否则学生改完简历后历史匹配记录的分数无法复现（快照机制存在的理由）。
    """
    five_layers = getattr(snapshot, "five_layers_json", None) or {}
    hard = five_layers.get("hard_skills") if isinstance(five_layers, dict) else None
    tags = hard.get("tags") if isinstance(hard, dict) else None
    return [str(item) for item in (tags or [])]


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
    # B5：学生侧技能也读同一份冻结快照（`five_layers_json.hard_skills.tags`）
    user_skills = _candidate_skills(snapshot)
    skill_weight = float(get_settings().matching_skill_weight or 0.0)

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

            # 岗位行：既取行业（配权重 R-5.1），也取**核心技能**（B5 的技能维度）。
            # 一次查询两用 —— 原先只 select industry，现在换成整行，查询数不变。
            job_profile = (
                await session.execute(select(JobProfile).where(JobProfile.id == job_profile_id))
            ).scalar_one_or_none()
            job_industry = (job_profile.industry if job_profile else None) or "技术研发岗"
            weights = await get_dimension_weights(job_industry, session=session)
            if not weights:
                weights = {dim: 1.0 for dim in user_dims}

            # B5：显式技能命中率（`Java开发` 与 `Java` 都归约成 `Java`，所以能对上）
            skill_overlap = None
            if job_profile is not None:
                job_skills = extract_key_skills(job_profile)
                if job_skills or user_skills:
                    skill_overlap = match_skill_overlap(user_skills, job_skills)

            # Compute score
            score, analysis = compute_match_score(
                distance,
                user_dims,
                job_dims,
                weights,
                skill_overlap=skill_overlap,
                skill_weight=skill_weight,
            )
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
    # ⚠ 不能用 `not user_vector`：pgvector 从库里读出来的是 **numpy 数组**（装了 numpy 时），
    #    对多元素数组做真值判断会抛 ValueError: The truth value of an array with more than
    #    one element is ambiguous（2026-10-09 CI 实测：Ubuntu 上这条用例必挂，
    #    Windows 本地因为拿到的是 list 才没暴露）。显式判 None / 长度。
    if user_vector is None or len(user_vector) == 0 or all(v == 0.0 for v in user_vector):
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
    # 同 `match_user_to_jobs`：pgvector 可能给出 numpy 数组，真值判断会抛 ValueError
    if user_vector is None or len(user_vector) == 0 or all(v == 0.0 for v in user_vector):
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
