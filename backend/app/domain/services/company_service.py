"""公司实体服务（B2-2）：按名称幂等 upsert + 岗位数同步。

为什么单独一层：公司既可能来自导入流水线（`persist` 阶段）、也可能来自
`db_writer` 工具调用或管理端手工建岗位，三处必须用**同一套**归一化与 upsert 规则，
否则同一个公司会被拆成多行（"ABC 科技" vs "ABC科技" 之类）。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.company import Company
from app.domain.models.job import JobProfile

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


async def refresh_job_count(session: AsyncSession, company_id: int) -> int:
    """按 job_profiles 实际关联重算并回写 job_count（冗余列的真相来源）。"""
    count = (
        await session.execute(
            select(func.count()).select_from(JobProfile).where(JobProfile.company_id == company_id)
        )
    ).scalar() or 0
    company = await session.get(Company, company_id)
    if company is not None and company.job_count != count:
        company.job_count = count
    return count


async def sync_all_job_counts(session: AsyncSession) -> int:
    """全量重算所有公司的 job_count（修数 / 人工改过 company_id 后用）。"""
    companies = list((await session.execute(select(Company))).scalars().all())
    for company in companies:
        await refresh_job_count(session, company.id)
    return len(companies)


__all__ = ["normalise_company_name", "refresh_job_count", "sync_all_job_counts", "upsert_company"]
