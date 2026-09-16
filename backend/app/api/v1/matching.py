from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
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
    """执行人岗匹配（读快照 embedding + 冻结六维分数，只读无副作用）。"""
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

    results = await run_matching(current_user.id, snap, body.top_k, body.max_distance, db)

    # 决策 #2：落 matched_at = now() 作为「匹配完成」标记（即使结果为 0 项也写）
    snap.matched_at = func.now()
    await db.commit()

    return MatchRunResponse(
        user_id=current_user.id,
        profile_snapshot_id=snap.id,
        total=len(results),
        results=results[:3],
    )