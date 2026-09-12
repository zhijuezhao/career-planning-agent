from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.prompts.career_path import build_career_path_messages
from app.core.llm.prompts.growth_plan import build_growth_plan_messages
from app.domain.models.dimension_score import DimensionScore
from app.domain.models.job import JobProfile
from app.domain.models.profile import AbilityProfile
from app.domain.models.report import GrowthPath, GrowthPlan
from app.infrastructure.database import async_session_factory


async def get_ability_profile(
    user_id: int,
    profile_id: int,
    session=None,
) -> AbilityProfile | None:
    """获取用户能力画像。"""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _get_profile(profile_id, session)
        return await _get_profile(profile_id, session)
    except Exception as exc:
        logger.warning("Failed to get ability profile | error={}", exc)
        return None


async def _get_profile(profile_id: int, session) -> AbilityProfile | None:
    result = await session.execute(
        select(AbilityProfile).where(AbilityProfile.id == profile_id)
    )
    return result.scalar_one_or_none()


async def get_dimension_scores_map(
    profile_type: str,
    profile_id: int,
    session=None,
) -> dict[str, float]:
    """获取维度评分映射。"""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _get_dimension_scores(profile_type, profile_id, session)
        return await _get_dimension_scores(profile_type, profile_id, session)
    except Exception as exc:
        logger.warning("Failed to get dimension scores | error={}", exc)
        return {}


async def _get_dimension_scores(
    profile_type: str,
    profile_id: int,
    session,
) -> dict[str, float]:
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
            if s.top_dimension not in dimension_scores:
                dimension_scores[s.top_dimension] = []
            dimension_scores[s.top_dimension].append(s.score)

    for key, val in dimension_scores.items():
        if isinstance(val, list):
            dimension_scores[key] = sum(val) / len(val) if val else 0.0

    return dimension_scores


async def get_target_job(
    job_profile_id: int,
    session=None,
) -> JobProfile | None:
    """获取目标岗位信息。"""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _get_job(job_profile_id, session)
        return await _get_job(job_profile_id, session)
    except Exception as exc:
        logger.warning("Failed to get target job | error={}", exc)
        return None


async def _get_job(job_profile_id: int, session) -> JobProfile | None:
    result = await session.execute(
        select(JobProfile).where(JobProfile.id == job_profile_id)
    )
    return result.scalar_one_or_none()


