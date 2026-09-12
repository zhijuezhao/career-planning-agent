from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.report import GrowthPath, GrowthPlan
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    GrowthPathListResponse,
    GrowthPathResponse,
    GrowthPlanListResponse,
    GrowthPlanResponse,
)

router = APIRouter()


# ── Career Paths ────────────────────────────────────────────────────────────


@router.get("/paths", response_model=GrowthPathListResponse)
async def list_career_paths(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    path_type: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List career paths with optional filtering."""
    query = select(GrowthPath)
    count_query = select(func.count()).select_from(GrowthPath)

    if user_id is not None:
        query = query.where(GrowthPath.user_id == user_id)
        count_query = count_query.where(GrowthPath.user_id == user_id)
    if path_type:
        query = query.where(GrowthPath.path_type == path_type)
        count_query = count_query.where(GrowthPath.path_type == path_type)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(GrowthPath.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return GrowthPathListResponse(
        total=total,
        items=[GrowthPathResponse.model_validate(i) for i in items],
    )


@router.get("/paths/{path_id}", response_model=GrowthPathResponse)
async def get_career_path(
    path_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single career path by ID."""
    path = await db.get(GrowthPath, path_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Career path not found")
    return path


@router.delete("/paths/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_career_path(
    path_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a career path."""
    path = await db.get(GrowthPath, path_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Career path not found")

    await db.delete(path)
    await db.flush()


# ── Growth Plans ────────────────────────────────────────────────────────────


@router.get("/plans", response_model=GrowthPlanListResponse)
async def list_growth_plans(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int | None = None,
    growth_path_id: int | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List growth plans with optional filtering."""
    query = select(GrowthPlan)
    count_query = select(func.count()).select_from(GrowthPlan)

    if user_id is not None:
        query = query.where(GrowthPlan.user_id == user_id)
        count_query = count_query.where(GrowthPlan.user_id == user_id)
    if growth_path_id is not None:
        query = query.where(GrowthPlan.growth_path_id == growth_path_id)
        count_query = count_query.where(GrowthPlan.growth_path_id == growth_path_id)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(GrowthPlan.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return GrowthPlanListResponse(
        total=total,
        items=[GrowthPlanResponse.model_validate(i) for i in items],
    )


@router.get("/plans/{plan_id}", response_model=GrowthPlanResponse)
async def get_growth_plan(
    plan_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single growth plan by ID."""
    plan = await db.get(GrowthPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Growth plan not found")
    return plan


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_growth_plan(
    plan_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a growth plan."""
    plan = await db.get(GrowthPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Growth plan not found")

    await db.delete(plan)
    await db.flush()
