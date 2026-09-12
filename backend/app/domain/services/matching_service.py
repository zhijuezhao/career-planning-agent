from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.matching import match_user_to_jobs
from app.domain.models.report import JobMatch, UserFeedback
from app.domain.models.resume import UserMatchEmbedding
from app.schemas.matching import (
    FeedbackCreateRequest,
    FeedbackResponse,
    MatchAnalysis,
    MatchResultItem,
    MatchRunRequest,
    MatchRunResponse,
)


async def get_user_vector(user_id: int, profile_id: int, session: AsyncSession) -> list[float] | None:
    """获取用户画像向量。"""
    result = await session.execute(
        select(UserMatchEmbedding).where(
            UserMatchEmbedding.user_id == user_id,
            UserMatchEmbedding.profile_id == profile_id,
        )
    )
    embedding = result.scalar_one_or_none()
    if embedding is None:
        return None
    return embedding.embedding


async def run_matching(
    user_id: int,
    request: MatchRunRequest,
    session: AsyncSession,
) -> MatchRunResponse:
    """执行人岗匹配流程。"""
    user_vector = await get_user_vector(user_id, request.profile_id, session)
    if user_vector is None:
        raise ValueError("用户画像向量不存在，请先生成画像嵌入")

    raw_results = await match_user_to_jobs(
        user_id=user_id,
        profile_id=request.profile_id,
        user_vector=user_vector,
        top_k=request.top_k,
        max_distance=request.max_distance,
        session=session,
    )

    results = [
        MatchResultItem(
            job_profile_id=r["job_profile_id"],
            match_score=r["match_score"],
            distance=r["distance"],
            analysis=MatchAnalysis(**r["analysis"]),
        )
        for r in raw_results
    ]

    return MatchRunResponse(
        user_id=user_id,
        profile_id=request.profile_id,
        total=len(results),
        results=results,
    )


async def get_match_history(
    user_id: int,
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
) -> list["MatchResultItem"]:
    """获取用户历史匹配结果。"""
    result = await session.execute(
        select(JobMatch)
        .where(JobMatch.user_id == user_id)
        .order_by(JobMatch.match_score.desc())
        .offset(skip)
        .limit(limit)
    )
    matches = result.scalars().all()

    items = []
    for m in matches:
        if m.match_analysis:
            items.append(
                MatchResultItem(
                    job_profile_id=m.job_profile_id,
                    match_score=m.match_score or 0.0,
                    distance=1.0 - m.match_analysis.get("vector_similarity", 0.0),
                    analysis=MatchAnalysis(**m.match_analysis),
                )
            )
    return items


async def create_feedback(
    user_id: int,
    request: FeedbackCreateRequest,
    session: AsyncSession,
) -> FeedbackResponse:
    """创建用户反馈。"""
    match = await session.get(JobMatch, request.match_id)
    if match is None:
        raise ValueError("匹配结果不存在")
    if match.user_id != user_id:
        raise PermissionError("无权操作此匹配结果")

    feedback = UserFeedback(
        user_id=user_id,
        match_id=request.match_id,
        feedback_type=request.feedback_type,
        comment=request.comment,
    )
    session.add(feedback)
    await session.flush()
    await session.refresh(feedback)
    logger.info("Feedback created | user_id={} | match_id={}", user_id, request.match_id)
    return FeedbackResponse.model_validate(feedback)


async def get_user_feedbacks(
    user_id: int,
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
) -> list[FeedbackResponse]:
    """获取用户反馈历史。"""
    result = await session.execute(
        select(UserFeedback)
        .where(UserFeedback.user_id == user_id)
        .order_by(UserFeedback.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    feedbacks = result.scalars().all()
    return [FeedbackResponse.model_validate(f) for f in feedbacks]
