from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.domain.models.report import JobMatch, UserFeedback
from app.domain.models.user import User
from app.domain.services.matching_service import (
    create_feedback,
    get_match_history,
    get_user_feedbacks,
    run_matching,
)
from app.infrastructure.database import get_db
from app.schemas.matching import (
    FeedbackCreateRequest,
    FeedbackListResponse,
    FeedbackResponse,
    MatchListResponse,
    MatchRunRequest,
    MatchRunResponse,
)

router = APIRouter()


@router.post("/run", response_model=MatchRunResponse)
async def run_match(
    request: MatchRunRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """执行人岗匹配，返回匹配结果列表。"""
    try:
        return await run_matching(current_user.id, request, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/results", response_model=MatchListResponse)
async def list_match_results(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的历史匹配结果。"""
    count_stmt = select(func.count()).select_from(JobMatch).where(JobMatch.user_id == current_user.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    items = await get_match_history(current_user.id, db, skip=skip, limit=limit)
    return MatchListResponse(total=total, items=items)


@router.get("/results/{match_id}", response_model=MatchListResponse)
async def get_match_detail(
    match_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取单个匹配结果详情。"""
    match = await db.get(JobMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="匹配结果不存在")
    if match.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此匹配结果")

    items = []
    if match.match_analysis:
        from app.schemas.matching import MatchAnalysis, MatchResultItem
        items.append(
            MatchResultItem(
                job_profile_id=match.job_profile_id,
                match_score=match.match_score or 0.0,
                distance=1.0 - match.match_analysis.get("vector_similarity", 0.0),
                analysis=MatchAnalysis(**match.match_analysis),
            )
        )
    return MatchListResponse(total=len(items), items=items)


@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    request: FeedbackCreateRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """提交用户反馈（点赞/踩/已申请/已收藏）。"""
    try:
        return await create_feedback(current_user.id, request, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/feedback", response_model=FeedbackListResponse)
async def list_feedbacks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的反馈历史。"""
    count_stmt = select(func.count()).select_from(UserFeedback).where(UserFeedback.user_id == current_user.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    items = await get_user_feedbacks(current_user.id, db, skip=skip, limit=limit)
    return FeedbackListResponse(total=total, items=items)
