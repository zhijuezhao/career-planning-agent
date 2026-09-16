from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
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
    raise HTTPException(status_code=501, detail="职业路线/成长计划管理依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.get("/paths/{path_id}", response_model=GrowthPathResponse)
async def get_career_path(
    path_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single career path by ID."""
    raise HTTPException(status_code=501, detail="职业路线/成长计划管理依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.delete("/paths/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_career_path(
    path_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a career path."""
    raise HTTPException(status_code=501, detail="职业路线/成长计划管理依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


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
    raise HTTPException(status_code=501, detail="职业路线/成长计划管理依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.get("/plans/{plan_id}", response_model=GrowthPlanResponse)
async def get_growth_plan(
    plan_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single growth plan by ID."""
    raise HTTPException(status_code=501, detail="职业路线/成长计划管理依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_growth_plan(
    plan_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a growth plan."""
    raise HTTPException(status_code=501, detail="职业路线/成长计划管理依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")