from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.domain.models import ProfileSnapshot, ReportRecord
from app.infrastructure.database import get_db
from app.schemas.journey import JourneyStatusResponse

router = APIRouter()


def derive_zone(snapshot_and_report):
    """两级判定纯函数：返回 (zone, guide_step, snapshot_id, report_id)。

    zone = "business" if 有报告 else ("guide" if 有快照 else "welcome")。
    """
    snapshot, report = snapshot_and_report
    if report:
        return "business", None, (snapshot.id if snapshot else None), report.id
    if not snapshot:
        return "welcome", None, None, None
    step = guide_step_for_snapshot(snapshot)
    return "guide", step, snapshot.id, None


def guide_step_for_snapshot(snap: ProfileSnapshot) -> Literal["resume", "parse", "match", "career"]:
    """依据快照判断当前引导步骤。

    - resume：resume_form 不完整（缺 intention / practice / hard_skills 任一层）
    - parse：画像完整但无 five_layers / dimension_scores / embedding 记录
    - match：画像完整但匹配未完成（matched_at 为 NULL）
    - career：匹配完成但尚无报告
    """
    form = snap.form_raw_json or {}
    has_intent = bool(form.get("intention"))
    has_practice = bool(form.get("practice") or form.get("campus_experiences"))
    has_skills = bool(form.get("hard_skills"))
    if not (has_intent and has_practice and has_skills):
        return "resume"
    if not (snap.five_layers_json and snap.six_dim_scores_json and snap.embedding):
        return "parse"
    if snap.matched_at is None:  # 决策 #2：matched_at 列作为匹配完成标记
        return "match"
    return "career"


@router.get("/status", response_model=JourneyStatusResponse)
async def journey_status(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_auth),
):
    snap_q = (
        select(ProfileSnapshot)
        .where(ProfileSnapshot.user_id == user.id)
        .order_by(ProfileSnapshot.created_at.desc())
        .limit(1)
    )
    snap = (await db.execute(snap_q)).scalar_one_or_none()

    report_q = (
        select(ReportRecord)
        .where(ReportRecord.user_id == user.id)
        .order_by(ReportRecord.created_at.desc())
        .limit(1)
    )
    report = (await db.execute(report_q)).scalar_one_or_none()

    cnt = (
        await db.execute(
            select(func.count(ReportRecord.id)).where(ReportRecord.user_id == user.id)
        )
    ).scalar_one()

    zone, step, snap_id, rep_id = derive_zone((snap, report))
    return JourneyStatusResponse(
        zone=zone,
        guide_step=step,
        snapshot_id=snap_id,
        report_id=rep_id,
        report_versions=cnt,
    )