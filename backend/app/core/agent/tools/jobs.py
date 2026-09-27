"""岗位只读工具（P4 / C2）：`job_search` / `job_detail` —— **0 LLM 调用**。

定位
----
- **L1 工作流**（`core/chat/workflows.py`）负责"有哪些岗位 / 岗位大类分布"这类**固定问法**，
  命中即 0 token 直接答；
- 本模块负责**带条件的检索**与**单个岗位的细节** —— 这些问题的条件是模型从自然语言里
  抽出来的，L1 的关键词规则覆盖不了，所以交给 agent 调工具。

两个工具都**只查库**（不发网络、不调模型），符合 C2 的硬要求。

筛选语义**不在这里实现**：统一走 `domain/services/job_query_service`，
与管理端岗位列表共用同一套（含 `coalesce(关联行地域, 公司地域)` 的地域口径）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from loguru import logger

from app.domain.models.job import JobProfile
from app.domain.services.job_query_service import (
    DEFAULT_COMPANY_LIMIT,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    clamp_limit,
    job_company_rows,
    job_company_summaries,
    search_jobs,
)
from app.infrastructure.database import async_session_factory

#: 岗位「事实」字段（岗位信息，§21.1）——模型答问真正需要的部分
_FACT_FIELDS = (
    "id",
    "title",
    "industry",
    "level",
    "salary_range",
    "education_requirement",
    "experience_requirement",
)


def _facts(job: JobProfile) -> dict[str, Any]:
    return {field: getattr(job, field) for field in _FACT_FIELDS}


def compact_scores(raw: Any) -> dict[str, float] | None:
    """把画像里的「五维/六维」JSONB 压成 `{维度: 分数}`。

    ⚠️ **必须容错**：这两列的**形状在真实数据里不止一种**（§18 那次"岗位管理 500"
    就是只收 dict 造成的）。已知形态：
    `{"technical": {"score": 4, "key_skills": [...]}}` / `{"technical": 4}` /
    `{"technical": "4"}` / 字符串 / 数组。认不出的键直接跳过，绝不抛错。
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    for key, value in raw.items():
        score: Any = value
        if isinstance(value, dict):
            score = value.get("score")
        try:
            if score is None:
                continue
            out[str(key)] = float(score)
        except (TypeError, ValueError):
            continue
    return out or None


def _bounded(value: Any, limit: int = 5) -> Any:
    """列表类字段截断（模型不需要 50 条晋升路径，那只是白烧上下文）。"""
    if isinstance(value, list) and len(value) > limit:
        return value[:limit]
    return value