def _safe_json_loads(text: str) -> dict[str, Any]:
    """安全解析 JSON，支持去除代码围栏。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON response")
        return {}


async def generate_career_path(
    user_id: int,
    profile_id: int,
    target_job_id: int,
    current_stage: str = "在校学生",
    session=None,
) -> GrowthPath | None:
    """生成职业路线规划。"""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _generate_path(user_id, profile_id, target_job_id, current_stage, session)
        return await _generate_path(user_id, profile_id, target_job_id, current_stage, session)
    except Exception as exc:
        logger.warning("Failed to generate career path | error={}", exc)
        return None


async def _generate_path(
    user_id: int,
    profile_id: int,
    target_job_id: int,
    current_stage: str,
    session,
) -> GrowthPath | None:
    # 获取用户能力画像
    profile = await _get_profile(profile_id, session)
    if not profile:
        logger.warning("Ability profile not found | profile_id={}", profile_id)
        return None

    # 获取维度评分
    dim_scores = await _get_dimension_scores("candidate", profile_id, session)

    # 获取目标岗位
    target_job = await _get_job(target_job_id, session)
    if not target_job:
        logger.warning("Target job not found | job_id={}", target_job_id)
        return None

    # 构建五层能力 JSON
    five_layers = {
        "direction_tag": profile.direction_tag,
        "intention": profile.intention,
        "traits": profile.traits,
        "practice": profile.practice,
        "soft_skills": profile.soft_skills,
        "hard_skills": profile.hard_skills,
    }

    # 构建目标岗位 JSON
    target_job_info = {
        "title": target_job.title,
        "industry": target_job.industry,
        "level": target_job.level,
        "hard_skills": target_job.hard_skills,
        "soft_skills": target_job.soft_skills,
        "requirement_intensity": target_job.requirement_intensity,
    }

    # 调用 LLM 生成路线
    messages = build_career_path_messages(
        five_layers_json=json.dumps(five_layers, ensure_ascii=False, indent=2),
        dimension_scores_json=json.dumps(dim_scores, ensure_ascii=False, indent=2),
        target_job_json=json.dumps(target_job_info, ensure_ascii=False, indent=2),
        current_stage=current_stage,
    )

    gateway = get_llm_gateway()
    response = await gateway.ainvoke(messages)
    path_data = _safe_json_loads(response.content)

    if not path_data:
        logger.warning("LLM returned empty career path data")
        return None

    # 持久化到数据库
    growth_path = GrowthPath(
        user_id=user_id,
        target_position=path_data.get("target_position", target_job.title),
        path_type=path_data.get("path_type", "技术专家"),
        current_abilities=path_data.get("current_abilities", {}),
        target_abilities=path_data.get("target_abilities", {}),
        milestones=path_data.get("milestones", []),
        generated_plan=path_data,
        learning_resources=path_data.get("learning_resources", {}),
    )
    session.add(growth_path)
    await session.commit()
    await session.refresh(growth_path)
    logger.info("Career path created | user_id={} | path_id={}", user_id, growth_path.id)
    return growth_path


async def generate_growth_plan(
    user_id: int,
    growth_path_id: int,
    weekly_hours: int = 10,
    cycle_weeks: int = 12,
    session=None,
) -> GrowthPlan | None:
    """生成成长计划。"""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _generate_plan(user_id, growth_path_id, weekly_hours, cycle_weeks, session)
        return await _generate_plan(user_id, growth_path_id, weekly_hours, cycle_weeks, session)
    except Exception as exc:
        logger.warning("Failed to generate growth plan | error={}", exc)
        return None


async def _generate_plan(
    user_id: int,
    growth_path_id: int,
    weekly_hours: int,
    cycle_weeks: int,
    session,
) -> GrowthPlan | None:
    # 获取职业路线
    result = await session.execute(
        select(GrowthPath).where(GrowthPath.id == growth_path_id)
    )
    growth_path = result.scalar_one_or_none()
    if not growth_path:
        logger.warning("Growth path not found | path_id={}", growth_path_id)
        return None

    if not growth_path.generated_plan:
        logger.warning("Growth path has no generated plan data | path_id={}", growth_path_id)
        return None

    # 构建当前能力和目标能力 JSON
    current_scores = growth_path.current_abilities or {}
    target_scores = growth_path.target_abilities or {}

    # 调用 LLM 生成计划
    messages = build_growth_plan_messages(
        career_path_json=json.dumps(growth_path.generated_plan, ensure_ascii=False, indent=2),
        current_scores_json=json.dumps(current_scores, ensure_ascii=False, indent=2),
        target_scores_json=json.dumps(target_scores, ensure_ascii=False, indent=2),
        weekly_hours=weekly_hours,
        cycle_weeks=cycle_weeks,
    )

    gateway = get_llm_gateway()
    response = await gateway.ainvoke(messages)
    plan_data = _safe_json_loads(response.content)

    if not plan_data:
        logger.warning("LLM returned empty growth plan data")
        return None

    # 持久化到数据库
    growth_plan = GrowthPlan(
        user_id=user_id,
        growth_path_id=growth_path_id,
        cycle_weeks=plan_data.get("cycle_weeks", cycle_weeks),
        intensity=plan_data.get("intensity", "中等强度"),
        tasks=plan_data.get("tasks", []),
        progress=plan_data.get("progress_tracking", {}),
        weekly_reviews=plan_data.get("weekly_review_template", {}),
    )
    session.add(growth_plan)
    await session.commit()
    await session.refresh(growth_plan)
    logger.info("Growth plan created | user_id={} | plan_id={}", user_id, growth_plan.id)
    return growth_plan


async def get_career_paths(
    user_id: int,
    session=None,
    skip: int = 0,
    limit: int = 20,
) -> list[GrowthPath]:
    """获取用户的职业路线列表。"""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _get_paths(user_id, session, skip, limit)
        return await _get_paths(user_id, session, skip, limit)
    except Exception as exc:
        logger.warning("Failed to get career paths | error={}", exc)
        return []


async def _get_paths(user_id: int, session, skip: int, limit: int) -> list[GrowthPath]:
    result = await session.execute(
        select(GrowthPath)
        .where(GrowthPath.user_id == user_id)
        .order_by(GrowthPath.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_growth_plans(
    user_id: int,
    growth_path_id: int | None = None,
    session=None,
    skip: int = 0,
    limit: int = 20,
) -> list[GrowthPlan]:
    """获取用户的成长计划列表。"""
    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        if own_session:
            async with session:
                return await _get_plans(user_id, growth_path_id, session, skip, limit)
        return await _get_plans(user_id, growth_path_id, session, skip, limit)
    except Exception as exc:
        logger.warning("Failed to get growth plans | error={}", exc)
        return []


async def _get_plans(
    user_id: int,
    growth_path_id: int | None,
    session,
    skip: int,
    limit: int,
) -> list[GrowthPlan]:
    stmt = select(GrowthPlan).where(GrowthPlan.user_id == user_id)
    if growth_path_id is not None:
        stmt = stmt.where(GrowthPlan.growth_path_id == growth_path_id)
    stmt = stmt.order_by(GrowthPlan.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
