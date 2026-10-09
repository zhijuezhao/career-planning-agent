from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.domain.models.job import JobProfile
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import JobProfileListResponse, JobProfileResponse

router = APIRouter()


@router.get("", response_model=JobProfileListResponse)
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    industry: str | None = None,
    level: str | None = None,
    keyword: str | None = Query(None, max_length=50),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Public job profile list for students."""
    query = select(JobProfile)
    count_query = select(func.count()).select_from(JobProfile)

    if industry:
        query = query.where(JobProfile.industry == industry)
        count_query = count_query.where(JobProfile.industry == industry)
    if level:
        query = query.where(JobProfile.level == level)
        count_query = count_query.where(JobProfile.level == level)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(JobProfile.title.ilike(pattern))
        count_query = count_query.where(JobProfile.title.ilike(pattern))

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(JobProfile.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    jobs = result.scalars().all()

    return JobProfileListResponse(
        total=total,
        items=[JobProfileResponse.model_validate(j) for j in jobs],
    )


@router.get("/{job_id}", response_model=JobProfileResponse)
async def get_job(
    job_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Public single job profile for students."""
    job = await db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job profile not found")
    return job
