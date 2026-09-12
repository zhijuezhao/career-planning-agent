from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin.auth import require_admin
from app.domain.models.report import AIConfig
from app.domain.models.user import User
from app.infrastructure.database import get_db
from app.schemas.admin import (
    AIConfigCreate,
    AIConfigListResponse,
    AIConfigResponse,
    AIConfigUpdate,
)

router = APIRouter()


# ── AI Config ───────────────────────────────────────────────────────────────


@router.get("/configs", response_model=AIConfigListResponse)
async def list_configs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    is_active: bool | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List AI configurations with optional filtering."""
    query = select(AIConfig)
    count_query = select(func.count()).select_from(AIConfig)

    if is_active is not None:
        query = query.where(AIConfig.is_active == is_active)
        count_query = count_query.where(AIConfig.is_active == is_active)

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(AIConfig.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return AIConfigListResponse(
        total=total,
        items=[AIConfigResponse.model_validate(i) for i in items],
    )


@router.get("/configs/{config_id}", response_model=AIConfigResponse)
async def get_config(
    config_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get a single AI configuration by ID."""
    config = await db.get(AIConfig, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI config not found")
    return config


@router.post("/configs", response_model=AIConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_config(
    data: AIConfigCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new AI configuration."""
    existing = await db.execute(
        select(AIConfig).where(AIConfig.function_key == data.function_key)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="AI config with this function_key already exists",
        )

    config = AIConfig(
        function_key=data.function_key,
        provider=data.provider,
        model_name=data.model_name,
        base_url=data.base_url,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
    )
    if data.api_key:
        config.api_key_encrypted = data.api_key

    db.add(config)
    await db.flush()
    await db.refresh(config)
    return config


@router.put("/configs/{config_id}", response_model=AIConfigResponse)
async def update_config(
    config_id: int,
    data: AIConfigUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an AI configuration."""
    config = await db.get(AIConfig, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI config not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    await db.flush()
    await db.refresh(config)
    return config


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an AI configuration."""
    config = await db.get(AIConfig, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI config not found")

    await db.delete(config)
    await db.flush()


# ── Scheduler Status ────────────────────────────────────────────────────────


@router.get("/scheduler/status")
async def get_scheduler_status(
    current_user: User = Depends(require_admin),
):
    """Get the status of the adaptive scheduler."""
    from app.main import app

    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None:
        return {"status": "not_initialized", "jobs": []}

    return {
        "status": "running" if scheduler._scheduler.running else "stopped",
        "jobs": scheduler.get_job_info(),
    }