@tool
async def job_search(
    keyword: str | None = None,
    industry: str | None = None,
    level: str | None = None,
    region: str | None = None,
    city: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Search job profiles in the local database (pure DB read, no LLM cost).

    Use this when the user asks **which jobs exist** or wants jobs **filtered** by
    name/industry/level/location. Use `job_detail` instead when they ask about
    **one specific** job's full requirements.

    Args:
        keyword: 岗位名关键词（忽略大小写与空格，如「Java」「前端」）。
        industry: 行业，精确匹配（如「互联网」）。
        level: 级别，精确匹配（如「高级」「中级」）。
        region: 省份（如「广东」）。按**招聘所在地**筛选，关联行缺失时回落公司所在地。
        city: 城市（如「深圳」），口径同 `region`。
        limit: 最多返回几条（1..50，默认 10）。

    Returns:
        Dict: `{"total": 命中总数, "returned": 实际返回, "jobs": [...]}`。
        每条 job 含岗位事实字段 + `companies`（在招公司，最多 5 家，含省市/薪资）。
    """
    limit = clamp_limit(limit, default=DEFAULT_LIMIT, maximum=MAX_LIMIT)

    async with async_session_factory() as session:
        jobs, total = await search_jobs(
            session,
            keyword=keyword,
            industry=industry,
            level=level,
            region=region,
            city=city,
            limit=limit,
        )
        grouped = await job_company_summaries(session, [job.id for job in jobs])

    logger.info(
        "job_search | keyword={!r} industry={!r} level={!r} region={!r} city={!r} "
        "| total={} returned={}",
        keyword,
        industry,
        level,
        region,
        city,
        total,
        len(jobs),
    )

    if total == 0:
        return {
            "total": 0,
            "returned": 0,
            "jobs": [],
            "note": "库里没有符合条件的岗位（也可能还没有导入任何岗位数据）",
        }

    return {
        "total": total,
        "returned": len(jobs),
        "jobs": [
            {**_facts(job), "companies": grouped.get(job.id, [])}
            for job in jobs
        ],
    }


@tool
async def job_detail(job_id: int | None = None, title: str | None = None) -> dict:
    """Get **one** job's full profile: requirements, skills, career path, outlook.

    Use this after `job_search` when the user wants the details of a specific job.
    Provide `job_id` (preferred, exact) or `title` (matched after normalisation:
    case/whitespace-insensitive).

    Args:
        job_id: 岗位 id（优先）。
        title: 岗位名（忽略大小写与空格；同名唯一，所以能唯一定位）。

    Returns:
        Dict: `{"found": True, "job": {...}}` 或 `{"found": False, ...}`。
    """
    if job_id is None and not title:
        return {"found": False, "error": "需要 job_id 或 title 其中之一"}

    async with async_session_factory() as session:
        job: JobProfile | None = None
        if job_id is not None:
            job = await session.get(JobProfile, job_id)
        if job is None and title:
            # 先按归一化后的**精确**键找（唯一索引就是它），找不到再退回模糊
            jobs, _ = await search_jobs(session, keyword=title, limit=1)
            job = jobs[0] if jobs else None
        if job is None:
            logger.info("job_detail | not found | job_id={} title={!r}", job_id, title)
            return {
                "found": False,
                "error": f"没有找到岗位（job_id={job_id!r}, title={title!r}）",
            }

        rows = await job_company_rows(session, job.id)

        # 在招公司：地域/薪资优先用**这次招聘**的值，缺失才回落公司属性（与详情页一致）
        companies = [
            {
                "company_id": company.id,
                "company_name": company.name,
                "industry": company.industry,
                "scale": company.scale,
                "region": link.region or company.region,
                "city": link.city or company.city,
                "salary": link.salary,
                "source_url": link.source_url,
                "hit_count": link.hit_count,
            }
            for link, company in rows[:DEFAULT_COMPANY_LIMIT]
        ]

        payload = {
            **_facts(job),
            # 岗位信息（确定性解析出来的「事实」，§21.1）
            "hard_skills": _bounded(job.hard_skills),
            "soft_skills": _bounded(job.soft_skills),
            "career_path": _bounded(job.career_path),
            "transition_paths": _bounded(job.transition_paths),
            "certificates": _bounded(job.certificates),
            # 岗位画像（模型精提，服务人岗匹配）
            "summary": job.summary,
            # ⚠️ 叫 `portrait_dimensions` 而不是 `dimension_scores`：这是**画像自己的五维**
            # （technical/experience/…，存在 `requirement_intensity`）；
            # 人岗匹配用的**六维**是另一套口径（`DimensionScore` 的 `job` 行），
            # 计划 P5 正要先定那套口径 —— 现在混着叫会把两套数字混为一谈。
            "portrait_dimensions": compact_scores(job.requirement_intensity),
            "outlook": job.outlook,
            "companies": companies,
            "company_count": len({company.id for _link, company in rows}),
        }

    logger.info(
        "job_detail | job_id={} | companies={} | has_summary={}",
        payload["id"],
        len(companies),
        bool(payload["summary"]),
    )
    return {"found": True, "job": payload}


__all__ = ["compact_scores", "job_detail", "job_search"]
