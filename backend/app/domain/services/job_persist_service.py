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
  由唯一索引 `uq_job_profiles_title_level (title_key, level)` 在 DB 层兜底；`company_id` 列已删除。
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
from app.core.job_agent.aggregate import build_payload
from app.core.job_agent.career_fields import extract_career_fields
from app.core.job_agent.field_groups import portrait_payload
from app.core.job_agent.levels import normalise_level
from app.domain.models.job import JobProfile, JobRawData
from app.domain.services.company_service import (
    GEO_KIND_CITY,
    GEO_KIND_PROVINCE,
    link_job_company,
    normalise_geo_name,
    province_of_city,
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
    """写入一条原始岗位数据（job_raw_data）。

    B4（2026-10-03）起把「抽取结果 + 原始表字段」一并写进 `payload`：
    这些字段（`hard_skills`/`soft_skills`/`education_requirement`/
    `experience_requirement`/`code`/`district`/…）在 `job_raw_data` 上**没有列**，
    不落 payload 就等于**聚合阶段无据可依**（它正是从 payload 读组内证据的）。
    """
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
        payload=build_payload(data),
    )
    session.add(row)
    await session.flush()
    return row


async def _find_profile(
    session: AsyncSession, title_key: str, level: str
) -> JobProfile | None:
    """按 `(title_key, level)` 定位既有岗位。

    **岗位是角色级 + 分等级的**（`Java/初级`、`Java/高级`）：不含公司维度 ——
    同一个岗位被多家公司在招，是**关联表**上的多条记录，不是多条岗位
    （用户 2026-09-27 拍板的多对多模型；2026-10-03 追加等级维度）。

    ⚠️ B4 起**必须带 `level`**：唯一索引已换成 `uq_job_profiles_title_level`，
    只按 `title_key` 查会随机命中同名的另一个等级，把高级画像写到初级行上。
    """
    return (
        await session.execute(
            select(JobProfile)
            .where(JobProfile.title_key == title_key, JobProfile.level == level)
            .limit(1)
        )
    ).scalar_one_or_none()


async def upsert_job_profile(session: AsyncSession, data: dict) -> tuple[JobProfile, bool]:
    """按**`(岗位名, 等级)`** upsert 岗位；顺带 upsert 公司、写「在招关联」。

    返回 (profile, created)。title 为空抛 ValueError（调用方按行容错）。

    数据模型（2026-09-27 任务 2 起多对多；**2026-10-03 B4 加等级**）：

    - `job_profiles` = **岗位角色级 × 等级**（技能 / 晋升 / 换岗 / 证书 / 画像），
      **一行一个 `(岗位名, 等级)`**（唯一键 `uq_job_profiles_title_level`）；
    - `companies` = 公司（名称 / 规模 / 省市）；
    - `job_company_links` = 「**谁在招谁**」的**唯一真相**：一行 = 一次招聘，
      带该次招聘的所在地（省/市）、薪资、原始链接，重复出现累加 `hit_count`。

    所以「同名不同公司」= **1 条岗位 + N 条关联**（不再像 P2 那样落成 N 条岗位，
    避免把最贵的角色级内容按公司数复制）。`job_profiles.company_id` 已由任务 3 删除。

    `level` 会先经 `normalise_level()` 收敛到 初级/中级/高级/不限 ——
    否则任何自由文本都会各建一条画像（唯一键里有 level）。
    """
    raw_title = str(data.get("title") or "").strip()
    if not raw_title:
        raise ValueError("title is required")
    title = raw_title[:200]
    title_key = normalise_title(title)
    level = normalise_level(data.get("level"))

    # 招聘所在地（省/市）：归一化为**短名**（与下选项同一套规则）+ 过滤占位值
    # （老数据的 `city` 是「未知」，不能当真实地域）
    region = normalise_geo_name(data.get("region"), kind=GEO_KIND_PROVINCE)
    city = normalise_geo_name(data.get("city"), kind=GEO_KIND_CITY)
    # 表里没有「省份」列时，由城市反查省份（2026-10-03）。
    # 实测用户的 524 行表**没有省份列**，不推导的话 `companies.region` 全为 None，
    # 管理端「先选省、再选市」的省份列表就是空的（70/70 城市都能反查成功）。
    if region is None and city is not None:
        region = province_of_city(city)

    company = await upsert_company(
        session,
        data.get("company"),
        industry=data.get("industry"),
        city=city,
        region=region,
        scale=data.get("scale"),
    )

    existing = await _find_profile(session, title_key, level)

    # ── 岗位信息 vs 岗位画像（用户 2026-09-27 要求：必须分开）───────────────────
    # `career_path` / `transition_paths` / `certificates` 是**岗位信息**，一律由源文本
    # **确定性解析**得到（`career_fields.py`）。不再取自 portrait 的 `career_paths` /
    # `transition_roles` —— 那会让"重跑画像"覆盖用户自己的岗位信息，而 portrait 本身
    # 还会静默失败返回默认值（§20.1）。
    career_facts = extract_career_fields(data.get("description"), data.get("requirements"))

    if existing is not None:
        existing.industry = _pick(data, "industry", existing.industry)
        # 等级不覆盖：定位键里已经有 level，且它是**分组依据**（人工/规则已定档），
        # 让每一个路过 jobs 行随手指派等级会把分组搞乱。
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
        # B4（2026-10-03）：综合卡与薪资统计（聚合阶段的产物）。
        # 空值不覆盖：一次"只有少量招聘的岗位"不该把上次综合出来的整张卡抹掉。
        existing.salary_stats = _pick(data, "salary_stats", existing.salary_stats)
        existing.aggregate_card = _pick(data, "aggregate_card", existing.aggregate_card)
        # 画像字段交给独立写入器（白名单，只碰 PORTRAIT_FIELDS）
        apply_job_portrait(existing, data)
        profile, created = existing, False
    else:
        profile = JobProfile(
            title=title,
            industry=data.get("industry"),
            level=level,  # 已 normalise_level 收敛（唯一键的一部分）
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
            # B4（2026-10-03）：聚合阶段的产物 —— 薪资统计与可审计的综合画像卡
            salary_stats=data.get("salary_stats"),
            aggregate_card=data.get("aggregate_card"),
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
    source: str = "import",
) -> dict:
    """批量落库导入行：每行 job_raw_data + job_profiles(+companies)。

    **单行失败不影响其他行**（用 SAVEPOINT 包住每一行）：导入是批量场景，
    一行脏数据不该让整单退回。返回统计，可直接写进 `data_import_jobs.stats`。

    质检 D 级行（不合格岗位）**不落库**（2026-09-30 用户要求）：`job_raw_data`
    只存通过质检的行；D 级行的原因保留在工单 errors 摘要里
    （`_import_runner._summarize_rejections`）。此前 C 层会把 D 级行也写
    `job_raw_data`（`import:rejected` / `is_active=False`），现按用户要求移除。
    """
    stats: dict = {
        "raw_written": 0,
        "profiles_new": 0,
        "profiles_updated": 0,
        "failed": 0,
        "errors": [],
    }

    for row in rows:
        written = False
        created = False
        last_exc: Exception | None = None
        # 唯一索引 `uq_job_profiles_title_level` 会让**并发**写入同一 `(岗位名, 等级)`
        # 的第二条抛 IntegrityError。这与"这行数据脏"不是一回事：savepoint 回滚后重查一次
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

    return stats


__all__ = ["apply_job_portrait", "persist_import_rows", "upsert_job_profile", "write_raw_job"]
