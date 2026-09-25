"""岗位落库服务（B2-2）：`db_writer` 工具与导入流水线共用的 upsert 逻辑。

拆分原因：原 `db_writer._write_profile` 把「开 session + 业务 upsert」揉在一起，
导入流水线要落库时只能复制一份；现在业务逻辑集中在这里，两处调用同一实现。

合并原则与 §4.3 一致：调用方负责把「表格清洗值」放在最后合并（表格值优先），
本层只负责**空值不覆盖已有值**（`_pick`）。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.job import JobProfile, JobRawData
from app.domain.services.company_service import refresh_job_count, upsert_company

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
    """按 title 去重 upsert 岗位画像；顺带 upsert 公司并挂上 `company_id`。

    返回 (profile, created)。title 为空抛 ValueError（调用方按行容错）。
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
        if company is not None:
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
        await refresh_job_count(session, company.id)
    return profile, created


async def persist_import_rows(session: AsyncSession, rows: list[dict], *, source: str = "import") -> dict:
    """批量落库导入行：每行 job_raw_data + job_profiles(+companies)。

    **单行失败不影响其他行**（用 SAVEPOINT 包住每一行）：导入是批量场景，
    一行脏数据不该让整单退回。返回统计，可直接写进 `data_import_jobs.stats`。
    """
    stats: dict = {
        "raw_written": 0,
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

    return stats


__all__ = ["persist_import_rows", "upsert_job_profile", "write_raw_job"]
