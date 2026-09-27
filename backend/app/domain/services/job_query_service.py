"""岗位**只读查询**服务（P4 / C2）：管理端列表与 chat 工具共用同一套筛选语义。

为什么单独一层
--------------
「按公司/地域筛岗位」的语义在管理端列表、级联选项（`geo-options`）、岗位详情的
「在招公司」展示三处必须**逐字一致**（2026-09-27 任务 4 定的约束），否则会出现
"筛得到却看不到"。P4 又要给 chat 加 `job_search` —— 如果再在工具里抄一遍
`coalesce(关联行地域, 公司地域)`，就变成四份拷贝、必然漂移。
所以把查询与聚合收敛到这里，两边都调它。

本模块**只读**：不写库、不发网络、不调模型（C2 的硬要求：0 LLM 调用）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dedup_keys import normalise_title
from app.core.dimensions.rubrics import DIMENSION_ORDER
from app.domain.models.company import Company
from app.domain.models.job import JobProfile
from app.domain.models.job_company_link import JobCompanyLink

#: 默认/上限条数（工具与管理端都用，避免让模型一次拉爆上下文）
DEFAULT_LIMIT = 10
MAX_LIMIT = 50

#: 岗位详情回给模型的「在招公司」最多几条
DEFAULT_COMPANY_LIMIT = 5


def clamp_limit(raw: Any, *, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    """把入参收敛成合法条数（脏输入不抛错，退回默认值）。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


def _linked_job_ids(
    *,
    company_id: int | None = None,
    region: str | None = None,
    city: str | None = None,
) -> Select:
    """「按**关联表**筛出的 job_profile_id」子查询。

    - `company_id`：只要这家公司在招就命中；
    - `region` / `city`：`coalesce(关联行地域, 公司地域)` —— 关联行自带的地域优先
      （"这次招聘在哪儿"），缺失才回落到公司所在地。**与详情展示、级联选项同源。**
    """
    stmt = select(JobCompanyLink.job_profile_id).join(
        Company, Company.id == JobCompanyLink.company_id
    )
    if company_id is not None:
        stmt = stmt.where(JobCompanyLink.company_id == company_id)
    if region:
        stmt = stmt.where(func.coalesce(JobCompanyLink.region, Company.region) == region)
    if city:
        stmt = stmt.where(func.coalesce(JobCompanyLink.city, Company.city) == city)
    return stmt


def build_filters(
    *,
    keyword: str | None = None,
    industry: str | None = None,
    level: str | None = None,
    company_id: int | None = None,
    region: str | None = None,
    city: str | None = None,
) -> list[Any]:
    """把查询参数翻成 `WHERE` 条件（管理端与工具共用，语义只有这一处）。"""
    filters: list[Any] = []
    if keyword:
        # 岗位名模糊匹配走 `title_key`（生成列：已折叠空白 + 转小写）——
        # 与落库唯一键同一套归一化，所以"Java"/"java"/"java  "都能命中同一条。
        # `autoescape=True`：把用户输入里的 % / _ 当普通字符，不让它变成 LIKE 通配符。
        filters.append(JobProfile.title_key.contains(normalise_title(keyword), autoescape=True))
    if industry:
        filters.append(JobProfile.industry == industry)
    if level:
        filters.append(JobProfile.level == level)
    if company_id is not None or region or city:
        filters.append(
            JobProfile.id.in_(_linked_job_ids(company_id=company_id, region=region, city=city))
        )
    return filters


async def search_jobs(
    session: AsyncSession,
    *,
    keyword: str | None = None,
    industry: str | None = None,
    level: str | None = None,
    company_id: int | None = None,
    region: str | None = None,
    city: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    order_desc: bool = True,
) -> tuple[list[JobProfile], int]:
    """按条件查岗位，返回 `(当前页岗位, 命中总数)`。"""
    filters = build_filters(
        keyword=keyword,
        industry=industry,
        level=level,
        company_id=company_id,
        region=region,
        city=city,
    )

    count_stmt = select(func.count()).select_from(JobProfile)
    stmt = select(JobProfile)
    for condition in filters:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = (await session.execute(count_stmt)).scalar() or 0
    order = JobProfile.id.desc() if order_desc else JobProfile.id.asc()
    stmt = stmt.order_by(order).offset(max(0, offset)).limit(limit)
    jobs = list((await session.execute(stmt)).scalars().all())
    return jobs, total


