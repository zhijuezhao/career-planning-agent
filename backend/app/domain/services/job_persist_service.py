"""岗位落库服务（B2-2 / B2-5）：`db_writer` 工具与导入流水线共用的 upsert 逻辑。

拆分原因：原 `db_writer._write_profile` 把「开 session + 业务 upsert」揉在一起，
导入流水线要落库时只能复制一份；现在业务逻辑集中在这里，两处调用同一实现。

合并原则与 §4.3 一致：调用方负责把「表格清洗值」放在最后合并（表格值优先），
本层只负责**空值不覆盖已有值**（`_pick`）。

B2-5：upsert 岗位画像时同时写 `job_company_links`（岗位 ↔ 公司 多对多）。
`job_profiles.company_id` 只记「主公司」，且**首次为准不再漂移** ——
否则「同一岗位名、不同公司」的第二条会把第一条的公司覆盖掉（旧实现的数据缺陷）。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.job import JobProfile, JobRawData
from app.domain.services.company_service import (
    link_job_company,
    refresh_job_count,
    upsert_company,
)

_EMPTY = (None, "", [], {})


def _pick(data: dict, key: str, current):
    """取新值；空值视为「本次没提供」，保留原值（避免导入缺列把已有画像抹平）。"""
    value = data.get(key)
    return current if value in _EMPTY else value


async def write_raw_job(session: AsyncSession, data: dict) -> JobRawData:
    """写入一条原始岗位数据（job_raw_data）。"""
    row = JobRawData(
        title=str(data.get("title") or "").strip()[:200],
        company=data.get("company"),
        city=data.get("city"),
        salary=data.get("salary"),
        industry=data.get("industry"),
        description=data.get("description"),
        requirements=data.get("requirements"),
        source=data.get("source", "import"),
        is_active=data.get("is_active", True),
    )
    session.add(row)
    await session.flush()
    return row


async def upsert_job_profile(session: AsyncSession, data: dict) -> tuple[JobProfile, bool]:
    """按 title 去重 upsert 岗位画像；顺带 upsert 公司、写「岗位↔公司」关联。

    返回 (profile, created)。title 为空抛 ValueError（调用方按行容错）。

    公司归属（B2-5）：
    - `job_company_links` 记录**全部**在招公司（同一岗位可被多家公司招）；
    - `job_profiles.company_id` 只记「主公司」，**首次为准**，后续导入不再覆盖
      （旧实现每行都覆盖，导致"同一岗位名、不同公司"时公司归属漂移且旧公司计数陈旧）。
    """
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    title = title[:200]

    company = await upsert_company(
        session, data.get("company"), industry=data.get("industry"), city=data.get("city")
    )

    existing = (
        await session.execute(select(JobProfile).where(JobProfile.title == title).limit(1))
    ).scalar_one_or_none()

    five_dim = data.get("five_dimensions") or {}
    outlook = data.get("outlook") or {}
    career_paths = data.get("career_paths") or []
    transition_roles = data.get("transition_roles") or []

    if existing is not None:
        existing.industry = _pick(data, "industry", existing.industry)
        existing.level = _pick(data, "level", existing.level)
        existing.hard_skills = _pick(data, "hard_skills", existing.hard_skills)
        existing.soft_skills = _pick(data, "soft_skills", existing.soft_skills)
        existing.salary_range = _pick(data, "salary", existing.salary_range)
        existing.education_requirement = _pick(
            data, "education_requirement", existing.education_requirement
        )
        existing.experience_requirement = _pick(
            data, "experience_requirement", existing.experience_requirement
        )
        existing.career_path = _pick(data, "career_paths", existing.career_path)
        existing.transition_paths = _pick(data, "transition_roles", existing.transition_paths)
        existing.requirement_intensity = _pick(data, "five_dimensions", existing.requirement_intensity)
        existing.outlook = _pick(data, "outlook", existing.outlook)
        existing.summary = _pick(data, "summary", existing.summary)
        if company is not None and existing.company_id is None:
            # 主公司只在为空时落定，避免"同岗多公司"互相覆盖
            existing.company_id = company.id
        profile, created = existing, False
    else:
        profile = JobProfile(
            title=title,
            industry=data.get("industry"),
            level=data.get("level"),
            hard_skills=data.get("hard_skills"),
            soft_skills=data.get("soft_skills"),
            salary_range=data.get("salary"),
            education_requirement=data.get("education_requirement"),
            experience_requirement=data.get("experience_requirement"),
            career_path=career_paths or None,
            transition_paths=transition_roles or None,
            requirement_intensity=five_dim or None,
            outlook=outlook or None,
            summary=data.get("summary"),
            company_id=company.id if company is not None else None,
        )
        session.add(profile)
        created = True

    await session.flush()

    if company is not None:
        # 关联表是「岗位 ↔ 公司」的真相来源；计数按它重算
        await link_job_company(
            session,
            job_profile_id=profile.id,
            company_id=company.id,
            source=str(data.get("source") or "import")[:20],
        )
        await refresh_job_count(session, company.id)
    return profile, created


async def persist_import_rows(
    session: AsyncSession,
    rows: list[dict],
    *,
    rejected_rows: list[dict] | None = None,
    source: str = "import",
) -> dict:
    """批量落库导入行：每行 job_raw_data + job_profiles(+companies)。

    **单行失败不影响其他行**（用 SAVEPOINT 包住每一行）：导入是批量场景，
    一行脏数据不该让整单退回。返回统计，可直接写进 `data_import_jobs.stats`。

    `rejected_rows`（质检 D 级）：只写 `job_raw_data`，标记 `source="import:rejected"`、
    `is_active=False`，**不生成画像** —— 目的是"不丢数据"，以后可离线重加工，
    不必让用户重新上传（2026-09-26 实测：84 条里 81 条被判 D，此前在库里毫无痕迹）。
    """
    stats: dict = {
        "raw_written": 0,
        "raw_written_rejected": 0,
        "profiles_new": 0,
        "profiles_updated": 0,
        "failed": 0,
        "errors": [],
    }

    for row in rows:
        try:
            async with session.begin_nested():  # 行级 SAVEPOINT
                await write_raw_job(session, {**row, "source": source})
                _profile, created = await upsert_job_profile(session, row)
            # 计数放在 savepoint 正常退出之后：行内失败时计数不应虚增
            stats["raw_written"] += 1
            stats["profiles_new" if created else "profiles_updated"] += 1
        except Exception as exc:  # noqa: BLE001 - 行级容错
            stats["failed"] += 1
            if len(stats["errors"]) < 5:
                title = row.get("title") or "未知岗位"
                stats["errors"].append(f"{title}：{exc}"[:200])
            logger.warning("导入行落库失败 | title={!r} | error={}", row.get("title"), exc)

    for row in rejected_rows or []:
        try:
            async with session.begin_nested():
                await write_raw_job(
                    session,
                    {**row, "source": f"{source}:rejected", "is_active": False},
                )
            stats["raw_written_rejected"] += 1
        except Exception as exc:  # noqa: BLE001 - 行级容错
            stats["failed"] += 1
            if len(stats["errors"]) < 5:
                title = row.get("title") or "未知岗位"
                stats["errors"].append(f"{title}（D级原始行）：{exc}"[:200])
            logger.warning("D 级原始行落库失败 | title={!r} | error={}", row.get("title"), exc)

    return stats


__all__ = ["persist_import_rows", "upsert_job_profile", "write_raw_job"]
