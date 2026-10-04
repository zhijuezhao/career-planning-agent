"""岗位聚合编排（B4-c 的「阶段 8」）：把原始行综合成**分等级的岗位画像**。

用户 2026-10-03 拍板的顺序 **S2 + B**：

1. 规则**初判**每条招聘的等级（带依据）→ 按 `(岗位名, 等级)` 分组 → 规则**终裁**
   （不足 `MIN_GROUP_SIZE` 并入「不限」）；
2. 组内 LLM **综合**出一份「岗位综合画像卡」（取其精华去其糟粕，并显式说出丢了什么）；
3. 对**这张卡**评一次六维（而不是逐条评分再平均）。

**为什么聚合读 `job_raw_data` 而不是"边导入边算"**：

* 切片是逐片提交的，一个岗位组会跨片；只有**全部片落完之后**才看得到完整的一组；
* 逐行 upsert 是"后一条覆盖前一条"，本质上无法聚合（旧实现就是这样把 60 条招聘塌成
  最后一条的画像的）；
* 从 `job_raw_data` 重跑聚合**不用重烧抽取的 LLM 额度**。

所以本模块是**幂等**的：随时可以整表重跑，结果只由 `job_raw_data` 决定
（`scripts/rerun_aggregate.py` 走的就是这条路）。
"""

from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_agent.aggregate import (
    build_group_input,
    compute_salary_stats,
    display_title,
    group_raw_rows,
)
from app.core.job_agent.levels import LEVEL_UNLIMITED
from app.core.job_agent.tools.job_aggregator import job_aggregator
from app.core.job_agent.tools.portrait_builder import portrait_builder
from app.core.skills import (
    BONUS_SKILL_LIMIT,
    CORE_SKILL_LIMIT,
    normalise_skills,
)
from app.domain.models.job import JobRawData
from app.domain.services.job_persist_service import upsert_job_profile

__all__ = ["AGGREGATE_PROMPT_VERSION", "aggregate_roles", "raw_row_to_dict"]

#: 综合卡提示词版本 —— 落进卡片，便于"只重跑聚合"时对比两版结果的差异
AGGREGATE_PROMPT_VERSION = "job_aggregate/v1"

#: 单个岗位组最多综合多少条（护栏；正常最大组 29 条，远低于此值）
MAX_POSTINGS_PER_GROUP = 120


def raw_row_to_dict(row: JobRawData) -> dict[str, Any]:
    """把 ORM 行转成聚合层能读的 dict（列 + payload 一起带上）。"""
    return {
        "title": row.title,
        "company": row.company,
        "city": row.city,
        "salary": row.salary,
        "industry": row.industry,
        "description": row.description,
        "requirements": row.requirements,
        "payload": row.payload or {},
    }


async def _load_raw_rows(session: AsyncSession) -> list[dict]:
    """读全部原始行（只取 `is_active` 的：被停用的行不该参与综合）。"""
    result = await session.execute(
        select(JobRawData).where(JobRawData.is_active.is_(True)).order_by(JobRawData.id)
    )
    return [raw_row_to_dict(row) for row in result.scalars().all()]


