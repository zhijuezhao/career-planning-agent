"""匹配明细的落库与查询（B2-3）。

落库策略：**同一快照覆盖**（先删旧行再插新行）。理由：
- 学生端可以反复点「开始匹配」，若每次追加，明细表会迅速膨胀且页面看到的会混着多次运行；
- 覆盖后「快照的最新匹配结果」语义清晰，且与 `profile_snapshots.matched_at`（最后一次匹配完成标记）一致。
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.match_record import JobMatchRecord


async def save_match_run(
    session: AsyncSession,
    *,
    snapshot_id: int,
    results: list[dict[str, Any]],
    failures: list[dict[str, Any]] | None = None,
    duration_ms: int | None = None,
) -> dict[str, int]:
    """把一次匹配运行落库（覆盖该快照的旧明细）。

    Args:
        session: 调用方事务（不在此 commit；由端点统一提交）。
        snapshot_id: 画像快照 ID。
        results: `[{job_profile_id, match_score, distance, analysis}, ...]`，已按分数倒序。
        failures: `[{job_profile_id, error}, ...]` 单岗位打分失败的行。
        duration_ms: 本次运行耗时。

    Returns:
        `{"replaced": 旧行数, "saved": 成功行数, "failed": 失败行数}`
    """
    removed = (
        await session.execute(
            delete(JobMatchRecord).where(JobMatchRecord.profile_snapshot_id == snapshot_id)
        )
    ).rowcount or 0

    saved = 0
    for index, item in enumerate(results, start=1):
        session.add(
            JobMatchRecord(
                profile_snapshot_id=snapshot_id,
                job_profile_id=int(item["job_profile_id"]),
                rank=index,
                score=item.get("match_score"),
                distance=item.get("distance"),
                status="success",
                duration_ms=duration_ms,
                analysis=item.get("analysis"),
            )
        )
        saved += 1

    failed = 0
    for failure in failures or []:
        session.add(
            JobMatchRecord(
                profile_snapshot_id=snapshot_id,
                job_profile_id=int(failure["job_profile_id"]),
                rank=0,  # 打分失败不参与排名
                score=None,
                distance=None,
                status="failed",
                duration_ms=duration_ms,
                analysis={"error": failure.get("error")},
            )
        )
        failed += 1

    await session.flush()
    logger.info(
        "匹配明细已落库 | snapshot_id={} | saved={} | failed={} | replaced={} | duration_ms={}",
        snapshot_id,
        saved,
        failed,
        removed,
        duration_ms,
    )
    return {"replaced": removed, "saved": saved, "failed": failed}


__all__ = ["save_match_run"]
