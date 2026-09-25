from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.matching import match_user_to_jobs_detailed
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.services.match_record_service import save_match_run
from app.schemas.matching import MatchAnalysis, MatchResultItem


@dataclass
class MatchRunOutcome:
    """一次匹配运行的完整结果（B2-3）。

    `items` 保持与旧 `run_matching` 返回的 `list[MatchResultItem]` 一致（学生端契约不变），
    额外带出耗时、单岗位失败与落库计数，供端点/日志/管理端明细使用。
    """

    items: list[MatchResultItem] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    records_saved: int = 0
    records_failed: int = 0
    records_replaced: int = 0


async def run_matching(
    user_id: int,
    snapshot: ProfileSnapshot,
    top_k: int = 10,
    max_distance: float = 0.5,
    db: AsyncSession | None = None,
) -> MatchRunOutcome:
    """执行人岗匹配并把明细落库（B2-3）。

    匹配本身仍然是只读计算；落库写在调用方事务里（端点随后 commit，
    与 `profile_snapshots.matched_at` 同事务），**同一快照覆盖上一轮明细**。

    Args:
        user_id: 用户 ID。
        snapshot: 快照对象（含冻结 embedding + 六维分数）。
        top_k: 返回匹配数量上限。
        max_distance: 最大余弦距离阈值。
        db: session；传 None 则只算不落库（测试/纯计算场景）。

    Returns:
        `MatchRunOutcome`。
    """
    started = time.perf_counter()
    raw, failures = await match_user_to_jobs_detailed(
        user_id=user_id,
        snapshot=snapshot,
        top_k=top_k,
        max_distance=max_distance,
        session=db,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)

    items = [
        MatchResultItem(
            job_profile_id=r["job_profile_id"],
            match_score=r["match_score"],
            distance=r["distance"],
            analysis=MatchAnalysis(**r["analysis"]),
        )
        for r in raw
    ]

    outcome = MatchRunOutcome(items=items, failures=failures, duration_ms=duration_ms)

    if db is None:
        logger.warning(
            "run_matching 未传 session，匹配明细不落库 | user_id={} | snapshot_id={}",
            user_id,
            snapshot.id,
        )
        return outcome

    stats = await save_match_run(
        db,
        snapshot_id=snapshot.id,
        results=raw,
        failures=failures,
        duration_ms=duration_ms,
    )
    outcome.records_saved = stats["saved"]
    outcome.records_failed = stats["failed"]
    outcome.records_replaced = stats["replaced"]
    return outcome