async def aggregate_roles(
    session: AsyncSession,
    *,
    titles: set[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """把所有（或指定 `title_key` 的）岗位组综合成画像并落库。

    Args:
        session: 数据库会话。
        titles: 只处理这些 `title_key`（用于"只重算本次导入碰到的岗位"）；None = 全部。
        dry_run: True 时只跑 LLM、**不落库**（用于预览综合质量）。

    Returns:
        统计 dict（可直接写进 `data_import_jobs.stats.aggregate`）::

            {
              "groups": 87, "ok": 85, "failed": 2,
              "postings": 487, "elapsed_s": 210.5,
              "by_level": {"初级": 40, ...},
              "errors": ["java/初级：TimeoutError..."],
              "dry_run": false
            }
    """
    started = time.monotonic()
    rows = await _load_raw_rows(session)
    groups = group_raw_rows(rows, titles=titles)

    stats: dict[str, Any] = {
        "groups": len(groups),
        "ok": 0,
        "failed": 0,
        "skipped_empty": 0,
        "postings": 0,
        "by_level": {},
        "errors": [],
        "dry_run": dry_run,
        "prompt_version": AGGREGATE_PROMPT_VERSION,
    }

    for (title_key, level), group_rows in sorted(groups.items()):
        if not group_rows:
            stats["skipped_empty"] += 1
            continue
        if len(group_rows) > MAX_POSTINGS_PER_GROUP:
            group_rows = group_rows[:MAX_POSTINGS_PER_GROUP]

        role = display_title(group_rows) or title_key
        group_input = build_group_input(group_rows)
        salary_stats = compute_salary_stats(group_rows)
        stats["postings"] += len(group_rows)
        stats["by_level"][level] = stats["by_level"].get(level, 0) + 1

        card = await job_aggregator.ainvoke(
            {
                "group_input": group_input,
                "role": role,
                "level": level,
                "posting_count": len(group_rows),
            }
        )

        if not card.get("aggregate_ok"):
            stats["failed"] += 1
            if len(stats["errors"]) < 10:
                stats["errors"].append(f"{title_key}/{level}：{card.get('aggregate_error')}")
            logger.warning(
                "综合卡失败，跳过该组 | title={!r} | level={} | error={}",
                title_key,
                level,
                card.get("aggregate_error"),
            )
            continue

        card_payload = {
            key: value
            for key, value in card.items()
            if key not in ("aggregate_ok", "aggregate_error", "aggregate_problems")
        }
        # 把薪资统计并进卡片交给画像，让六维评分看得到真实薪资区间（而不是某一条的）
        card_payload["salary_range"] = {
            "envelope": salary_stats["envelope"],
            "median": salary_stats["median"],
        }

        portrait = await portrait_builder.ainvoke(
            {"job_data": json.dumps(card_payload, ensure_ascii=False)}
        )

        if not dry_run:
            await _upsert_group(
                session,
                title=role,
                level=level,
                salary_stats=salary_stats,
                card=card,
                card_payload=card_payload,
                portrait=portrait,
                posting_count=len(group_rows),
            )

        stats["ok"] += 1
        if not portrait.get("portrait_ok", True):
            stats.setdefault("portrait_failed", 0)
            stats["portrait_failed"] += 1

    if not dry_run:
        await session.commit()

    stats["elapsed_s"] = round(time.monotonic() - started, 1)
    logger.info(
        "岗位聚合完成 | groups={} ok={} failed={} postings={} elapsed={}s dry_run={}",
        stats["groups"],
        stats["ok"],
        stats["failed"],
        stats["postings"],
        stats["elapsed_s"],
        dry_run,
    )
    return stats


async def _upsert_group(
    session: AsyncSession,
    *,
    title: str,
    level: str,
    salary_stats: dict,
    card: dict,
    card_payload: dict,
    portrait: dict,
    posting_count: int,
) -> None:
    """把一组的综合结果写成一条 `job_profiles`（按 `(title_key, level)` 幂等）。

    B5（2026-10-03）：技能在落库前再走一遍**归一化 + 数量上限**。
    提示词里已经要求模型输出"最基础的技术名词、核心≤20 / 加分≤10"，
    但提示词是**约定**不是**保证** —— 这里做第二道防线（生成时预防 + 落库前归一双保险）。
    """
    # 归一化 + 去重 + 上限（用户 2026-10-03：核心 ≤20 / 加分 ≤10）
    core_skills = normalise_skills(card.get("core_skills"), limit=CORE_SKILL_LIMIT)
    bonus_skills = normalise_skills(card.get("bonus_skills"), limit=BONUS_SKILL_LIMIT)
    # 加分技能里若已经出现在核心技能里，就不重复（归一化后可能撞上）
    core_keys = {skill.lower() for skill in core_skills}
    bonus_skills = [skill for skill in bonus_skills if skill.lower() not in core_keys]

    data: dict[str, Any] = {
        "title": title,
        "level": level if level else LEVEL_UNLIMITED,
        # 薪资主值取**包络区间**（用户要求"两者都存"，中位数与原文在 salary_stats 里）
        "salary": salary_stats.get("envelope"),
        "salary_stats": salary_stats,
        # 岗位信息：来源表格/确定性解析，模型派生流程不许覆盖（field_groups 的约定）
        "industry": (card.get("top_industries") or [None])[0] if card.get("top_industries") else None,
        "hard_skills": {
            "tags": core_skills,
            "bonus_tags": bonus_skills,
            "source": "aggregate_card",
            "postings": posting_count,
        },
        "education_requirement": card.get("education_range"),
        "experience_requirement": card.get("experience_range"),
        # 画像：六维 + 前景 + 摘要（`portrait_payload` 会按白名单取）
        "six_dimensions": portrait.get("six_dimensions"),
        "outlook": portrait.get("outlook"),
        "summary": portrait.get("summary"),
        # 可审计的综合卡（含 excluded_noise / level_objections / 提示词版本）。
        # ⚠️ 审计三件套**显式兜底**：不能依赖调用方传进来的 `card_payload` 里恰好有它们 ——
        # "丢了什么、为什么丢、等级判得对不对"正是这张卡存在的理由。
        "aggregate_card": {
            **card_payload,
            "excluded_noise": list(card.get("excluded_noise") or []),
            "level_objections": list(card.get("level_objections") or []),
            "aggregate_problems": list(card.get("aggregate_problems") or []),
            "prompt_version": AGGREGATE_PROMPT_VERSION,
            "posting_count": posting_count,
            "portrait_ok": portrait.get("portrait_ok"),
            "portrait_error": portrait.get("portrait_error"),
        },
    }
    await upsert_job_profile(session, data)
