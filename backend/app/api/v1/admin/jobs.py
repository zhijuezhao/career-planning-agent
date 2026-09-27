from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.core.dedup_keys import normalise_title
from app.core.matching import embed_job
from app.domain.models.company import Company
from app.domain.models.job import JobProfile
from app.domain.models.job_company_link import JobCompanyLink
from app.domain.models.user import User
from app.domain.models.vector import JobMatchEmbedding
from app.domain.services.company_service import refresh_job_count
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
    """给当前页岗位补「在招公司」的**展示名**（一次查询，不做 N+1）。

    岗位↔公司是**多对多**（2026-09-27 任务 2）→ 一个岗位可能有多家在招。列表里只展示
    **最早建立关联的那一家**作为展示名，完整清单走 `GET /admin/jobs/{id}` 的 `companies`。
    """
    ids = [job.id for job in jobs]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(JobCompanyLink.job_profile_id, Company.name)
            .join(Company, Company.id == JobCompanyLink.company_id)
            .where(JobCompanyLink.job_profile_id.in_(ids))
            .order_by(JobCompanyLink.job_profile_id.asc(), JobCompanyLink.id.asc())
        )
    ).all()
    names: dict[int, str] = {}
    for job_profile_id, name in rows:
        names.setdefault(job_profile_id, name)  # 第一条（最早）即展示名
    return names


async def _company_counts(db: AsyncSession, jobs: list[JobProfile]) -> dict[int, int]:
    """给当前页岗位批量补「有多少家公司在招」（B2-5，一次查询，无 N+1）。

    多对多模型下**直接数关联表**即可。P2 那套"按 `title_key` 汇总同名画像"的绕法
    （同名不同公司 = 多条画像）在 2026-09-27 任务 2 已废止 —— 现在同名只有一条岗位。
    """
    ids = [job.id for job in jobs]
    if not ids:
        return {}
    rows = await db.execute(
        select(
            JobCompanyLink.job_profile_id,
            func.count(func.distinct(JobCompanyLink.company_id)),
        )
        .where(JobCompanyLink.job_profile_id.in_(ids))
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
    counts = await _company_counts(db, jobs)

    return JobProfileListResponse(
        total=total,
        items=[_job_response(j, names.get(j.id), counts.get(j.id, 0)) for j in jobs],
    )


@router.get("/{job_id}", response_model=JobProfileDetail)
async def get_job(
    job_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """岗位详情：含「在招公司」清单。

    「谁在招这个岗位」的**唯一真相是 `job_company_links`**（2026-09-27 任务 2 起：
    岗位是角色级的、公司归属全在关联表）。每条关联 = 一次招聘，自带所在地/薪资/原始链接。
    """
    job = await db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job profile not found")

    rows = (
        await db.execute(
            select(JobCompanyLink, Company)
            .join(Company, Company.id == JobCompanyLink.company_id)
            .where(JobCompanyLink.job_profile_id == job.id)
            .order_by(JobCompanyLink.id.asc())
        )
    ).all()

    detail = JobProfileDetail.model_validate(job)
    # 多对多没有"主公司"概念了：展示名取**最早建立关联**的那家，完整清单在 companies 里
    detail.company_name = rows[0][1].name if rows else None
    detail.company_count = len({company.id for _link, company in rows})
    detail.companies = [
        JobCompanyLinkInfo(
            company_id=company.id,
            company_name=company.name,
            industry=company.industry,
            scale=company.scale,
            # 地域/薪资优先用**这次招聘**的值（岗位所在地），缺失才回落到公司属性
            region=link.region or company.region,
            city=link.city or company.city,
            salary=link.salary,
            source_url=link.source_url,
            hit_count=link.hit_count,
            last_seen_at=link.last_seen_at,
            is_primary=(index == 0),
        )
        for index, (link, company) in enumerate(rows)
    ]
    return detail


async def _assert_title_free(
    db: AsyncSession,
    *,
    title: str,
    exclude_id: int | None = None,
) -> None:
    """**岗位名唯一** —— 管理端手工建/改岗位时先查一次，撞了给 **409** 而不是 500。

    ⚠️ 2026-09-27 任务 2 起去重键**只有岗位名**（`title_key`，忽略大小写与空格）：
    岗位是**角色级**的，"同名不同公司"是关联表上的多条记录，不再落成多条岗位。
    并发下仍可能漏过这里，所以调用方还要兜 `IntegrityError`。
    """
    query = select(JobProfile.id).where(JobProfile.title_key == normalise_title(title))
    if exclude_id is not None:
        query = query.where(JobProfile.id != exclude_id)
    duplicate_id = (await db.execute(query.limit(1))).scalar_one_or_none()
    if duplicate_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"岗位已存在：同名（忽略大小写与空格）的岗位 id={duplicate_id}",
        )


@router.post("", response_model=JobProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: JobProfileCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new job profile."""
    # 管理端没有"公司"输入项：岗位是**角色级**的，去重键只有岗位名（2026-09-27 任务 2）
    await _assert_title_free(db, title=data.title)

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
        await _assert_title_free(
            db, title=str(update_data["title"]), exclude_id=job.id
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
    """Delete a job profile.

    **两个子表都要照顾到**，否则这里会 500、或者留下跟真实数据对不上的脏状态：

    - `job_match_embeddings.job_profile_id` 是 **NO ACTION** 外键（三张子表里只有
      它漏了 CASCADE），而 `create_job` 会调 `embed_job()` 写一行 → 有向量的岗位
      直接删就是 `ForeignKeyViolationError` → 500。所以先显式清子行。
    - `job_company_links` 是 CASCADE，行会自己消失，但 `companies.job_count` 这个
      **冗余列**不会跟着变（公司页按它排序 / `only_with_jobs` 过滤）→ 删完顺手
      把受影响的公司重算一遍，别让"在招岗位数"虚高。
    """
    job = await db.get(JobProfile, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job profile not found")

    # 受影响的公司必须在删之前记下来 —— 关联行下面就被 CASCADE 掉了。
    # （岗位是角色级的、公司归属全在关联表，所以只从这里取，不再看 `job_profiles.company_id`）
    affected_company_ids: set[int] = set(
        (
            await db.execute(
                select(JobCompanyLink.company_id).where(JobCompanyLink.job_profile_id == job_id)
            )
        )
        .scalars()
        .all()
    )

    # 子行必须先走：NO ACTION 外键不允许父行先删
    await db.execute(
        delete(JobMatchEmbedding).where(JobMatchEmbedding.job_profile_id == job_id)
    )

    await db.delete(job)
    await db.flush()

    # 关联行已经随 CASCADE 没了，这里把冗余计数追平
    for company_id in affected_company_ids:
        await refresh_job_count(db, company_id)


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
