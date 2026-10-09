from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.api.v1.snapshot_task import get_task, start_snapshot_task
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.student_profile import StudentProfile
from app.domain.models.user import User
from app.domain.services.snapshot_service import create_profile_snapshot
from app.infrastructure.database import async_session_factory, get_db
from app.schemas.profile import (
    ProfileResponse,
    ProfileUpdate,
    SnapshotCreateResponse,
    SnapshotDetailResponse,
    SnapshotPollResponse,
    SnapshotSummary,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── resume_form 存取（纯存储，前端组装展开结构）───────────────────────────────


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = (
        await db.execute(
            select(StudentProfile).where(StudentProfile.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    return ProfileResponse(resume_form=profile.resume_form if profile else {})


@router.put("/profile", response_model=ProfileResponse)
async def put_profile(
    body: ProfileUpdate,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = (
        await db.execute(
            select(StudentProfile).where(StudentProfile.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if profile is None:
        profile = StudentProfile(user_id=current_user.id)
        db.add(profile)
    profile.resume_form = body.resume_form
    await db.commit()
    await db.refresh(profile)
    return ProfileResponse(resume_form=profile.resume_form)


# ── 快照：异步创建 + 轮询 + 列表 + 详情 ──────────────────────────────────────


async def _run_snapshot_bg(user_id: int, sleep: float = 0.5) -> object:
    """后台任务：等待请求 session 释放后再开独立 session 建快照。"""
    await asyncio.sleep(sleep)
    async with async_session_factory() as session:
        return await create_profile_snapshot(user_id, session)


@router.post("/profile/snapshot", response_model=SnapshotCreateResponse)
async def create_snapshot(
    current_user: User = Depends(require_auth),
) -> SnapshotCreateResponse:
    task_id = start_snapshot_task(
        lambda tid: _run_snapshot_bg(current_user.id)  # noqa: ARG005
    )
    return SnapshotCreateResponse(task_id=task_id)


@router.get("/profile/snapshot/{task_id}", response_model=SnapshotPollResponse)
async def poll_snapshot(
    task_id: str,
    current_user: User = Depends(require_auth),
) -> SnapshotPollResponse:
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] == "failed":
        return SnapshotPollResponse(status="failed", message=task["message"])
    if task["status"] == "done":
        return SnapshotPollResponse(status="done", snapshot_id=task["snapshot_id"])
    return SnapshotPollResponse(status="running")


@router.get("/profile/snapshots", response_model=list[SnapshotSummary])
async def list_snapshots(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[SnapshotSummary]:
    rows = (
        await db.execute(
            select(ProfileSnapshot)
            .where(ProfileSnapshot.user_id == current_user.id)
            .order_by(ProfileSnapshot.created_at.desc())
        )
    ).scalars().all()
    return [
        SnapshotSummary(
            id=s.id,
            serial_no=s.serial_no,
            description=s.description,
            created_at=s.created_at,
        )
        for s in rows
    ]


@router.get("/profile/snapshots/{sid}", response_model=SnapshotDetailResponse)
async def snapshot_detail(
    sid: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> SnapshotDetailResponse:
    snap = (
        await db.execute(
            select(ProfileSnapshot).where(
                ProfileSnapshot.id == sid,
                ProfileSnapshot.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return SnapshotDetailResponse(
        id=snap.id,
        serial_no=snap.serial_no,
        description=snap.description,
        created_at=snap.created_at,
        form=snap.form_raw_json,
        five_layers=snap.five_layers_json,
        dimension_scores=snap.six_dim_scores_json,
        # 不能用 `bool(snap.embedding)`：pgvector 给出的是 numpy 数组，
        # 多元素数组真值判断会抛 ValueError（2026-10-09 CI 实测）
        has_embedding=snap.embedding is not None and len(snap.embedding) > 0,
    )
