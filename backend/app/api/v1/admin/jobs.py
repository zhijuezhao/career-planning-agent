from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.core.dedup_keys import normalise_title
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


async def _company_counts(db: AsyncSession, jobs: list[JobProfile]) -> dict[int, int]:
    """给当前页岗位批量补「有多少家公司在招」（B2-5，一次查询，无 N+1）。

    **P2 起口径变了**：岗位去重粒度是 `(岗位名, 公司)`，同一岗位名会被拆成多条画像
    （每家一条），所以"这个岗位有几家公司在招"不能再数单条画像的关联行（那永远是 1）。
    现在按 `title_key` **汇总同名画像的公司集合** —— 对使用者来说 B2-5 的能力没变，
    只是数据表示从"1 条画像 + N 条关联"变成"N 条画像"。
    """
    keys = {j.title_key for j in jobs if j.title_key}
    if not keys:
        return {}
    rows = await db.execute(
        select(JobProfile.title_key, func.count(func.distinct(JobProfile.company_id)))
        .where(JobProfile.title_key.in_(keys), JobProfile.company_id.isnot(None))
        .group_by(JobProfile.title_key)
    )
    by_key = {row[0]: row[1] for row in rows.all()}
    return {j.id: by_key.get(j.title_key, 0) for j in jobs}


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
    counts = await _company_counts(db, jobs)

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
    """岗位详情：含「在招公司」清单（B2-5；P2 起按 `title_key` 汇总同名画像）。"""
    job = await db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job profile not found")

    # P2：同一岗位名 × N 家公司 = N 条画像 —— 「在招公司」= 同名画像各自的公司。
    siblings = list(
        (
            await db.execute(
                select(JobProfile, Company)
                .join(Company, Company.id == JobProfile.company_id)
                .where(JobProfile.title_key == job.title_key)
                .order_by(JobProfile.id.asc())
            )
        ).all()
    )
    sibling_ids = [profile.id for profile, _ in siblings]
    link_rows = (
        (
            await db.execute(
                select(JobCompanyLink).where(JobCompanyLink.job_profile_id.in_(sibling_ids))
            )
        )
        .scalars()
        .all()
        if sibling_ids
        else []
    )
    # 命中次数/最近出现时间仍以关联表为准（B3 链接富化会累加它）
    links = {(link.job_profile_id, link.company_id): link for link in link_rows}

    primary_name = next(
        (company.name for profile, company in siblings if profile.id == job.id), None
    )
    if primary_name is None:
        names = await _company_names(db, [job])
        primary_name = names.get(job.company_id)

    detail = JobProfileDetail.model_validate(job)
    detail.company_name = primary_name
    detail.company_count = len({company.id for _profile, company in siblings})
    detail.companies = [
        JobCompanyLinkInfo(
            company_id=company.id,
            company_name=company.name,
            industry=company.industry,
            city=company.city,
            hit_count=links[(profile.id, company.id)].hit_count
            if (profile.id, company.id) in links
            else 1,
            last_seen_at=links[(profile.id, company.id)].last_seen_at
            if (profile.id, company.id) in links
            else None,
            is_primary=(company.id == job.company_id),
        )
        for profile, company in siblings
    ]
    return detail


async def _assert_title_company_free(
    db: AsyncSession,
    *,
    title: str,
    company_id: int | None,
    exclude_id: int | None = None,
) -> None:
    """P2：`(岗位名, 公司)` 唯一 —— 管理端手工建/改岗位时先查一次，撞了给 **409** 而不是 500。

    条件必须与唯一索引 `uq_job_profiles_title_company (title_key, company_id) NULLS NOT DISTINCT`
    **完全一致**：`company_id IS NULL` 只和 NULL 冲突（NULL 与非 NULL 在 PG 里仍是不同的键）。
    并发下仍可能漏过这里，所以调用方还要兜 `IntegrityError`。
    """
    condition = (
        JobProfile.company_id.is_(None)
        if company_id is None
        else JobProfile.company_id == company_id
    )
    query = select(JobProfile.id).where(JobProfile.title_key == normalise_title(title), condition)
    if exclude_id is not None:
        query = query.where(JobProfile.id != exclude_id)
    duplicate_id = (await db.execute(query.limit(1))).scalar_one_or_none()
    if duplicate_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"岗位已存在：同名（忽略大小写与空格）且同公司的岗位 id={duplicate_id}",
        )


@router.post("", response_model=JobProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobProfileCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new job profile."""
    # 管理端没有"公司"输入项 → 新岗位的 company_id 恒为 NULL，键就是 (title_key, NULL)
    await _assert_title_company_free(db, title=data.title, company_id=None)

    job = JobProfile(**data.model_dump())
    db.add(job)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="岗位已存在（同名同公司，并发写入）"
        ) from exc
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
    if "title" in update_data and update_data["title"]:
        # 改标题可能撞上另一条同键岗位 → 同样给 409（不然是 500）
        await _assert_title_company_free(
            db, title=str(update_data["title"]), company_id=job.company_id, exclude_id=job.id
        )
    for field, value in update_data.items():
        setattr(job, field, value)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="岗位已存在（同名同公司，并发写入）"
        ) from exc
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
