"""公司实体管理（B2-2 / B2-5 / 任务 4，需求 3）：公司信息导航。

- 数据来源：导入流水线 persist 阶段 / `db_writer` 工具 / 管理端手工建岗位时
  由 `company_service.upsert_company()` 幂等 upsert；
  **没有"新建公司"接口**：公司是导入的副产品，管理端只做人工修正（`PUT`）。
- 岗位↔公司是**多对多**（`job_company_links`，B2-5）：一个岗位可被多家公司招，
  一家公司也可招多个岗位。`job_count` 是冗余列，由关联表重算；
- `POST /companies/sync`：全量重算 `job_count`（**只重算，不回填** —— 回填的源列
  `job_profiles.company_id` 已在任务 3 删除）；
- `GET /companies/geo-options`（任务 4）：省 → 市级联筛选的数据源（公司所在地）；
- 删除公司**不会删岗位**：关联行随公司级联删除，岗位本身保留。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.company import Company
from app.domain.models.job import JobProfile
from app.domain.models.job_company_link import JobCompanyLink
from app.domain.models.user import User
from app.domain.services.company_service import (
    aggregate_geo_options,
    normalise_geo_name,
    sync_all_job_counts,
)
from app.infrastructure.database import get_db
from app.schemas.admin import (
    CompanyDetail,
    CompanyJobSummary,
    CompanyListResponse,
    CompanyResponse,
    CompanySyncResponse,
    CompanyUpdate,
    GeoOptionsResponse,
)

router = APIRouter()

DETAIL_JOB_LIMIT = 50


@router.get("", response_model=CompanyListResponse)
async def list_companies(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, description="按公司名模糊搜索"),
    industry: str | None = None,
    region: str | None = Query(None, description="按公司所在省筛选（任务 4；配合 city 做省→市级联）"),
    city: str | None = None,
    only_with_jobs: bool = Query(False, description="只看有岗位的公司"),
    sort: str = Query("job_count", pattern="^(job_count|name|created_at)$"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """公司列表（默认按岗位数倒序，便于「公司导航」先看到主要雇主）。"""
    conditions = []
    if q:
        conditions.append(Company.name.ilike(f"%{q}%"))
    if industry:
        conditions.append(Company.industry == industry)
    if region:
        # 省与市各自独立筛选：前端是"选中省后把市的选项收敛一下"，不是强制成对（任务 4）
        conditions.append(Company.region == region)
    if city:
        conditions.append(Company.city == city)
    if only_with_jobs:
        conditions.append(Company.job_count > 0)

    query = select(Company)
    count_query = select(func.count()).select_from(Company)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar() or 0

    order = {
        "job_count": (Company.job_count.desc(), Company.name.asc()),
        "name": (Company.name.asc(),),
        "created_at": (Company.created_at.desc(),),
    }[sort]
    query = query.order_by(*order).offset(skip).limit(limit)
    items = list((await db.execute(query)).scalars().all())

    return CompanyListResponse(
        total=total, items=[CompanyResponse.model_validate(c) for c in items]
    )


# ⚠️ 必须声明在 `/{company_id}` **之前**：否则 "geo-options" 会先被那条
# `company_id: int` 的路径吃掉，返回 422 而不是命中这里。
@router.get("/geo-options", response_model=GeoOptionsResponse)
async def company_geo_options(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """省 → 市级联下拉的选项（**公司所在地**口径，任务 4）。

    数据来源是 `companies.region / city` 的 distinct 值 —— 不做任何硬编码省份表，
    也不编造库里没有的地域（空库 → 三个空值，前端空着显示）。
    """
    rows = (
        await db.execute(select(Company.region, Company.city).distinct())
    ).all()
    return GeoOptionsResponse(**aggregate_geo_options(rows))


@router.get("/{company_id}", response_model=CompanyDetail)
async def get_company(
    company_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """公司详情 + 该公司最近岗位（最多 50 条，够导航用；更多请用岗位页按公司筛选）。"""
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    jobs = list(
        (
            await db.execute(
                select(JobProfile)
                .join(JobCompanyLink, JobCompanyLink.job_profile_id == JobProfile.id)
                .where(JobCompanyLink.company_id == company_id)
                .order_by(JobProfile.id.desc())
                .limit(DETAIL_JOB_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    detail = CompanyDetail.model_validate(company)
    detail.jobs = [
        CompanyJobSummary(
            id=j.id,
            title=j.title,
            industry=j.industry,
            level=j.level,
            salary_range=j.salary_range,
            created_at=j.created_at,
        )
        for j in jobs
    ]
    return detail


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: int,
    data: CompanyUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """人工修正公司名/行业/规模/省/市（导入自动识别的值可能不准）。

    `CompanyUpdate` 全部字段可选，不传=不改（`exclude_unset`）→ 前端只想改规模时
    不必把其余字段回传，也就不会误清空。
    """
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    fields = data.model_dump(exclude_unset=True)
    new_name = fields.get("name")
    if new_name and new_name != company.name:
        dup = (
            await db.execute(select(Company).where(Company.name == new_name))
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(status_code=409, detail="Another company already uses this name")

    for field, value in fields.items():
        # 省/市归一化为**短名**（与级联下拉同一套写法）：否则管理端手输「广东省」
        # 存进去后，下拉给出的却是「广东」→ 该行永远筛不到。
        if field in ("region", "city"):
            value = normalise_geo_name(value)
        setattr(company, field, value)

    await db.flush()
    await db.refresh(company)
    return CompanyResponse.model_validate(company)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    company_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除公司行（岗位不受影响：关联行随公司级联删除，岗位本身保留）。"""
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    await db.delete(company)
    await db.flush()


@router.post("/sync", response_model=CompanySyncResponse)
async def sync_companies(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """修数口子：按关联表全量重算 `job_count`。

    2026-09-27 任务 2 起，「谁在招谁」的唯一真相就是 `job_company_links`，
    任务 3 又把 `job_profiles.company_id` 列本身删掉了 → 原先那个"把 `company_id`
    回填进关联表"的步骤已无对象可回填，故移除（`links_created` 恒为 0，仅为兼容旧前端保留字段）。
    """
    synced = await sync_all_job_counts(db)
    await db.flush()
    with_jobs = (
        await db.execute(select(func.count()).select_from(Company).where(Company.job_count > 0))
    ).scalar() or 0
    return CompanySyncResponse(synced=synced, with_jobs=with_jobs, links_created=0)


__all__ = ["router"]