async def company_names(session: AsyncSession, jobs: Sequence[JobProfile]) -> dict[int, str]:
    """给一批岗位补「在招公司」的**展示名**（一次查询，不做 N+1）。

    多对多下取**最早建立关联**的那家作为展示名，完整清单走岗位详情。
    """
    ids = [job.id for job in jobs]
    if not ids:
        return {}
    rows = (
        await session.execute(
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


async def company_counts(session: AsyncSession, jobs: Sequence[JobProfile]) -> dict[int, int]:
    """给一批岗位补「有多少家公司在招」（一次查询，无 N+1）。"""
    ids = [job.id for job in jobs]
    if not ids:
        return {}
    rows = await session.execute(
        select(
            JobCompanyLink.job_profile_id,
            func.count(func.distinct(JobCompanyLink.company_id)),
        )
        .where(JobCompanyLink.job_profile_id.in_(ids))
        .group_by(JobCompanyLink.job_profile_id)
    )
    return {row[0]: row[1] for row in rows.all()}


async def job_company_rows(
    session: AsyncSession, job_id: int
) -> list[tuple[JobCompanyLink, Company]]:
    """一个岗位的「在招公司」明细（关联行 + 公司），**最早关联在前**。"""
    rows = (
        await session.execute(
            select(JobCompanyLink, Company)
            .join(Company, Company.id == JobCompanyLink.company_id)
            .where(JobCompanyLink.job_profile_id == job_id)
            .order_by(JobCompanyLink.id.asc())
        )
    ).all()
    return [(link, company) for link, company in rows]


async def job_company_summaries(
    session: AsyncSession,
    job_ids: Sequence[int],
    *,
    per_job_limit: int = DEFAULT_COMPANY_LIMIT,
) -> dict[int, list[dict[str, Any]]]:
    """一批岗位各自的「在招公司」摘要（给 chat 工具用，条数有上限）。

    地域口径与展示/筛选一致：**关联行优先，缺失回落公司**。
    """
    ids = list(job_ids)
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(JobCompanyLink, Company)
            .join(Company, Company.id == JobCompanyLink.company_id)
            .where(JobCompanyLink.job_profile_id.in_(ids))
            .order_by(JobCompanyLink.job_profile_id.asc(), JobCompanyLink.id.asc())
        )
    ).all()

    grouped: dict[int, list[dict[str, Any]]] = {}
    for link, company in rows:
        bucket = grouped.setdefault(link.job_profile_id, [])
        if len(bucket) >= per_job_limit:
            continue
        bucket.append(
            {
                "company_id": company.id,
                "company_name": company.name,
                "industry": company.industry,
                "scale": company.scale,
                # 关联行优先（"这次招聘在哪儿/给多少"），缺失才回落到公司属性
                "region": link.region or company.region,
                "city": link.city or company.city,
                "salary": link.salary,
                "source_url": link.source_url,
            }
        )
    return grouped


# ── 岗位侧六维（画像 → 匹配用的 {维度: 分数}）────────────────────────────────────
# 2026-09-27 P5：岗位侧的维度**唯一真相是画像**（`job_profiles.requirement_intensity`）。
# 此前匹配读的是 `dimension_scores` 表里 `profile_type='job'` 的行，而**全仓没有任何地方
# 写那种行**（唯一的写入者写的是 `candidate`）→ 岗位侧恒为 `{}`，六维对比实际全是 0。


def extract_job_dimensions(portrait: object) -> dict[str, float]:
    """从岗位画像里取出**六维分数** `{维度: 分数}`（形状容错）。

    - 只认**六维规范名**（`DIMENSION_ORDER`）。**刻意不做**「英文五维(technical/…) → 中文六维」
      的映射：两套维度的含义并不一一对应（职业匹配度/成长潜力在旧五维里没有对应项），
      硬映射就是**编数据**（用户 2026-09-27 明确否掉了那个方案）；
    - 形状容错（真实数据的 JSONB 形状不止一种，§18 的教训）：
      `{维度: {"score": 4, "key_skills": [...]}}` / `{维度: 4}` / `{维度: "4"}`；
    - **缺的维度不补 0**：不返回 = 没有可比数据，让调用方如实说"不可比"，
      而不是拿 0 去参与 `min(学生/岗位)` 算出"完全不匹配"这种假结论。
    """
    if not isinstance(portrait, dict):
        return {}
    out: dict[str, float] = {}
    for dim in DIMENSION_ORDER:
        value = portrait.get(dim)
        score: Any = value
        if isinstance(value, dict):
            score = value.get("score")
        if score is None:
            continue
        try:
            out[dim] = float(score)
        except (TypeError, ValueError):
            continue
    return out


async def job_dimension_scores(
    session: AsyncSession, job_profile_id: int
) -> dict[str, float]:
    """按岗位 id 取六维（读**画像**，不再读 `dimension_scores` 的 job 行）。"""
    portrait = (
        await session.execute(
            select(JobProfile.requirement_intensity).where(JobProfile.id == job_profile_id)
        )
    ).scalar_one_or_none()
    return extract_job_dimensions(portrait)


__all__ = [
    "DEFAULT_COMPANY_LIMIT",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "build_filters",
    "clamp_limit",
    "company_counts",
    "company_names",
    "extract_job_dimensions",
    "job_company_rows",
    "job_company_summaries",
    "job_dimension_scores",
    "search_jobs",
]
