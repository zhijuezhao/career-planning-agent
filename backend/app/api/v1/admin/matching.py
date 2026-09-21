from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.dimension_weight import DimensionWeight
from app.domain.models.profile_snapshot import ProfileSnapshot
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    AdminSnapshotDetail,
    AdminSnapshotListResponse,
    AdminSnapshotSummary,
    DimensionWeightCreate,
    DimensionWeightListResponse,
    DimensionWeightResponse,
    DimensionWeightUpdate,
)

router = APIRouter()


# ── 画像快照（替代原「匹配结果」：匹配明细已不落表，改为看快照与匹配状态，D9）──


def _to_summary(row) -> AdminSnapshotSummary:
    """Row（列表，按列选取）与 ORM 对象（详情）都能用。"""
    return AdminSnapshotSummary(
        id=row.id,
        user_id=row.user_id,
        profile_id=row.profile_id,
        serial_no=row.serial_no,
        description=row.description,
        matched=row.matched_at is not None,
        matched_at=row.matched_at,
        created_at=row.created_at,
        six_dim_scores=row.six_dim_scores_json or {},
    )


@router.get("/snapshots", response_model=AdminSnapshotListResponse)
async def list_snapshots(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    matched: bool | None = Query(None, description="true=已匹配 / false=待匹配"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """画像快照列表（含匹配状态）。

    只选取列表需要的列 —— 不加载 embedding 向量（1024 维 × 每行）。
    """
    columns = (
        ProfileSnapshot.id,
        ProfileSnapshot.user_id,
        ProfileSnapshot.profile_id,
        ProfileSnapshot.serial_no,
        ProfileSnapshot.description,
        ProfileSnapshot.matched_at,
        ProfileSnapshot.created_at,
        ProfileSnapshot.six_dim_scores_json,
    )
    query = select(*columns)
    count_query = select(func.count()).select_from(ProfileSnapshot)

    if user_id is not None:
        query = query.where(ProfileSnapshot.user_id == user_id)
        count_query = count_query.where(ProfileSnapshot.user_id == user_id)
    if matched is not None:
        cond = (
            ProfileSnapshot.matched_at.isnot(None)
            if matched
            else ProfileSnapshot.matched_at.is_(None)
        )
        query = query.where(cond)
        count_query = count_query.where(cond)

    total = (await db.execute(count_query)).scalar() or 0
    rows = (
        await db.execute(query.order_by(ProfileSnapshot.id.desc()).offset(skip).limit(limit))
    ).all()

    return AdminSnapshotListResponse(total=total, items=[_to_summary(r) for r in rows])


@router.get("/snapshots/{snapshot_id}", response_model=AdminSnapshotDetail)
async def get_snapshot(
    snapshot_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """画像快照详情（五层画像 + 冻结的六维分数 + 原始表单）。"""
    snap = await db.get(ProfileSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="画像快照不存在")
    return AdminSnapshotDetail(
        **_to_summary(snap).model_dump(),
        five_layers=snap.five_layers_json or {},
        form_raw=snap.form_raw_json or {},
        embedding_dim=len(snap.embedding) if snap.embedding is not None else None,
    )


# ── Dimension Weights ───────────────────────────────────────────────────────


@router.get("/weights", response_model=DimensionWeightListResponse)
async def list_dimension_weights(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    job_category: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List dimension weights with optional filtering."""
    query = select(DimensionWeight)
    count_query = select(func.count()).select_from(DimensionWeight)

    if job_category:
        query = query.where(DimensionWeight.job_category == job_category)
        count_query = count_query.where(DimensionWeight.job_category == job_category)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(DimensionWeight.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return DimensionWeightListResponse(
        total=total,
        items=[DimensionWeightResponse.model_validate(i) for i in items],
    )


@router.get("/weights/{weight_id}", response_model=DimensionWeightResponse)
async def get_dimension_weight(
    weight_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single dimension weight by ID."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")
    return weight


@router.post("/weights", response_model=DimensionWeightResponse, status_code=status.HTTP_201_CREATED)
async def create_dimension_weight(
    data: DimensionWeightCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new dimension weight."""
    existing = await db.execute(
        select(DimensionWeight).where(
            DimensionWeight.job_category == data.job_category,
            DimensionWeight.top_dimension == data.top_dimension,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Dimension weight for this category and dimension already exists",
        )

    weight = DimensionWeight(**data.model_dump())
    db.add(weight)
    await db.flush()
    await db.refresh(weight)
    return weight


@router.put("/weights/{weight_id}", response_model=DimensionWeightResponse)
async def update_dimension_weight(
    weight_id: int,
    data: DimensionWeightUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a dimension weight."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")

    weight.weight = data.weight
    await db.flush()
    await db.refresh(weight)
    return weight


@router.delete("/weights/{weight_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dimension_weight(
    weight_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a dimension weight."""
    weight = await db.get(DimensionWeight, weight_id)
    if weight is None:
        raise HTTPException(status_code=404, detail="Dimension weight not found")

    await db.delete(weight)
    await db.flush()
