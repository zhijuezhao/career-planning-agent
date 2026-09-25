"""公司实体服务（B2-2 / B2-5）：按名称幂等 upsert + 岗位↔公司关联 + 岗位数同步。

为什么单独一层：公司既可能来自导入流水线（`persist` 阶段）、也可能来自
`db_writer` 工具调用或管理端手工建岗位，三处必须用**同一套**归一化与 upsert 规则，
否则同一个公司会被拆成多行（"ABC 科技" vs "ABC科技" 之类）。

B2-5 起新增 `job_company_links`（岗位 ↔ 公司 多对多）：
- 「某家公司有多少岗位」= 该公司关联的**不同岗位**数（`count(distinct job_profile_id)`）；
- 「某个岗位有多少家公司在招」= 该岗位关联的**不同公司**数。
两个方向的计数都以关联表为真相来源，`companies.job_count` 只是它的冗余缓存。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.company import Company
from app.domain.models.job import JobProfile
from app.domain.models.job_company_link import JobCompanyLink

# 明显不是公司名的占位值（导入表里常见）
_PLACEHOLDERS = {"nan", "none", "null", "-", "--", "未知", "未提供", "保密", "不详"}


def normalise_company_name(name: str | None) -> str | None:
    """归一化公司名；无意义的值返回 None（宁可 company_id 为空，也不要脏公司行）。"""
    if name is None:
        return None
    text = " ".join(str(name).split()).strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return None
    return text[:200]


async def upsert_company(
    session: AsyncSession,
    name: str | None,
    *,
    industry: str | None = None,
    city: str | None = None,
) -> Company | None:
    """按 name 取公司，没有则建。

    industry / city **只在公司行为空时补全**：这两个字段允许管理端手工修正，
    后续导入不应把它们覆盖回去。
    """
    clean = normalise_company_name(name)
    if clean is None:
        return None

    company = (
        await session.execute(select(Company).where(Company.name == clean).limit(1))
    ).scalar_one_or_none()

    if company is None:
        company = Company(
            name=clean,
            industry=(industry or None),
            city=(city or None),
            job_count=0,
        )
        session.add(company)
        await session.flush()
        logger.info("公司表新增 | id={} | name={!r}", company.id, clean)
        return company

    if industry and not company.industry:
        company.industry = industry
    if city and not company.city:
        company.city = city
    return company


async def link_job_company(
    session: AsyncSession,
    *,
    job_profile_id: int,
    company_id: int,
    source: str = "import",
) -> JobCompanyLink:
    """建立/更新「岗位 ↔ 公司」关联（幂等；重复出现时累加 hit_count）。"""
    link = (
        await session.execute(
            select(JobCompanyLink).where(
                JobCompanyLink.job_profile_id == job_profile_id,
                JobCompanyLink.company_id == company_id,
            )
        )
    ).scalar_one_or_none()

    if link is None:
        link = JobCompanyLink(
            job_profile_id=job_profile_id,
            company_id=company_id,
            source=source,
            hit_count=1,
        )
        session.add(link)
        await session.flush()
        logger.info(
            "岗位↔公司关联新增 | job_profile_id={} | company_id={}", job_profile_id, company_id
        )
        return link

    link.hit_count += 1
    link.last_seen_at = func.now()
    return link


async def company_job_count(session: AsyncSession, company_id: int) -> int:
    """该公司在招的不同岗位数（以关联表为准）。"""
    return (
        await session.execute(
            select(func.count(func.distinct(JobCompanyLink.job_profile_id))).where(
                JobCompanyLink.company_id == company_id
            )
        )
    ).scalar() or 0


async def refresh_job_count(session: AsyncSession, company_id: int) -> int:
    """按关联表重算并回写 `companies.job_count`（冗余列的真相来源）。"""
    count = await company_job_count(session, company_id)
    company = await session.get(Company, company_id)
    if company is not None and company.job_count != count:
        company.job_count = count
    return count


async def backfill_links_from_profiles(session: AsyncSession) -> int:
    """把历史上只有 `job_profiles.company_id` 的关联补进关联表（幂等）。

    用于 B2-5 上线：早先导入的岗位只记了"主公司"，没有关联行 ——
    不补的话这两个查询会漏掉它们。
    """
    rows = (
        await session.execute(
            select(JobProfile.id, JobProfile.company_id).where(JobProfile.company_id.isnot(None))
        )
    ).all()

    existing = {
        (link.job_profile_id, link.company_id)
        for link in (await session.execute(select(JobCompanyLink))).scalars().all()
    }

    created = 0
    for job_profile_id, company_id in rows:
        if (job_profile_id, company_id) in existing:
            continue
        session.add(
            JobCompanyLink(
                job_profile_id=job_profile_id,
                company_id=company_id,
                source="backfill",
                hit_count=1,
            )
        )
        created += 1

    if created:
        await session.flush()
        logger.info("岗位↔公司关联回填 | created={}", created)
    return created


async def sync_all_job_counts(session: AsyncSession) -> int:
    """全量重算所有公司的 job_count（修数 / 人工改过关联后用）。"""
    companies = list((await session.execute(select(Company))).scalars().all())
    for company in companies:
        await refresh_job_count(session, company.id)
    return len(companies)


__all__ = [
    "backfill_links_from_profiles",
    "company_job_count",
    "link_job_company",
    "normalise_company_name",
    "refresh_job_count",
    "sync_all_job_counts",
    "upsert_company",
]
