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

from collections.abc import Iterable

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.company import Company
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
    region: str | None = None,
    scale: str | None = None,
) -> Company | None:
    """按 name 取公司，没有则建。

    industry / city / region / scale **只在公司行为空时补全**：这些字段允许管理端手工修正，
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
            region=(region or None),
            scale=(scale or None),
            job_count=0,
        )
        session.add(company)
        await session.flush()
        logger.info("公司表新增 | id={} | name={!r}", company.id, clean)
        return company

    for field, value in (
        ("industry", industry),
        ("city", city),
        ("region", region),
        ("scale", scale),
    ):
        if value and not getattr(company, field):
            setattr(company, field, value)
    return company


async def link_job_company(
    session: AsyncSession,
    *,
    job_profile_id: int,
    company_id: int,
    source: str = "import",
    region: str | None = None,
    city: str | None = None,
    salary: str | None = None,
    source_url: str | None = None,
) -> JobCompanyLink:
    """建立/更新「岗位 ↔ 公司」关联（幂等；重复出现时累加 hit_count）。

    这张表是「**谁在招谁**」的**唯一真相**（岗位↔公司 多对多）。每条关联 = **一次招聘**，
    所以招聘所在地（省/市）、薪资、原始链接挂在这里 —— 同一个岗位角色在不同公司在招时，
    这三项必然不同。

    取值策略：**非空的新值覆盖旧值**（表格是这次招聘的事实来源），空值不覆盖。
    """
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
            region=(region or None),
            city=(city or None),
            salary=(salary or None),
            source_url=(source_url or None),
        )
        session.add(link)
        await session.flush()
        logger.info(
            "岗位↔公司关联新增 | job_profile_id={} | company_id={}", job_profile_id, company_id
        )
        return link

    for field, value in (
        ("region", region),
        ("city", city),
        ("salary", salary),
        ("source_url", source_url),
    ):
        if value:
            setattr(link, field, value)
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


async def sync_all_job_counts(session: AsyncSession) -> int:
    """全量重算所有公司的 job_count（修数 / 人工改过关联后用）。"""
    companies = list((await session.execute(select(Company))).scalars().all())
    for company in companies:
        await refresh_job_count(session, company.id)
    return len(companies)


def aggregate_geo_options(pairs: Iterable[tuple[str | None, str | None]]) -> dict[str, object]:
    """把 `(省, 市)` 明细汇总成**省 → 市 级联下拉**要的三份数据（纯函数，无 IO）。

    返回 `{"regions": [...], "cities_by_region": {省: [市...]}, "all_cities": [...]}`，
    三份都是**排序去重**的（排序在前端表现为稳定的下拉顺序，省得前端再排一遍）。

    - `regions`：有省的 distinct 省；
    - `cities_by_region`：省 → 该省的市；
    - `all_cities`：全部市 —— 含"只写了市、没写省"的行，否则这些行在当前筛选器里
      **永远筛不到**（选中它们的省是做不到的，因为压根没有省）。

    ⚠️ 刻意**不编造**地域：库里没有就返回三个空值，由前端空着显示
    （`companies` / `job_company_links` 现在都还是 0 行，这条路径就是空库的真实形态）。

    放在服务层但**不 import schemas**：返回普通 dict，由接口侧包成 `GeoOptionsResponse`，
    免得领域层反向依赖接口契约。
    """
    regions: set[str] = set()
    cities_by_region: dict[str, set[str]] = {}
    all_cities: set[str] = set()

    for raw_region, raw_city in pairs:
        region = str(raw_region).strip() if raw_region is not None else ""
        city = str(raw_city).strip() if raw_city is not None else ""
        if region:
            regions.add(region)
        if city:
            all_cities.add(city)
            if region:
                cities_by_region.setdefault(region, set()).add(city)

    return {
        "regions": sorted(regions),
        "cities_by_region": {
            region: sorted(cities) for region, cities in sorted(cities_by_region.items())
        },
        "all_cities": sorted(all_cities),
    }


__all__ = [
    "aggregate_geo_options",
    "company_job_count",
    "link_job_company",
    "normalise_company_name",
    "refresh_job_count",
    "sync_all_job_counts",
    "upsert_company",
]
