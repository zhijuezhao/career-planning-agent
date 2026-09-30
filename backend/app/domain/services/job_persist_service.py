"""岗位落库服务（B2-2 / B2-5 / P2）：`db_writer` 工具与导入流水线共用的 upsert 逻辑。

拆分原因：原 `db_writer._write_profile` 把「开 session + 业务 upsert」揉在一起，
导入流水线要落库时只能复制一份；现在业务逻辑集中在这里，两处调用同一实现。

合并原则与 §4.3 一致：调用方负责把「表格清洗值」放在最后合并（表格值优先），
本层只负责**空值不覆盖已有值**（`_pick`）。

B2-5：upsert 岗位画像时同时写 `job_company_links`（岗位 ↔ 公司 多对多）。

**去重键的两次收敛**：
- P2（2026-09-26 用户拍板）把粒度从「只看岗位名」改成 `(归一化岗位名, 公司)`；
- **2026-09-27 任务 2/3 又收回到「只有岗位名」**：用户改主意为**多对多** ——
  岗位是**角色级**的，同一岗位名 × N 家公司 = **1 条画像 + N 条关联**，
  不再复制最贵的角色级内容。定位只用 `job_profiles.title_key` 生成列
  （`lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))`），
  由唯一索引 `uq_job_profiles_title_key` 在 DB 层兜底；`company_id` 列已删除。
- `title_key` 是**生成列**，永远不要手写：DDL 见 `apply_ddl.py`，规则见 `core/dedup_keys.py`。

**岗位信息 vs 岗位画像（2026-09-27 用户明确要求分开）**：这两类数据此前混在同一个 upsert
里 —— portrait 的 `career_paths` / `transition_roles` 被直接写进 `career_path` /
`transition_paths`（那是**岗位信息**，用户还要二次开发）。现在：

- **岗位信息**（`field_groups.JOB_INFO_FIELDS`）：来自表格或对源文本的**确定性解析**
  （`career_fields.py`），本模块**只填空、不覆盖**；模型派生流程不许碰。
- **岗位画像**（`field_groups.PORTRAIT_FIELDS`）：只能经 `apply_job_portrait()` 写，
  该函数按白名单行事 —— 重跑画像因此**不可能**改到用户自己的岗位信息。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dedup_keys import normalise_title
from app.core.job_agent.career_fields import extract_career_fields
from app.core.job_agent.field_groups import portrait_payload
from app.domain.models.job import JobProfile, JobRawData
from app.domain.services.company_service import (
    GEO_KIND_CITY,
    GEO_KIND_PROVINCE,
    link_job_company,
    normalise_geo_name,
    refresh_job_count,
    upsert_company,
)

_EMPTY = (None, "", [], {})


def _pick(data: dict, key: str, current):
    """取新值；空值视为「本次没提供」，保留原值（避免导入缺列把已有画像抹平）。"""
    value = data.get(key)
    return current if value in _EMPTY else value


def apply_job_portrait(profile: JobProfile, data: dict) -> dict:
    """**画像写入器**：把画像字段写到 ``profile`` 上，并返回实际写入的键值。

    ⚠️ **白名单**：只碰 ``field_groups.PORTRAIT_FIELDS``（`requirement_intensity` /
    `outlook` / `summary`）。**绝不触碰岗位信息列** —— 用户 2026-09-27 明确要求
    「岗位信息」与「岗位画像」分开，前者他还要做二次开发。

    画像工具（`portrait_builder`）与重跑脚本都必须经这里写库，别直接 `setattr`。
    空值不写（"本次没提供"不等于"要清空"）。
    """
    payload = portrait_payload(data)
    for column, value in payload.items():
        setattr(profile, column, value)
    return payload


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


async def _find_profile(session: AsyncSession, title_key: str) -> JobProfile | None:
    """按 `title_key`（归一化岗位名）定位既有岗位。

    **岗位是角色级的**（`Java`、`前端开发工程师`），不含公司维度 —— 同一个岗位被多家公司
    在招，是**关联表**上的多条记录，不是多条岗位（用户 2026-09-27 拍板的多对多模型）。
    """
    return (
        await session.execute(
            select(JobProfile).where(JobProfile.title_key == title_key).limit(1)
        )
    ).scalar_one_or_none()


async def upsert_job_profile(session: AsyncSession, data: dict) -> tuple[JobProfile, bool]:
    """按**岗位名**（`title_key`）upsert 岗位；顺带 upsert 公司、写「在招关联」。

    返回 (profile, created)。title 为空抛 ValueError（调用方按行容错）。

    数据模型（2026-09-27 任务 2 起，用户拍板的**多对多**）：

    - `job_profiles` = **岗位角色级**（技能 / 晋升 / 换岗 / 证书 / 画像），**一行一个岗位名**；
    - `companies` = 公司（名称 / 规模 / 省市）；
    - `job_company_links` = 「**谁在招谁**」的**唯一真相**：一行 = 一次招聘，
      带该次招聘的所在地（省/市）、薪资、原始链接，重复出现累加 `hit_count`。

    所以「同名不同公司」= **1 条岗位 + N 条关联**（不再像 P2 那样落成 N 条岗位，
    避免把最贵的角色级内容按公司数复制）。`job_profiles.company_id` 已由任务 3 删除。
    """
    raw_title = str(data.get("title") or "").strip()
    if not raw_title:
        raise ValueError("title is required")
    title = raw_title[:200]
    title_key = normalise_title(title)

    # 招聘所在地（省/市）：归一化为**短名**（与下选项同一套规则）+ 过滤占位值
    # （老数据的 `city` 是「未知」，不能当真实地域）
    region = normalise_geo_name(data.get("region"), kind=GEO_KIND_PROVINCE)
    city = normalise_geo_name(data.get("city"), kind=GEO_KIND_CITY)

    company = await upsert_company(
        session,
        data.get("company"),
        industry=data.get("industry"),
        city=city,
        region=region,
        scale=data.get("scale"),
    )

    existing = await _find_profile(session, title_key)

    # ── 岗位信息 vs 岗位画像（用户 2026-09-27 要求：必须分开）───────────────────
    # `career_path` / `transition_paths` / `certificates` 是**岗位信息**，一律由源文本
    # **确定性解析**得到（`career_fields.py`）。不再取自 portrait 的 `career_paths` /
    # `transition_roles` —— 那会让"重跑画像"覆盖用户自己的岗位信息，而 portrait 本身
    # 还会静默失败返回默认值（§20.1）。
    career_facts = extract_career_fields(data.get("description"), data.get("requirements"))

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
        # 岗位信息里的三列：**只填空**（已有值 = 用户的既有数据/已回填结果，不覆盖）
        for column, items in career_facts.items():
            if getattr(existing, column) in _EMPTY:
                setattr(existing, column, items)
        # B3-1：链接富化产物。两列此前只在 DDL 里存在、ORM 没映射 → 谁也写不进去；
        # 现在补上映射（见 `models/job.py`）。同样只填空：后来的"没有链接的导入"
        # 不该把上一次富化拿到的来源与统计抹掉。
        existing.source_url = _pick(data, "source_url", existing.source_url)
        existing.enrich_stats = _pick(data, "enrich_stats", existing.enrich_stats)
        # 画像字段交给独立写入器（白名单，只碰 PORTRAIT_FIELDS）
        apply_job_portrait(existing, data)
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
            career_path=career_facts.get("career_path") or None,
            transition_paths=career_facts.get("transition_paths") or None,
            certificates=career_facts.get("certificates") or None,
            # B3-1：链接来源与富化统计（无链接导入时为 None）
            source_url=data.get("source_url"),
            enrich_stats=data.get("enrich_stats"),
            # ⚠️ 不写 `company_id`：岗位是角色级的，公司归属全在 `job_company_links`。
            #    该列已由任务 3 从表上删除，留着只会造成"两个真相来源"。
        )
        # 画像字段仍走同一个白名单写入器，保证"新建"和"更新"两条路的口径一致
        apply_job_portrait(profile, data)
        session.add(profile)
        created = True

    await session.flush()

    if company is not None:
        # 关联表是「谁在招谁」的**唯一真相**；一次招聘自带所在地/薪资/链接
        await link_job_company(
            session,
            job_profile_id=profile.id,
            company_id=company.id,
            source=str(data.get("source") or "import")[:20],
            region=region,
            city=city,
            salary=data.get("salary"),
            source_url=data.get("source_url"),
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
        written = False
        created = False
        last_exc: Exception | None = None
        # 唯一索引 `uq_job_profiles_title_key` 会让**并发**写入同一岗位名的第二条
        # 抛 IntegrityError。这与"这行数据脏"不是一回事：savepoint 回滚后重查一次
        # 即可转成 update（赢家那条已经落定）。
        for attempt in (1, 2):
            try:
                async with session.begin_nested():  # 行级 SAVEPOINT
                    await write_raw_job(session, {**row, "source": source})
                    _profile, created = await upsert_job_profile(session, row)
                written = True
                break
            except IntegrityError as exc:
                last_exc = exc
                logger.warning(
                    "岗位唯一键冲突（多为并发导入同一岗位），重试 | title={!r} | attempt={} | error={}",
                    row.get("title"),
                    attempt,
                    getattr(exc, "orig", exc),
                )
            except Exception as exc:  # noqa: BLE001 - 行级容错
                last_exc = exc
                break

        if written:
            # 计数放在 savepoint 正常退出之后：行内失败时计数不应虚增
            stats["raw_written"] += 1
            stats["profiles_new" if created else "profiles_updated"] += 1
        else:
            stats["failed"] += 1
            if len(stats["errors"]) < 5:
                title = row.get("title") or "未知岗位"
                stats["errors"].append(f"{title}：{last_exc}"[:200])
            logger.warning("导入行落库失败 | title={!r} | error={}", row.get("title"), last_exc)

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


__all__ = ["apply_job_portrait", "persist_import_rows", "upsert_job_profile", "write_raw_job"]
