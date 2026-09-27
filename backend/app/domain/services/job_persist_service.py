"""岗位落库服务（B2-2 / B2-5 / P2）：`db_writer` 工具与导入流水线共用的 upsert 逻辑。

拆分原因：原 `db_writer._write_profile` 把「开 session + 业务 upsert」揉在一起，
导入流水线要落库时只能复制一份；现在业务逻辑集中在这里，两处调用同一实现。

合并原则与 §4.3 一致：调用方负责把「表格清洗值」放在最后合并（表格值优先），
本层只负责**空值不覆盖已有值**（`_pick`）。

B2-5：upsert 岗位画像时同时写 `job_company_links`（岗位 ↔ 公司 多对多）。

**P2（2026-09-26 用户拍板）**：去重粒度由「只看岗位名」改为 **`(归一化岗位名, 公司)`** ——
同一岗位名 × N 家公司 = **N 条画像**。要点：

1. 定位用 `job_profiles.title_key` 生成列（`lower(regexp_replace(btrim(title), '\\s+', ' ', 'g'))`）
   + `company_id`，并由唯一索引 `uq_job_profiles_title_company` 在 DB 层兜底；
2. **公司未知 ≠ 另一家公司**：没有公司列时 `company_id IS NULL` 只是"未知桶"。
   含公司数据首次出现时，**收养**（adopt）此前"公司未知"的同名画像而不是新建一条，
   否则用户"先导职业路线表、再导含公司表"会把同一个岗位裂成两条；
3. `title_key` 是**生成列**，永远不要手写：DDL 见 `apply_ddl.py`，规则见 `core/dedup_keys.py`。

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
    link_job_company,
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


async def _find_profile(
    session: AsyncSession, title_key: str, company_id: int | None
) -> tuple[JobProfile | None, bool]:
    """按 `(title_key, company_id)` 定位既有画像。

    返回 `(画像或 None, 是否需要把 company_id 落定)`。

    公司已知时：先找精确的 `(title_key, company_id)`；没有就**收养**同名的
    "公司未知"（`company_id IS NULL`）画像 —— 这是"先导无公司表、再导含公司表"
    不产生重复岗位的关键。
    公司未知时：先找"未知桶"；没有就退让到该岗位名下 id 最小的一条
    （"未知"没有区分能力，不该把一个已有岗位裂成两条）。
    """
    base = select(JobProfile).where(JobProfile.title_key == title_key)

    if company_id is not None:
        hit = (
            await session.execute(base.where(JobProfile.company_id == company_id).limit(1))
        ).scalar_one_or_none()
        if hit is not None:
            return hit, False
        adopted = (
            await session.execute(base.where(JobProfile.company_id.is_(None)).limit(1))
        ).scalar_one_or_none()
        return adopted, adopted is not None

    hit = (
        await session.execute(base.where(JobProfile.company_id.is_(None)).limit(1))
    ).scalar_one_or_none()
    if hit is not None:
        return hit, False
    fallback = (
        await session.execute(base.order_by(JobProfile.id).limit(1))
    ).scalar_one_or_none()
    return fallback, False


async def upsert_job_profile(session: AsyncSession, data: dict) -> tuple[JobProfile, bool]:
    """按 `(岗位名, 公司)` 去重 upsert 岗位画像；顺带 upsert 公司、写「岗位↔公司」关联。

    返回 (profile, created)。title 为空抛 ValueError（调用方按行容错）。

    公司归属（P2 起）：`job_profiles.company_id` 就是键的一部分（每个岗位一条公司），
    不再需要 B2-5 那个"首次为准、后续不覆盖"的补丁 —— 同名不同公司本来就会落成两条画像；
    `job_company_links` 仍然记录全部在招公司（B3 链接富化与历史来源要用）。
    """
    raw_title = str(data.get("title") or "").strip()
    if not raw_title:
        raise ValueError("title is required")
    title = raw_title[:200]
    title_key = normalise_title(title)

    company = await upsert_company(
        session, data.get("company"), industry=data.get("industry"), city=data.get("city")
    )

    existing, adopt_company = await _find_profile(
        session, title_key, company.id if company is not None else None
    )

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
        # 画像字段交给独立写入器（白名单，只碰 PORTRAIT_FIELDS）
        apply_job_portrait(existing, data)
        if company is not None and (adopt_company or existing.company_id is None):
            # 收养"公司未知"的同名画像：把公司落定，让键从 (title, NULL) 变成 (title, 公司)。
            # 只在精确键不存在时才走到这里，故不会撞唯一索引（并发竞态由调用方重试兜底）。
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
            career_path=career_facts.get("career_path") or None,
            transition_paths=career_facts.get("transition_paths") or None,
            certificates=career_facts.get("certificates") or None,
            company_id=company.id if company is not None else None,
        )
        # 画像字段仍走同一个白名单写入器，保证"新建"和"更新"两条路的口径一致
        apply_job_portrait(profile, data)
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
        written = False
        created = False
        last_exc: Exception | None = None
        # P2：唯一索引 `uq_job_profiles_title_company` 会让**并发**写入同一
        # `(岗位名, 公司)` 的第二条抛 IntegrityError。这与"这行数据脏"不是一回事：
        # savepoint 回滚后重查一次即可转成 update（赢家那条已经落定）。
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
