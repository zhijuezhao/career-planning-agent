from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_auth
from app.core.matching.path_planner import (
    generate_career_path,
    generate_growth_plan,
    get_career_paths,
    get_growth_plans,
)
from app.domain.models.report import GrowthPath, GrowthPlan
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
    result = await generate_career_path(
        user_id=current_user.id,
        profile_id=request.profile_id,
        target_job_id=request.target_job_id,
        current_stage=request.current_stage,
        session=db,
    )
    if result is None:
        raise HTTPException(status_code=400, detail="生成职业路线失败，请检查画像和岗位是否存在")
    return result


@router.get("/paths", response_model=CareerPathListResponse)
async def list_career_paths(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的职业路线列表。"""
    count_stmt = select(func.count()).select_from(GrowthPath).where(GrowthPath.user_id == current_user.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    items = await get_career_paths(current_user.id, db, skip=skip, limit=limit)
    return CareerPathListResponse(
        total=total,
        items=[CareerPathResponse.model_validate(p) for p in items],
    )


@router.get("/paths/{path_id}", response_model=CareerPathResponse)
async def get_career_path_detail(
    path_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取单个职业路线详情。"""
    path = await db.get(GrowthPath, path_id)
    if path is None:
        raise HTTPException(status_code=404, detail="职业路线不存在")
    if path.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此职业路线")
    return path


@router.post("/plans", response_model=GrowthPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_growth_plan(
    request: GrowthPlanRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """生成成长计划。"""
    result = await generate_growth_plan(
        user_id=current_user.id,
        growth_path_id=request.growth_path_id,
        weekly_hours=request.weekly_hours,
        cycle_weeks=request.cycle_weeks,
        session=db,
    )
    if result is None:
        raise HTTPException(status_code=400, detail="生成成长计划失败，请检查职业路线是否存在")
    return result


@router.get("/plans", response_model=GrowthPlanListResponse)
async def list_growth_plans(
    growth_path_id: int | None = Query(None, description="按职业路线 ID 过滤"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的成长计划列表。"""
    count_stmt = select(func.count()).select_from(GrowthPlan).where(GrowthPlan.user_id == current_user.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    items = await get_growth_plans(current_user.id, growth_path_id, db, skip=skip, limit=limit)
    return GrowthPlanListResponse(
        total=total,
        items=[GrowthPlanResponse.model_validate(p) for p in items],
    )


@router.get("/plans/{plan_id}", response_model=GrowthPlanResponse)
async def get_growth_plan_detail(
    plan_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """获取单个成长计划详情。"""
    plan = await db.get(GrowthPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="成长计划不存在")
    if plan.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此成长计划")
    return plan
