from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.core.matching import embed_job
from app.domain.models.company import Company
from app.domain.models.job import JobProfile
from app.domain.models.job_company_link import JobCompanyLink
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    JobCompanyLinkInfo,
    JobProfileCreate,
    JobProfileDetail,
    JobProfileListResponse,
    JobProfileResponse,
    JobProfileUpdate,
)

router = APIRouter()


async def _company_names(db: AsyncSession, jobs: list[JobProfile]) -> dict[int, str]:
    """给当前页的岗位批量补 company_name（一次查询，不做 N+1）。"""
    company_ids = {j.company_id for j in jobs if j.company_id is not None}
    if not company_ids:
        return {}
    rows = await db.execute(select(Company.id, Company.name).where(Company.id.in_(company_ids)))
    return {row[0]: row[1] for row in rows.all()}


async def _company_counts(db: AsyncSession, job_ids: list[int]) -> dict[int, int]:
    """给当前页岗位批量补「有多少家公司在招」（B2-5，一次查询，无 N+1）。"""
    if not job_ids:
        return {}
    rows = await db.execute(
        select(JobCompanyLink.job_profile_id, func.count())
        .where(JobCompanyLink.job_profile_id.in_(job_ids))
        .group_by(JobCompanyLink.job_profile_id)
    )
    return {row[0]: row[1] for row in rows.all()}


def _job_response(
    job: JobProfile, company_name: str | None = None, company_count: int = 0
) -> JobProfileResponse:
    data = JobProfileResponse.model_validate(job)
    data.company_name = company_name
    data.company_count = company_count
    return data


@router.get("", response_model=JobProfileListResponse)
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    industry: str | None = None,
    level: str | None = None,
    company_id: int | None = Query(None, description="按公司实体筛选（B2-5：走关联表）"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List job profiles with optional filtering."""
    query = select(JobProfile)
    count_query = select(func.count()).select_from(JobProfile)

    if industry:
        query = query.where(JobProfile.industry == industry)
        count_query = count_query.where(JobProfile.industry == industry)
    if level:
        query = query.where(JobProfile.level == level)
        count_query = count_query.where(JobProfile.level == level)
    if company_id is not None:
        # 走关联表：即便该岗位的"主公司"是别家，只要这家也在招就应命中
        linked = select(JobCompanyLink.job_profile_id).where(
            JobCompanyLink.company_id == company_id
        )
        query = query.where(JobProfile.id.in_(linked))
        count_query = count_query.where(JobProfile.id.in_(linked))

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(JobProfile.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    jobs = list(result.scalars().all())
    names = await _company_names(db, jobs)
    counts = await _company_counts(db, [j.id for j in jobs])

    return JobProfileListResponse(
        total=total,
        items=[_job_response(j, names.get(j.company_id), counts.get(j.id, 0)) for j in jobs],
    )


@router.get("/{job_id}", response_model=JobProfileDetail)
async def get_job(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """岗位详情：含「在招公司」清单（B2-5）。"""
    job = await db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job profile not found")

    rows = (
        await db.execute(
            select(JobCompanyLink, Company)
            .join(Company, Company.id == JobCompanyLink.company_id)
            .where(JobCompanyLink.job_profile_id == job_id)
            .order_by(JobCompanyLink.first_seen_at.asc(), JobCompanyLink.id.asc())
        )
    ).all()

    primary_name = next((c.name for link, c in rows if link.company_id == job.company_id), None)
    if primary_name is None:
        names = await _company_names(db, [job])
        primary_name = names.get(job.company_id)

    detail = JobProfileDetail.model_validate(job)
    detail.company_name = primary_name
    detail.company_count = len(rows)
    detail.companies = [
        JobCompanyLinkInfo(
            company_id=company.id,
            company_name=company.name,
            industry=company.industry,
            city=company.city,
            hit_count=link.hit_count,
            last_seen_at=link.last_seen_at,
            is_primary=(company.id == job.company_id),
        )
        for link, company in rows
    ]
    return detail


@router.post("", response_model=JobProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobProfileCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new job profile."""
    job = JobProfile(**data.model_dump())
    db.add(job)
    await db.flush()
    await db.refresh(job)

    # Generate embedding for the new job
    await embed_job(job.id, session=db)

    return job


@router.put("/{job_id}", response_model=JobProfileResponse)
async def update_job(
    job_id: int,
    data: JobProfileUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a job profile."""
    job = await db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job profile not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)

    await db.flush()
    await db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a job profile."""
    job = await db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job profile not found")

    await db.delete(job)
    await db.flush()


@router.post("/{job_id}/re-embed", response_model=JobProfileResponse)
async def re_embed_job(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate embedding for a job profile."""
    job = await db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job profile not found")

    await embed_job(job.id, session=db)
    await db.refresh(job)
    return job
