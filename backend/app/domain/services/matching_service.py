from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.matching import match_user_to_jobs
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.schemas.matching import MatchAnalysis, MatchResultItem


async def run_matching(
    user_id: int,
    snapshot: ProfileSnapshot,
    top_k: int = 10,
    max_distance: float = 0.5,
    db: AsyncSession | None = None,
) -> list[MatchResultItem]:
    """执行人岗匹配流程（只读，无副作用）。

    Args:
        user_id: 用户 ID。
        snapshot: 快照对象（含冻结 embedding + 六维分数）。
        top_k: 返回匹配数量上限。
        max_distance: 最大余弦距离阈值。
        db: 可选注入的 session。

    Returns:
        MatchResultItem 列表。
    """
    raw = await match_user_to_jobs(
        user_id=user_id,
        snapshot=snapshot,
        top_k=top_k,
        max_distance=max_distance,
        session=db,
    )
    return [
        MatchResultItem(
            job_profile_id=r["job_profile_id"],
            match_score=r["match_score"],
            distance=r["distance"],
            analysis=MatchAnalysis(**r["analysis"]),
        )
        for r in raw
    ]