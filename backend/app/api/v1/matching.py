from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.user import User
from app.domain.services.matching_service import run_matching
from app.infrastructure.database import get_db
from app.schemas.matching import MatchRunRequest, MatchRunResponse

router = APIRouter()


@router.post("/run", response_model=MatchRunResponse)
async def run_match(
    body: MatchRunRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """执行人岗匹配（读快照 embedding + 冻结六维分数），并把明细落库（B2-3）。

    落库与 `matched_at` 在**同一事务**提交：要么"这轮匹配 + 明细"一起成功，
    要么都不留痕；同一快照重复匹配会覆盖上一轮明细（见 `match_record_service`）。
    """
    snap = (
        await db.execute(
            select(ProfileSnapshot).where(
                ProfileSnapshot.id == body.profile_snapshot_id,
                ProfileSnapshot.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="快照不存在")

    outcome = await run_matching(current_user.id, snap, body.top_k, body.max_distance, db)

    # 决策 #2：落 matched_at = now() 作为「匹配完成」标记（即使结果为 0 项也写）
    snap.matched_at = func.now()
    await db.commit()

    logger.info(
        "匹配完成 | user_id={} | snapshot_id={} | hits={} | failed={} | duration_ms={}",
        current_user.id,
        snap.id,
        outcome.records_saved,
        outcome.records_failed,
        outcome.duration_ms,
    )

    return MatchRunResponse(
        user_id=current_user.id,
        profile_snapshot_id=snap.id,
        total=len(outcome.items),
        results=outcome.items[:3],
    )
