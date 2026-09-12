from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.dimension_weight import DimensionWeight
from app.domain.models.report import JobMatch, UserFeedback
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    DimensionWeightCreate,
    DimensionWeightListResponse,
    DimensionWeightResponse,
    DimensionWeightUpdate,
    FeedbackListResponse,
    FeedbackResponse,
    MatchResultListResponse,
    MatchResultResponse,
)

router = APIRouter()


# ── Match Results ───────────────────────────────────────────────────────────


@router.get("/results", response_model=MatchResultListResponse)
async def list_match_results(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    min_score: float | None = Query(None, ge=0.0, le=1.0),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List match results with optional filtering."""
    query = select(JobMatch)
    count_query = select(func.count()).select_from(JobMatch)

    if user_id is not None:
        query = query.where(JobMatch.user_id == user_id)
        count_query = count_query.where(JobMatch.user_id == user_id)
    if min_score is not None:
        query = query.where(JobMatch.match_score >= min_score)
        count_query = count_query.where(JobMatch.match_score >= min_score)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(JobMatch.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return MatchResultListResponse(
        total=total,
        items=[MatchResultResponse.model_validate(i) for i in items],
    )


@router.get("/results/{match_id}", response_model=MatchResultResponse)
async def get_match_result(
    match_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single match result by ID."""
    match = await db.get(JobMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match result not found")
    return match


@router.delete("/results/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_match_result(
    match_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a match result."""
    match = await db.get(JobMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match result not found")

    await db.delete(match)
    await db.flush()


# ── Feedbacks ───────────────────────────────────────────────────────────────


@router.get("/feedbacks", response_model=FeedbackListResponse)
async def list_feedbacks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    feedback_type: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List user feedbacks with optional filtering."""
    query = select(UserFeedback)
    count_query = select(func.count()).select_from(UserFeedback)

    if user_id is not None:
        query = query.where(UserFeedback.user_id == user_id)
        count_query = count_query.where(UserFeedback.user_id == user_id)
    if feedback_type:
        query = query.where(UserFeedback.feedback_type == feedback_type)
        count_query = count_query.where(UserFeedback.feedback_type == feedback_type)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(UserFeedback.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return FeedbackListResponse(
        total=total,
        items=[FeedbackResponse.model_validate(i) for i in items],
    )


@router.get("/feedbacks/{feedback_id}", response_model=FeedbackResponse)
async def get_feedback(
    feedback_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single feedback by ID."""
    feedback = await db.get(UserFeedback, feedback_id)
    if feedback is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return feedback


# ── Dimension Weights ───────────────────────────────────────────────────────


@router.get("/weights", response_model=DimensionWeightListResponse)
async def list_dimension_weights(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    job_category: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List dimension weights with optional filtering."""
    query = select(DimensionWeight)
    count_query = select(func.count()).select_from(DimensionWeight)

    if job_category:
        query = query.where(DimensionWeight.job_category == job_category)
        count_query = count_query.where(DimensionWeight.job_category == job_category)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(DimensionWeight.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return DimensionWeightListResponse(
        total=total,
        items=[DimensionWeightResponse.model_validate(i) for i in items],
    )


@router.get("/weights/{weight_id}", response_model=DimensionWeightResponse)
async def get_dimension_weight(
    weight_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single dimension weight by ID."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")
    return weight


@router.post("/weights", response_model=DimensionWeightResponse, status_code=status.HTTP_201_CREATED)
async def create_dimension_weight(
    data: DimensionWeightCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new dimension weight."""
    existing = await db.execute(
        select(DimensionWeight).where(
            DimensionWeight.job_category == data.job_category,
            DimensionWeight.top_dimension == data.top_dimension,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Dimension weight for this category and dimension already exists",
        )

    weight = DimensionWeight(**data.model_dump())
    db.add(weight)
    await db.flush()
    await db.refresh(weight)
    return weight


@router.put("/weights/{weight_id}", response_model=DimensionWeightResponse)
async def update_dimension_weight(
    weight_id: int,
    data: DimensionWeightUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a dimension weight."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")

    weight.weight = data.weight
    await db.flush()
    await db.refresh(weight)
    return weight


@router.delete("/weights/{weight_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dimension_weight(
    weight_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a dimension weight."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")

    await db.delete(weight)
    await db.flush()
