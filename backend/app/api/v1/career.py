from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.career import (
    CareerPathListResponse,
    CareerPathRequest,
    CareerPathResponse,
    GrowthPlanListResponse,
    GrowthPlanRequest,
    GrowthPlanResponse,
)

router = APIRouter()


@router.post("/paths", response_model=CareerPathResponse, status_code=status.HTTP_201_CREATED)
async def create_career_path(
    request: CareerPathRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """生成职业路线规划。"""
    raise HTTPException(status_code=501, detail="职业路线/成长计划功能依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.get("/paths", response_model=CareerPathListResponse)
async def list_career_paths(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的职业路线列表。"""
    raise HTTPException(status_code=501, detail="职业路线/成长计划功能依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.get("/paths/{path_id}", response_model=CareerPathResponse)
async def get_career_path_detail(
    path_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取单个职业路线详情。"""
    raise HTTPException(status_code=501, detail="职业路线/成长计划功能依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.post("/plans", response_model=GrowthPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_growth_plan(
    request: GrowthPlanRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """生成成长计划。"""
    raise HTTPException(status_code=501, detail="职业路线/成长计划功能依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.get("/plans", response_model=GrowthPlanListResponse)
async def list_growth_plans(
    growth_path_id: int | None = Query(None, description="按职业路线 ID 过滤"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的成长计划列表。"""
    raise HTTPException(status_code=501, detail="职业路线/成长计划功能依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")


@router.get("/plans/{plan_id}", response_model=GrowthPlanResponse)
async def get_growth_plan_detail(
    plan_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取单个成长计划详情。"""
    raise HTTPException(status_code=501, detail="职业路线/成长计划功能依赖已删的 GrowthPath/GrowthPlan 表，暂不提供")